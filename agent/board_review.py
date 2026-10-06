"""Deterministic aggregation used by the single comprehensive Board Review."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Optional

from .sprint_health import ACTIVE_STATES, DONE_STATES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(item: dict[str, Any]) -> str:
    return str(item.get("state") or "Unknown")


def _is_done(item: dict[str, Any]) -> bool:
    return _state(item).casefold().strip() in DONE_STATES


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _risk_order(risk: str) -> int:
    return {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
        "HEALTHY": 4,
        "UNKNOWN": 5,
    }.get(str(risk).upper(), 99)


# ---------------------------------------------------------------------------
# Main Board Review aggregation
# ---------------------------------------------------------------------------

def build_board_review(
    items: list[dict[str, Any]],
    sprint_health: Optional[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    """
    Build the deterministic data model consumed by the comprehensive
    Board Review and audit report.

    This function does not call an LLM.

    sprint_health is the authoritative source for:
        - sprint timing
        - item aging
        - time in current state
        - inactivity
        - deadline exposure
        - deterministic risk
        - workload concentration
        - health score

    Azure DevOps work-item data remains the source of truth for:
        - state
        - owner
        - priority
        - relationships
        - work-item identity
    """

    # -----------------------------------------------------------------------
    # Board distributions
    # -----------------------------------------------------------------------

    states = Counter(
        _state(item)
        for item in items
    )

    priorities = Counter(
        str(
            item.get("priority")
            if item.get("priority") is not None
            else "Unspecified"
        )
        for item in items
    )

    completed_items = [
        item
        for item in items
        if _is_done(item)
    ]

    unfinished_items = [
        item
        for item in items
        if not _is_done(item)
    ]

    new_items = [
        item
        for item in unfinished_items
        if _state(item).casefold().strip()
        in {"new", "to do", "todo", "approved"}
    ]

    active_items = [
        item
        for item in unfinished_items
        if _state(item).casefold().strip()
        in ACTIVE_STATES
    ]

    # Exact-title collisions are an audit signal only. They do not prove that
    # two work items are duplicates; they identify scope that merits review.
    title_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in unfinished_items:
        title = str(item.get("title") or "").strip()
        if title:
            title_groups[title.casefold()].append(item)

    duplicate_title_groups = [
        {
            "title": group[0].get("title"),
            "work_item_ids": [item.get("id") for item in group if item.get("id") is not None],
        }
        for group in title_groups.values()
        if len(group) >= 2
    ]
    duplicate_title_groups.sort(key=lambda entry: (-len(entry["work_item_ids"]), str(entry["title"]).casefold()))

    unassigned = [
        item.get("id")
        for item in unfinished_items
        if not item.get("assigned_to")
    ]

    completion_rate = (
        len(completed_items) / len(items) * 100
        if items
        else 0.0
    )
    new_count = len(new_items)

    # -----------------------------------------------------------------------
    # Workload aggregation
    # -----------------------------------------------------------------------

    by_owner: dict[str, Counter] = defaultdict(Counter)

    for item in items:
        owner = item.get("assigned_to") or "Unassigned"
        state = _state(item)

        by_owner[owner]["total"] += 1
        by_owner[owner][state] += 1

        if not _is_done(item):
            by_owner[owner]["unfinished"] += 1

        if state.casefold().strip() in ACTIVE_STATES:
            by_owner[owner]["active"] += 1

        if state.casefold().strip() in {
            "new",
            "to do",
            "todo",
            "approved",
        }:
            by_owner[owner]["new"] += 1

        if state.casefold().strip() in {
            "resolved",
            "done",
            "completed",
        }:
            by_owner[owner]["resolved"] += 1

        if state.casefold().strip() in {
            "closed",
            "removed",
        }:
            by_owner[owner]["closed"] += 1

    total_unfinished = sum(values["unfinished"] for values in by_owner.values())
    total_active = sum(values["active"] for values in by_owner.values())

    workload = []

    for owner, values in sorted(
        by_owner.items(),
        key=lambda pair: (
            -pair[1]["unfinished"],
            pair[0],
        ),
    ):
        active_count = values["active"]
        board_share = (values["unfinished"] / total_unfinished) if total_unfinished else 0.0
        active_share = (active_count / total_active) if total_active else 0.0

        # Concentration is based on active work, while Board Share shows the
        # owner's share of all unfinished scope. This avoids equating New work
        # with active execution load.
        concentration_share = active_share if total_active else board_share
        # Relative share alone is misleading on tiny active populations
        # (e.g. one of two active items = 50%). Require a meaningful active
        # item count before escalating workload concentration.
        if active_count >= 4 and concentration_share >= 0.50:
            concentration = "HIGH"
        elif active_count >= 3 and concentration_share >= 0.35:
            concentration = "ELEVATED"
        elif active_count >= 2 and concentration_share >= 0.25:
            concentration = "WATCH"
        else:
            concentration = "NORMAL"

        workload.append(
            {
                "owner": owner,
                "total_items": values["total"],
                "new_items": values["new"],
                "active_items": values["active"],
                "resolved_items": values["resolved"],
                "closed_items": values["closed"],
                "unfinished_items": values["unfinished"],

                # Backward-compatible alias.
                "in_scope_items": values["unfinished"],

                "board_share": round(board_share * 100, 1),
                "active_work_pct": round(active_share * 100, 1),

                "concentration": concentration,

                "status": (
                    "HIGH RISK"
                    if concentration == "HIGH"
                    else "AT RISK"
                    if concentration == "ELEVATED"
                    else "WATCH"
                    if concentration == "WATCH"
                    else "NORMAL"
                ),
            }
        )

    # -----------------------------------------------------------------------
    # Sprint-health data
    # -----------------------------------------------------------------------

    sprint_summary: dict[str, Any] = {}
    sprint_findings: list[dict[str, Any]] = []
    aging_items: list[dict[str, Any]] = []
    deadline_risks: list[dict[str, Any]] = []
    health_status = "UNKNOWN"
    health_score = None

    if sprint_health:

        sprint_summary = sprint_health.get(
            "summary",
            {},
        ) or {}

        sprint_findings = sprint_health.get(
            "findings",
            [],
        ) or []

        aging_items = sprint_health.get(
            "aging_items",
            [],
        ) or []

        deadline_risks = sprint_health.get(
            "deadline_risks",
            [],
        ) or []

        health_status = (
            sprint_health.get("overall_status")
            or sprint_health.get("overall_health")
            or sprint_health.get("health_status")
            or "UNKNOWN"
        )

        health_score = sprint_health.get(
            "health_score"
        )

    # -----------------------------------------------------------------------
    # Time-based metrics
    # -----------------------------------------------------------------------

    timing = (
        sprint_health.get("timing", {})
        if sprint_health
        else {}
    ) or {}

    timing_available = bool(
        sprint_health
        and sprint_health.get(
            "timing_available",
            True,
        )
    )

    sprint_elapsed_pct = timing.get(
        "elapsed_pct"
    )

    if sprint_elapsed_pct is not None:
        sprint_elapsed_pct = round(
            float(sprint_elapsed_pct) * 100,
            1,
        )

    completion_vs_time_gap = None

    if sprint_elapsed_pct is not None:
        completion_vs_time_gap = round(
            sprint_elapsed_pct - completion_rate,
            1,
        )

    elapsed_days = timing.get("elapsed_days")
    remaining_days = timing.get("remaining_days")
    observed_completion_pace = (
        len(completed_items) / elapsed_days
        if isinstance(elapsed_days, (int, float)) and elapsed_days > 0
        else None
    )
    required_completion_pace = (
        len(unfinished_items) / remaining_days
        if isinstance(remaining_days, (int, float)) and remaining_days > 0
        else None
    )
    pace_ratio = (
        required_completion_pace / observed_completion_pace
        if observed_completion_pace and required_completion_pace is not None
        else None
    )

    # -----------------------------------------------------------------------
    # Aging analysis
    # -----------------------------------------------------------------------

    # The sprint-health module is authoritative. We only normalize the data
    # here so audit.py has a predictable schema.

    normalized_aging = []

    for item in aging_items:

        normalized_aging.append(
            {
                "work_item_id": item.get(
                    "work_item_id"
                ),
                "title": item.get("title"),
                "state": item.get("state"),
                "owner": item.get("owner")
                or "Unassigned",

                "item_age_days": item.get(
                    "item_age_days"
                ),

                "days_in_current_state": item.get(
                    "days_in_current_state"
                ),

                "days_since_update": item.get(
                    "days_since_update"
                ),

                "risk": item.get(
                    "risk",
                    "UNKNOWN",
                ),

                "reason": item.get(
                    "reason"
                ),

                "evidence": (
                    "Item age: "
                    f"{item.get('item_age_days')} days"
                    if item.get("item_age_days") is not None
                    else "Item age unavailable"
                ),

                "state_duration_evidence": (
                    "Time in current state: "
                    f"{item.get('days_in_current_state')} days"
                    if item.get(
                        "days_in_current_state"
                    ) is not None
                    else "Time in current state unknown"
                ),

                "activity_evidence": (
                    "Last update: "
                    f"{item.get('days_since_update')} days ago"
                    if item.get(
                        "days_since_update"
                    ) is not None
                    else "Last update timestamp unavailable"
                ),
            }
        )

    normalized_aging.sort(
        key=lambda item: (
            _risk_order(item.get("risk", "UNKNOWN")),
            -(
                item.get("days_in_current_state")
                if item.get("days_in_current_state") is not None
                else -1
            ),
            -(
                item.get("item_age_days")
                if item.get("item_age_days") is not None
                else -1
            ),
        )
    )

    # -----------------------------------------------------------------------
    # Deadline analysis
    # -----------------------------------------------------------------------

    normalized_deadlines = []

    for item in deadline_risks:

        normalized_deadlines.append(
            {
                "work_item_id": item.get(
                    "work_item_id"
                ),
                "title": item.get("title"),
                "state": item.get("state"),
                "owner": item.get("owner")
                or "Unassigned",
                "target_date": item.get(
                    "target_date"
                ),
                "due_status": item.get(
                    "due_status",
                    "UNKNOWN",
                ),
                "risk": item.get(
                    "risk",
                    "UNKNOWN",
                ),
                "reason": item.get("reason") or item.get("evidence"),
            }
        )

    normalized_deadlines.sort(
        key=lambda item: (
            _risk_order(item.get("risk", "UNKNOWN")),
            str(item.get("target_date") or ""),
        )
    )

    # -----------------------------------------------------------------------
    # RAID — Risks
    # -----------------------------------------------------------------------
    # Risks are forward-looking conditions. Keep them distinct from the
    # confirmed Current Issues register and build them from concrete
    # normalized signals rather than every per-item finding.

    risks: list[dict[str, Any]] = []

    limited_progress_count = sum(
        1
        for finding in sprint_findings
        if finding.get("progress_observed") is False
        and not _is_done(next((item for item in items if item.get("id") == finding.get("work_item_id")), {}))
    )

    if normalized_deadlines:
        overdue = sum(1 for x in normalized_deadlines if str(x.get("due_status")).upper() == "OVERDUE")
        due_today = sum(1 for x in normalized_deadlines if str(x.get("due_status")).upper() == "DUE_TODAY")
        due_soon = sum(1 for x in normalized_deadlines if str(x.get("due_status")).upper() == "DUE_SOON")
        parts = []
        if overdue:
            parts.append(f"{overdue} overdue")
        if due_today:
            parts.append(f"{due_today} due today")
        if due_soon:
            parts.append(f"{due_soon} due soon")
        risks.append({
            "work_item_id": None,
            "affected_work_item_ids": [x.get("work_item_id") for x in normalized_deadlines if x.get("work_item_id") is not None],
            "severity": "CRITICAL" if overdue or due_today else "HIGH",
            "risk": f"{len(normalized_deadlines)} unfinished item(s) have deadline exposure.",
            "observed": f"Observed deadline exposure: {', '.join(parts)}.",
            "inferred": "Deadline exposure may affect sprint delivery commitments if the affected scope is not completed or re-planned.",
            "evidence": f"Affected work items: {', '.join('#'+str(x.get('work_item_id')) for x in normalized_deadlines[:20])}",
            "impact": "Deadline exposure may affect sprint delivery commitments.",
            "owner": "Team" if len({x.get("owner") for x in normalized_deadlines}) != 1 else (normalized_deadlines[0].get("owner") or "Team"),
            "recommendation": "Review overdue and due-today items first; confirm scope, ownership and delivery dates.",
        })

    if new_count >= 3 and timing_available and sprint_elapsed_pct >= 35:
        new_ids = [item.get("id") for item in new_items if item.get("id") is not None]
        risks.append({
            "work_item_id": None,
            "affected_work_item_ids": new_ids,
            "severity": "HIGH" if sprint_elapsed_pct >= 65 else "MEDIUM",
            "risk": f"{new_count} unfinished item(s) remain unstarted in the New state.",
            "observed": f"{sprint_elapsed_pct:.1f}% of the sprint has elapsed while {new_count} items remain New.",
            "inferred": "If the New items are committed sprint scope, late activation could increase delivery pressure.",
            "evidence": f"Affected work items: {', '.join('#'+str(x) for x in new_ids[:20])}",
            "impact": "Late activation may reduce remaining execution time for committed scope.",
            "owner": "Team",
            "recommendation": "Confirm which New items are committed scope and whether they remain feasible within the remaining sprint window.",
        })

    if normalized_aging:
        aging_ids = [x.get("work_item_id") for x in normalized_aging if x.get("work_item_id") is not None]
        risks.append({
            "work_item_id": None,
            "affected_work_item_ids": aging_ids,
            "severity": "HIGH" if any(str(x.get("risk")).upper() in {"HIGH", "CRITICAL"} for x in normalized_aging) else "MEDIUM",
            "risk": f"{len(normalized_aging)} unfinished item(s) meet the deterministic aging criteria.",
            "observed": "Age and/or time-in-current-state thresholds were exceeded for the affected items.",
            "inferred": "Aging scope may reduce delivery flexibility if it remains unresolved.",
            "evidence": f"Affected work items: {', '.join('#'+str(x) for x in aging_ids[:20])}",
            "impact": "Long-running work may require reprioritization or direct delivery attention.",
            "owner": "Team",
            "recommendation": "Review the oldest and longest-running items for readiness, blockers and prioritization.",
        })

    if limited_progress_count >= 3:
        limited_ids = [f.get("work_item_id") for f in sprint_findings if f.get("progress_observed") is False and f.get("work_item_id") is not None]
        risks.append({
            "work_item_id": None,
            "affected_work_item_ids": limited_ids,
            "severity": "HIGH" if sprint_elapsed_pct >= 65 else "MEDIUM",
            "risk": f"{limited_progress_count} unfinished item(s) have no confirmed progress signal since sprint start.",
            "observed": "Available Azure DevOps timestamps do not show state progression or item updates during the sprint for the affected items.",
            "inferred": "This is an attention signal only; it does not prove that work has stopped.",
            "evidence": f"Affected work items: {', '.join('#'+str(x) for x in limited_ids[:20])}",
            "impact": "Unconfirmed progress may reduce visibility into delivery readiness.",
            "owner": "Team",
            "recommendation": "Review the affected items directly and confirm current delivery status.",
        })

    risks.sort(key=lambda x: ({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(str(x.get("severity")).upper(), 9), str(x.get("risk", ""))))

    # -----------------------------------------------------------------------
    # RAID — Issues
    # -----------------------------------------------------------------------
    # Issues represent current, evidence-backed conditions. Similar item-level
    # findings are grouped so the executive register stays useful instead of
    # producing dozens of near-identical rows.
    issues: list[dict[str, Any]] = []

    def add_issue(issue: str, evidence: str, severity: str, action: str,
                  work_item_id: Any = None, state: str = "Sprint",
                  owner: str = "Team") -> None:
        issues.append({
            "work_item_id": work_item_id,
            "issue": issue,
            "state": state,
            "owner": owner,
            "observed": evidence,
            "evidence": evidence,
            "severity": severity,
            "recommendation": action,
            "action": action,
        })

    # Explicit blockers remain item-level issues.
    for item in items:
        if _state(item).casefold().strip() == "blocked":
            add_issue(
                "Work item is explicitly Blocked.",
                "Azure DevOps explicitly reports the item state as Blocked.",
                "HIGH",
                "Review and resolve the recorded blocker.",
                work_item_id=item.get("id"),
                state=_state(item),
                owner=item.get("assigned_to") or "Unassigned",
            )

    # Delivery pressure: one issue instead of one row per affected item.
    if items and completion_vs_time_gap is not None and completion_vs_time_gap >= 15:
        add_issue(
            "Sprint completion is materially behind elapsed sprint time.",
            f"Sprint is {sprint_elapsed_pct:.1f}% elapsed while completion is {completion_rate:.1f}% ({completion_vs_time_gap:.1f} percentage-point gap).",
            "HIGH" if completion_vs_time_gap >= 30 else "MEDIUM",
            "Review unfinished scope, priorities and remaining delivery capacity.",
        )

    if sprint_health and timing_available and new_count >= 3 and sprint_elapsed_pct >= 35:
        add_issue(
            f"{new_count} unfinished work item(s) remain in the New state.",
            f"{sprint_elapsed_pct:.1f}% of the sprint has elapsed while {new_count} items remain New.",
            "HIGH" if sprint_elapsed_pct >= 65 else "MEDIUM",
            "Confirm which New items are intended for this sprint and move ready work into active execution.",
        )

    if len(normalized_aging) >= 3:
        add_issue(
            f"{len(normalized_aging)} unfinished work item(s) meet the aging criteria.",
            "Deterministic age/time-in-state checks identified multiple items requiring review.",
            "HIGH" if any(str(x.get("risk")).upper() in {"HIGH", "CRITICAL"} for x in normalized_aging) else "MEDIUM",
            "Review the oldest and longest-running items for readiness, blockers and prioritization.",
        )

    if limited_progress_count >= 3:
        add_issue(
            f"{limited_progress_count} unfinished item(s) have no observed progress since sprint start.",
            "The latest available Azure DevOps activity/state timestamps do not show progress since the sprint start for these items.",
            "HIGH" if sprint_elapsed_pct >= 65 else "MEDIUM",
            "Review the affected items directly; absence of Azure activity is an attention signal, not proof that work is not happening.",
        )

    if normalized_deadlines:
        deadline_severity = "CRITICAL" if any(str(x.get("due_status")).upper() in {"OVERDUE", "DUE_TODAY"} for x in normalized_deadlines) else "HIGH"
        add_issue(
            f"{len(normalized_deadlines)} unfinished item(s) have deadline exposure.",
            "One or more target/due dates are overdue, due today, or approaching.",
            deadline_severity,
            "Review deadline-exposed items and confirm scope, ownership and delivery dates.",
        )

    concentrated = [x for x in workload if x.get("concentration") in {"HIGH", "ELEVATED"} and x.get("owner") != "Unassigned"]
    if concentrated:
        highest = max(concentrated, key=lambda x: x.get("active_work_pct", 0))
        add_issue(
            f"{highest.get('owner')} has concentrated active workload.",
            f"{highest.get('owner')} owns {highest.get('active_items', 0)} active item(s), representing {highest.get('active_work_pct', 0):.1f}% of active workload.",
            "HIGH" if highest.get("concentration") == "HIGH" else "MEDIUM",
            f"Review whether {highest.get('owner')}'s active workload should be rebalanced.",
            owner=highest.get("owner") or "Team",
        )

    issues.sort(key=lambda x: (
        {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(str(x.get("severity")).upper(), 9),
        str(x.get("work_item_id") or ""),
        str(x.get("issue") or ""),
    ))

    # -----------------------------------------------------------------------
    # RAID — Dependencies
    # -----------------------------------------------------------------------

    dependencies = []

    dependency_data_available = False

    for item in items:

        item_dependencies = _safe_list(
            item.get("dependencies")
        )

        relations = _safe_list(
            item.get("relations")
        )

        if (
            item_dependencies
            or relations
            or item.get("relations_retrieved")
        ):
            dependency_data_available = True

        for dependency in item_dependencies:

            if not isinstance(
                dependency,
                dict,
            ):
                continue

            dependencies.append(
                {
                    "work_item_id": item.get(
                        "id"
                    ),
                    "source": item.get(
                        "id"
                    ),
                    "relation": dependency.get(
                        "type"
                    ),
                    "target": dependency.get(
                        "work_item_id"
                    ),
                    "dependency_work_item_id": dependency.get(
                        "work_item_id"
                    ),
                    "status": dependency.get(
                        "status"
                    )
                    or "UNKNOWN",
                    "evidence": "Observed Azure DevOps work-item relationship.",
                }
            )

    # -----------------------------------------------------------------------
    # RAID — Assumptions / evidence gaps
    # -----------------------------------------------------------------------

    assumptions = []

    if not sprint_health:
        assumptions.append(
            "UNKNOWN: Sprint timeline and time-based health "
            "could not be determined from available Azure DevOps data."
        )
    else:
        if not timing_available:
            assumptions.append(
                "UNKNOWN: Sprint start/finish dates are unavailable; "
                "time-pressure calculations are not fully assessable."
            )

    if not dependency_data_available:
        assumptions.append(
            "UNKNOWN: Explicit dependency relationships were not "
            "available in the retrieved work-item data."
        )
    elif not dependencies:
        assumptions.append(
            "OBSERVED: Dependency relationship retrieval succeeded, "
            "but no explicit dependency relationships were observed."
        )

    # -----------------------------------------------------------------------
    # Key findings
    # -----------------------------------------------------------------------

    key_findings = []

    # 1. Overall sprint health
    if sprint_health:

        if health_status != "UNKNOWN":

            key_findings.append(
                {
                    "classification": health_status,
                    "evidence": (
                        f"Sprint health is {health_status}."
                        + (
                            f" Deterministic health score: {health_score}/100."
                            if health_score is not None
                            else ""
                        )
                    ),
                    "impact": (
                        "The health assessment reflects observed timing, "
                        "progress, deadline, aging, and workload signals."
                    ),
                    "recommendation": (
                        "Review the highest-severity work items and "
                        "time-based exceptions first."
                    ),
                }
            )

    # 2. Completion versus elapsed time
    if completion_vs_time_gap is not None:

        if completion_vs_time_gap >= 30:
            classification = "HIGH RISK"
        elif completion_vs_time_gap >= 15:
            classification = "AT RISK"
        elif completion_vs_time_gap >= 5:
            classification = "WATCH"
        else:
            classification = "NORMAL"

        key_findings.append(
            {
                "classification": classification,
                "evidence": (
                    f"Sprint is {sprint_elapsed_pct:.1f}% elapsed "
                    f"while completion is {completion_rate:.1f}%."
                ),
                "impact": (
                    f"Completion-versus-time gap is "
                    f"{completion_vs_time_gap:.1f} percentage points."
                ),
                "recommendation": (
                    "Review unfinished and aging work if delivery progress "
                    "is materially behind elapsed sprint time."
                ),
            }
        )

    # 3. Aging
    if normalized_aging:

        high_aging = [
            item
            for item in normalized_aging
            if item.get("risk")
            in {"CRITICAL", "HIGH"}
        ]

        key_findings.append(
            {
                "classification": (
                    "HIGH RISK"
                    if high_aging
                    else "AT RISK"
                ),
                "evidence": (
                    f"{len(normalized_aging)} unfinished item(s) "
                    "have aging/time-in-state signals requiring attention."
                ),
                "impact": (
                    "Long duration in a state can increase delivery "
                    "uncertainty when combined with sprint time pressure."
                ),
                "recommendation": (
                    "Review the oldest and longest-running items for "
                    "readiness, blockers, ownership, or prioritization."
                ),
            }
        )

    # 4. Deadline
    if normalized_deadlines:

        key_findings.append(
            {
                "classification": "HIGH RISK",
                "evidence": (
                    f"{len(normalized_deadlines)} unfinished item(s) "
                    "have overdue or approaching target/due dates."
                ),
                "impact": (
                    "Deadline exposure may affect delivery commitments."
                ),
                "recommendation": (
                    "Review overdue and due-soon items immediately."
                ),
            }
        )

    # 5. Workload
    concentrated = [
        owner
        for owner in workload
        if owner["concentration"]
        in {"HIGH", "ELEVATED"}
    ]

    if concentrated:

        highest = max(
            concentrated,
            key=lambda owner: owner["active_work_pct"],
        )

        key_findings.append(
            {
                "classification": (
                    "HIGH RISK"
                    if highest["concentration"] == "HIGH"
                    else "AT RISK"
                ),
                "evidence": (
                    f"{highest['owner']} owns "
                    f"{highest['active_items']} active items "
                    f"({highest['active_work_pct']:.1f}% of active workload); "
                    f"{highest['unfinished_items']} unfinished items "
                    f"({highest['board_share']:.1f}% of unfinished board scope)."
                ),
                "impact": (
                    "Workload concentration may constrain delivery "
                    "if multiple items require attention simultaneously."
                ),
                "recommendation": (
                    f"Review whether {highest['owner']}'s workload "
                    "should be rebalanced."
                ),
            }
        )

    # Keep the executive finding list concise.
    key_findings = key_findings[:5]

    # -----------------------------------------------------------------------
    # Board-level metrics
    # -----------------------------------------------------------------------

    total_items = len(items)

    board_metrics = {
        "total_items": total_items,
        "completed_items": len(completed_items),
        "unfinished_items": len(unfinished_items),
        "completion_rate": round(
            completion_rate,
            1,
        ),
        "active_items": len(active_items),
        "new_items": len(new_items),
        "unassigned_items": len(unassigned),

        "sprint_elapsed_pct": sprint_elapsed_pct,
        "completion_vs_time_gap_pct": completion_vs_time_gap,
        "observed_completion_pace_items_per_day": (
            round(observed_completion_pace, 2)
            if observed_completion_pace is not None
            else None
        ),
        "required_completion_pace_items_per_day": (
            round(required_completion_pace, 2)
            if required_completion_pace is not None
            else None
        ),
        "required_vs_observed_pace_ratio": (
            round(pace_ratio, 1) if pace_ratio is not None else None
        ),
        "potential_duplicate_title_groups": len(duplicate_title_groups),

        "aging_item_count": len(
            normalized_aging
        ),

        "deadline_risk_count": len(
            normalized_deadlines
        ),

        "limited_progress_count": sum(
            1
            for finding in sprint_findings
            if finding.get("progress_observed") is False
            and not _is_done(
                next(
                    (
                        item
                        for item in items
                        if item.get("id")
                        == finding.get("work_item_id")
                    ),
                    {},
                )
            )
        ),

        "no_observed_progress_count": sum(
            1
            for finding in sprint_findings
            if finding.get("progress_observed") is False
        ),

        "overloaded_owner_count": sum(
            1
            for owner in workload
            if owner.get("concentration")
            == "HIGH"
        ),
    }

    # -----------------------------------------------------------------------
    # Final result
    # -----------------------------------------------------------------------

    return {
        # Board overview
        "board": {
            "total_items": total_items,
            "completed_items": len(completed_items),
            "unfinished_items": len(unfinished_items),
            "completion_rate": round(
                completion_rate,
                1,
            ),
            "active_items": len(active_items),
            "new_items": len(new_items),
            "state_distribution": dict(
                sorted(states.items())
            ),
            "priority_distribution": dict(
                sorted(priorities.items())
            ),
            "unassigned_items": unassigned,
        },

        # Executive metrics
        "metrics": board_metrics,

        # Sprint
        "sprint_health": sprint_health,

        "health_status": health_status,
        "health_score": health_score,

        "timing": timing,
        "timing_available": timing_available,

        "completion_vs_time_gap_pct": (
            completion_vs_time_gap
        ),
        "delivery_pace": {
            "observed_items_per_day": (
                round(observed_completion_pace, 2)
                if observed_completion_pace is not None
                else None
            ),
            "required_items_per_day": (
                round(required_completion_pace, 2)
                if required_completion_pace is not None
                else None
            ),
            "required_vs_observed_ratio": (
                round(pace_ratio, 1) if pace_ratio is not None else None
            ),
        },
        "potential_duplicate_title_groups": duplicate_title_groups,

        # Workload
        "workload": workload,

        # Time-based analysis
        "aging_items": normalized_aging,
        "deadline_risks": normalized_deadlines,

        # RAID
        "raid": {
            "risks": risks,
            "assumptions": assumptions,
            "issues": issues,
            "dependencies": dependencies,
        },

        # Executive findings
        "key_findings": key_findings,

        "warnings": warnings,

        # Original evidence retained for audit traceability.
        "evidence_items": items,
    }