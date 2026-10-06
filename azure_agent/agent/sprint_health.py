"""Deterministic sprint-health calculations; this module does not call an LLM."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any, Optional


DONE_STATES = {"closed", "done", "resolved", "completed", "removed"}
NEW_STATES = {"new", "to do", "todo", "approved"}

# States that generally represent work which has started.
ACTIVE_STATES = {
    "active",
    "in progress",
    "doing",
    "committed",
    "development",
    "developing",
    "testing",
    "test",
}

RISK_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "HEALTHY": 4,
    "UNKNOWN": 5,
}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_date(value: Any) -> Optional[date]:
    """Parse common Azure DevOps date formats safely."""
    if not value:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()

    if not text:
        return None

    text = text.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _first_date(item: dict[str, Any], *keys: str) -> Optional[date]:
    """Return the first successfully parsed date from the supplied keys."""
    for key in keys:
        parsed = _parse_date(item.get(key))
        if parsed:
            return parsed
    return None


def _sprint_dates(
    sprint: dict[str, Any],
) -> tuple[Optional[date], Optional[date]]:
    """
    Extract sprint start/end dates.

    Azure DevOps can expose classification dates either directly or inside
    the sprint's attributes object.
    """
    attributes = sprint.get("attributes") or {}

    start = _first_date(
        sprint,
        "start",
        "startDate",
    )

    finish = _first_date(
        sprint,
        "end",
        "finish",
        "finishDate",
        "endDate",
    )

    if not start:
        start = _first_date(
            attributes,
            "start",
            "startDate",
        )

    if not finish:
        finish = _first_date(
            attributes,
            "end",
            "finish",
            "finishDate",
            "endDate",
        )

    return start, finish


# ---------------------------------------------------------------------------
# Sprint selection
# ---------------------------------------------------------------------------

def select_sprint(
    sprints: list[dict[str, Any]],
    today: date,
    sprint_name: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Choose a named sprint, otherwise the sprint containing today."""
    candidates = []

    for sprint in sprints:
        start, finish = _sprint_dates(sprint)

        if sprint_name:
            if sprint.get("name", "").casefold() == sprint_name.casefold():
                return sprint

        if not sprint_name and start and finish:
            if start <= today <= finish:
                candidates.append(sprint)

    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Sprint timing
# ---------------------------------------------------------------------------

def calculate_time_metrics(
    sprint_start: date,
    sprint_end: date,
    current_date: date,
) -> dict[str, Any]:
    """
    Return bounded inclusive sprint timing metrics.

    Example:
        Sprint: Oct 5 -> Oct 16
        Current: Oct 10

    total_days = 12
    elapsed_days = 6
    remaining_days = 6

    Percentages are calculated from the calendar interval while preventing
    negative or >100% elapsed values.
    """
    if sprint_end < sprint_start:
        return {
            "total_days": 0,
            "elapsed_days": 0,
            "remaining_days": 0,
            "elapsed_pct": 0.0,
            "remaining_pct": 0.0,
            "status": "INVALID_DATES",
        }

    total_days = max(1, (sprint_end - sprint_start).days + 1)

    if current_date < sprint_start:
        elapsed_days = 0
    else:
        elapsed_days = min(
            total_days,
            (current_date - sprint_start).days + 1,
        )

    if current_date > sprint_end:
        remaining_days = 0
    else:
        remaining_days = max(
            0,
            (sprint_end - current_date).days,
        )

    elapsed_pct = elapsed_days / total_days
    remaining_pct = remaining_days / total_days

    return {
        "total_days": total_days,
        "elapsed_days": elapsed_days,
        "remaining_days": remaining_days,
        "elapsed_pct": round(elapsed_pct, 4),
        "remaining_pct": round(remaining_pct, 4),
        "status": (
            "NOT_STARTED"
            if current_date < sprint_start
            else "IN_PROGRESS"
            if current_date <= sprint_end
            else "COMPLETED"
        ),
    }


# ---------------------------------------------------------------------------
# Work-item timing
# ---------------------------------------------------------------------------

def _calculate_item_timing(
    item: dict[str, Any],
    sprint_start: date,
    sprint_end: date,
    current_date: date,
) -> dict[str, Any]:
    """
    Calculate all available item-level time metrics.

    Important distinction:

    created_date
        -> age of the work item

    changed_date
        -> time since any Azure DevOps update

    state_change_date
        -> best available evidence for time in current state

    We never infer time-in-state from changed_date because an item can be
    updated without changing state.
    """
    created_date = _first_date(
        item,
        "created_date",
        "createdDate",
    )

    changed_date = _first_date(
        item,
        "changed_date",
        "changedDate",
    )

    state_changed_date = _first_date(
        item,
        "state_change_date",
        "stateChangedDate",
    )

    target_date = _first_date(
        item,
        "target_date",
        "targetDate",
        "due_date",
        "dueDate",
    )

    item_age_days: Optional[int] = None
    days_since_update: Optional[int] = None
    days_in_current_state: Optional[int] = None
    days_in_sprint: Optional[int] = None

    if created_date:
        item_age_days = max(
            0,
            (current_date - created_date).days,
        )

        # Number of calendar days the item has existed while overlapping
        # the current sprint.
        sprint_item_start = max(created_date, sprint_start)

        if sprint_item_start <= current_date:
            days_in_sprint = (
                min(current_date, sprint_end) - sprint_item_start
            ).days + 1

            days_in_sprint = max(0, days_in_sprint)

    if changed_date:
        days_since_update = max(
            0,
            (current_date - changed_date).days,
        )

    if state_changed_date:
        days_in_current_state = max(
            0,
            (current_date - state_changed_date).days,
        )

    # State-change timestamp is the only reliable basis for time-in-state.
    if state_changed_date:
        state_age_basis = "OBSERVED_STATE_CHANGE"
    else:
        state_age_basis = "UNKNOWN"

    due_status = "UNKNOWN"

    if target_date:
        if target_date < current_date:
            due_status = "OVERDUE"
        elif target_date <= current_date:
            due_status = "DUE_TODAY"
        elif (target_date - current_date).days <= 2:
            due_status = "DUE_SOON"
        else:
            due_status = "ON_TRACK"

    return {
        "created_date": created_date.isoformat() if created_date else None,
        "changed_date": changed_date.isoformat() if changed_date else None,
        "state_change_date": (
            state_changed_date.isoformat()
            if state_changed_date
            else None
        ),
        "target_date": target_date.isoformat() if target_date else None,
        "item_age_days": item_age_days,
        "days_since_update": days_since_update,
        "days_in_current_state": days_in_current_state,
        "days_in_sprint": days_in_sprint,
        "state_age_basis": state_age_basis,
        "due_status": due_status,
    }


# ---------------------------------------------------------------------------
# Risk calculations
# ---------------------------------------------------------------------------

def _risk(
    state: str,
    is_done: bool,
    elapsed_pct: float,
    remaining_days: int,
    progress_observed: bool,
    overloaded: bool,
    item_age_days: Optional[int] = None,
    days_in_current_state: Optional[int] = None,
    days_since_update: Optional[int] = None,
    due_status: str = "UNKNOWN",
) -> tuple[str, str]:
    """
    Classify work-item time risk using deterministic evidence.

    Risk is deliberately conservative.

    We do NOT say:
        "developer is not working"

    We say:
        "no observable Azure DevOps activity/state progression"

    Time-in-state is only used when Azure provides a state-change timestamp.
    """
    state_key = state.casefold().strip()

    if is_done:
        return "HEALTHY", "Item is in a completed state."

    # ---------------------------------------------------------------
    # Deadline risk has the highest priority.
    # ---------------------------------------------------------------

    if due_status == "OVERDUE":
        return (
            "CRITICAL",
            "The item's target/due date has passed while the item remains unfinished.",
        )

    if due_status == "DUE_TODAY":
        return (
            "CRITICAL",
            "The item's target/due date is today while the item remains unfinished.",
        )

    if remaining_days <= 1:
        return (
            "CRITICAL",
            "Sprint deadline is within one day and the item is not completed.",
        )

    if due_status == "DUE_SOON":
        return (
            "HIGH",
            "The item's target/due date is approaching within two days while the item remains unfinished.",
        )

    # ---------------------------------------------------------------
    # Long time in the same state.
    #
    # Only apply this when state_change_date exists.
    # ---------------------------------------------------------------

    if days_in_current_state is not None:

        if state_key in NEW_STATES and days_in_current_state >= 14:
            reason = (
                f"Item has remained in {state} for "
                f"{days_in_current_state} days."
            )

            if elapsed_pct >= 0.65:
                reason += (
                    " At least 65% of the sprint has elapsed."
                )

            return "HIGH", reason

        if days_in_current_state >= 14 and elapsed_pct >= 0.65:
            return (
                "HIGH",
                f"Item has remained in {state} for "
                f"{days_in_current_state} days while at least "
                f"65% of the sprint has elapsed.",
            )

        if days_in_current_state >= 7 and elapsed_pct >= 0.65:
            return (
                "MEDIUM",
                f"Item has remained in {state} for "
                f"{days_in_current_state} days while the sprint is "
                f"substantially progressed.",
            )

        if state_key in NEW_STATES and days_in_current_state >= 7:
            return (
                "MEDIUM",
                f"Item has remained in {state} for "
                f"{days_in_current_state} days.",
            )

    # ---------------------------------------------------------------
    # Age-based risk.
    #
    # Age alone does not prove an item is stuck. It becomes meaningful
    # when combined with sprint progress / lack of observable activity.
    # ---------------------------------------------------------------

    if (
        item_age_days is not None
        and item_age_days >= 30
        and elapsed_pct >= 0.65
        and progress_observed is False
    ):
        return (
            "HIGH",
            f"Item is {item_age_days} days old and has no observable "
            "activity or state progression while the sprint is substantially progressed.",
        )

    if (
        item_age_days is not None
        and item_age_days >= 14
        and elapsed_pct >= 0.65
        and progress_observed is False
    ):
        return (
            "MEDIUM",
            f"Item is {item_age_days} days old with no observable "
            "activity or state progression while the sprint is substantially progressed.",
        )

    # ---------------------------------------------------------------
    # Existing sprint-progress rules.
    # ---------------------------------------------------------------

    if state_key in NEW_STATES and elapsed_pct >= 0.65:
        return (
            "HIGH",
            "At least 65% of the sprint has elapsed while the item remains New.",
        )

    if progress_observed is False and elapsed_pct >= 0.65:
        reason = (
            "At least 65% of the sprint has elapsed without observable "
            "activity or state progression."
        )

        if overloaded:
            reason += (
                " The owner also has a concentrated active workload."
            )

        return "HIGH", reason

    if state_key in NEW_STATES and elapsed_pct >= 0.35:
        return (
            "MEDIUM",
            "At least 35% of the sprint has elapsed while the item remains New.",
        )

    if progress_observed is False and elapsed_pct >= 0.35:
        return (
            "MEDIUM",
            "A material portion of the sprint has elapsed without observable "
            "activity or state progression.",
        )

    # ---------------------------------------------------------------
    # Inactivity warning.
    # ---------------------------------------------------------------

    if (
        days_since_update is not None
        and days_since_update >= 14
        and elapsed_pct >= 0.35
    ):
        return (
            "MEDIUM",
            f"No Azure DevOps item update has been observed for "
            f"{days_since_update} days.",
        )

    return (
        "LOW",
        "No deterministic time-and-progress risk threshold was met.",
    )


# ---------------------------------------------------------------------------
# Item progress classification
# ---------------------------------------------------------------------------

def _progress_evidence(
    item: dict[str, Any],
    sprint_start: date,
    state: str,
    is_done: bool,
) -> dict[str, Any]:
    """
    Separate state progression from generic item updates.

    changed_date:
        evidence of an item update/activity

    state_change_date:
        evidence of state progression

    This distinction prevents us from calling an updated item "progressed"
    when its state may not have changed.
    """
    changed = _parse_date(item.get("changed_date"))
    state_changed = _parse_date(item.get("state_change_date"))

    item_updated_in_sprint = bool(
        changed and changed >= sprint_start
    )

    state_progressed_in_sprint = bool(
        state_changed and state_changed >= sprint_start
    )

    if is_done:
        progress_observed = True
        progress_basis = "COMPLETED_STATE"
    elif state_progressed_in_sprint:
        progress_observed = True
        progress_basis = "STATE_PROGRESSION"
    elif item_updated_in_sprint:
        progress_observed = True
        progress_basis = "ITEM_UPDATED"
    elif changed is None and state_changed is None:
        # Absence of timestamps is not evidence of inactivity.
        progress_observed = None
        progress_basis = "UNKNOWN_ACTIVITY"
    else:
        progress_observed = False
        progress_basis = "NO_OBSERVED_ACTIVITY_SINCE_SPRINT_START"

    return {
        "item_updated_in_sprint": item_updated_in_sprint,
        "state_progressed_in_sprint": state_progressed_in_sprint,
        "progress_observed": progress_observed,
        "progress_basis": progress_basis,
        "changed_date": changed.isoformat() if changed else None,
        "state_change_date": (
            state_changed.isoformat()
            if state_changed
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def build_sprint_health_report(
    sprint: dict[str, Any],
    items: list[dict[str, Any]],
    current_date: date,
) -> dict[str, Any]:
    """
    Build a JSON-safe deterministic sprint-health report.

    The report intentionally does not call an LLM.

    Important concepts:

    1. Item age
       How long the work item has existed.

    2. Time in current state
       How long the item has remained in its current state, but ONLY when
       Azure provides state_change_date.

    3. Time since update
       How long since any observable Azure DevOps item update.

    4. Sprint elapsed time
       How much of the sprint has passed.

    5. Deadline exposure
       Target/due date proximity.

    6. Progress evidence
       State progression and generic updates are tracked separately.

    Missing timestamps are reported as UNKNOWN rather than fabricated.
    """

    start, finish = _sprint_dates(sprint)

    # ---------------------------------------------------------------
    # Missing sprint dates should not crash the audit.
    # ---------------------------------------------------------------

    if not start or not finish:
        return {
            "sprint": {
                "name": sprint.get("name"),
                "start": start.isoformat() if start else None,
                "end": finish.isoformat() if finish else None,
            },
            "generated_date": current_date.isoformat(),
            "timing_available": False,
            "timing": {
                "total_days": None,
                "elapsed_days": None,
                "remaining_days": None,
                "elapsed_pct": None,
                "remaining_pct": None,
                "status": "UNKNOWN",
            },
            "overall_status": "UNKNOWN",
            "overall_health": "UNKNOWN",
            "health_status": "UNKNOWN",
            "health_score": None,
            "findings": [],
            "aging_items": [],
            "deadline_risks": [],
            "workload": [],
            "summary": {
                "work_item_count": len(items),
                "unfinished_item_count": sum(
                    str(item.get("state") or "").casefold()
                    not in DONE_STATES
                    for item in items
                ),
                "at_risk_count": 0,
                "no_observed_progress_count": 0,
                "completed_count": sum(
                    str(item.get("state") or "").casefold()
                    in DONE_STATES
                    for item in items
                ),
                "completion_rate": (
                    round(
                        (
                            sum(
                                str(item.get("state") or "").casefold()
                                in DONE_STATES
                                for item in items
                            )
                            / len(items)
                        )
                        * 100,
                        1,
                    )
                    if items
                    else 0.0
                ),
                "new_count": 0,
                "active_count": 0,
                "unassigned_count": 0,
                "deadline_risk_count": 0,
                "overloaded_owner_count": 0,
                "progress_gap_pct": None,
            },
            "warnings": [
                "Sprint start/finish dates are unavailable; time-based health cannot be fully assessed."
            ],
        }

    timing = calculate_time_metrics(
        start,
        finish,
        current_date,
    )

    elapsed_pct = timing["elapsed_pct"]
    remaining_days = timing["remaining_days"]

    # ---------------------------------------------------------------
    # Active / unfinished work
    # ---------------------------------------------------------------

    unfinished_items = [
        item
        for item in items
        if str(item.get("state") or "").casefold()
        not in DONE_STATES
    ]

    completed_items = [
        item
        for item in items
        if str(item.get("state") or "").casefold()
        in DONE_STATES
    ]

    unfinished_total = len(unfinished_items)

    # ---------------------------------------------------------------
    # Workload
    # ---------------------------------------------------------------

    unfinished_owner_counts = Counter(
        item.get("assigned_to") or "Unassigned"
        for item in unfinished_items
    )
    active_owner_counts = Counter(
        item.get("assigned_to") or "Unassigned"
        for item in unfinished_items
        if str(item.get("state") or "").casefold().strip() in ACTIVE_STATES
    )
    active_state_total = sum(active_owner_counts.values())

    workload = []
    overloaded_owners = set()

    for owner, count in sorted(
        unfinished_owner_counts.items(),
        key=lambda pair: (-pair[1], pair[0]),
    ):
        active_count = active_owner_counts.get(owner, 0)
        board_share = (count / unfinished_total) if unfinished_total else 0
        active_share = (active_count / active_state_total) if active_state_total else 0

        # Relative concentration is based on actual active states, not New work.
        concentration_share = active_share if active_state_total else board_share
        #
        # Avoid blindly calling someone overloaded simply because they
        # have >=4 items. Concentration matters relative to the board.
        assessment = "NORMAL"

        if active_count >= 4 and concentration_share >= 0.50:
            assessment = "HIGH"
        elif active_count >= 3 and concentration_share >= 0.35:
            assessment = "ELEVATED"
        elif active_count >= 2 and concentration_share >= 0.25:
            assessment = "WATCH"

        if assessment == "HIGH" and owner != "Unassigned":
            overloaded_owners.add(owner)

        workload.append(
            {
                "owner": owner,
                "active_items": active_count,
                "unfinished_items": count,
                "active_work_pct": round(active_share * 100, 1),
                "board_share": round(board_share * 100, 1),
                "assessment": assessment,
            }
        )

    # ---------------------------------------------------------------
    # Findings
    # ---------------------------------------------------------------

    findings = []
    aging_items = []
    deadline_risks = []

    for item in items:

        item_id = item.get("id")
        title = item.get("title")
        state = str(item.get("state") or "Unknown")
        owner = item.get("assigned_to") or "Unassigned"

        state_key = state.casefold().strip()
        is_done = state_key in DONE_STATES

        # -----------------------------------------------------------
        # Timing
        # -----------------------------------------------------------

        item_timing = _calculate_item_timing(
            item,
            start,
            finish,
            current_date,
        )

        item_age_days = item_timing["item_age_days"]
        days_since_update = item_timing["days_since_update"]
        days_in_current_state = item_timing["days_in_current_state"]

        # -----------------------------------------------------------
        # Progress evidence
        # -----------------------------------------------------------

        progress = _progress_evidence(
            item,
            start,
            state,
            is_done,
        )

        progress_observed = progress["progress_observed"]

        # -----------------------------------------------------------
        # Risk
        # -----------------------------------------------------------

        risk, reason = _risk(
            state=state,
            is_done=is_done,
            elapsed_pct=elapsed_pct,
            remaining_days=remaining_days,
            progress_observed=progress_observed,
            overloaded=owner in overloaded_owners,
            item_age_days=item_age_days,
            days_in_current_state=days_in_current_state,
            days_since_update=days_since_update,
            due_status=item_timing["due_status"],
        )

        # -----------------------------------------------------------
        # Evidence
        # -----------------------------------------------------------

        observed = []

        if is_done:
            observed.append(
                f"State is {state}."
            )
        else:
            observed.append(
                f"State is {state}."
            )

        if item_age_days is not None:
            observed.append(f"Item age: {item_age_days} days.")
        if days_in_current_state is not None:
            observed.append(f"Time in current state: {days_in_current_state} days.")
        if days_since_update is not None:
            observed.append(f"Days since last item update: {days_since_update} days.")

        if progress["state_progressed_in_sprint"]:
            observed.append("A state progression was observed during the sprint.")
        elif progress["state_progressed_in_sprint"] is False and progress["state_change_date"]:
            observed.append("The latest state change predates the current sprint.")

        if progress["item_updated_in_sprint"]:
            observed.append("An item update was observed during the sprint.")
        elif progress["item_updated_in_sprint"] is False and progress["changed_date"]:
            observed.append("The latest item update predates the current sprint.")

        # -----------------------------------------------------------
        # Inference
        # -----------------------------------------------------------

        inferred = None

        if not is_done:

            if (
                risk in {"HIGH", "CRITICAL"}
                and days_in_current_state is not None
            ):
                inferred = (
                    "The observed duration in the current state, combined "
                    "with sprint timing, indicates the item may require "
                    "delivery review. Azure data does not establish why "
                    "the item remains in this state."
                )

            elif risk in {"HIGH", "CRITICAL"}:
                inferred = (
                    "The available timing and progress signals indicate "
                    "the item may require review. Azure data does not "
                    "establish whether the owner is actively working."
                )

            elif (
                days_since_update is not None
                and days_since_update >= 14
            ):
                inferred = (
                    "The item has not been updated recently in Azure DevOps; "
                    "this is an activity signal, not proof that work has stopped."
                )

        # -----------------------------------------------------------
        # Classification flags
        # -----------------------------------------------------------

        aging_signal = False

        if (
            not is_done
            and days_in_current_state is not None
            and days_in_current_state >= 7
        ):
            aging_signal = True

        elif (
            not is_done
            and item_age_days is not None
            and item_age_days >= 14
            and progress_observed is False
        ):
            aging_signal = True

        if aging_signal:
            aging_items.append(
                {
                    "work_item_id": item_id,
                    "title": title,
                    "state": state,
                    "owner": owner,
                    "item_age_days": item_age_days,
                    "days_in_current_state": days_in_current_state,
                    "days_since_update": days_since_update,
                    "risk": risk,
                    "reason": reason,
                }
            )

        if (
            not str(state).casefold().strip() in DONE_STATES
            and item_timing["due_status"] in {
                "OVERDUE",
                "DUE_TODAY",
                "DUE_SOON",
            }
        ):
            deadline_risks.append(
                {
                    "work_item_id": item_id,
                    "title": title,
                    "state": state,
                    "owner": owner,
                    "target_date": item_timing["target_date"],
                    "due_status": item_timing["due_status"],
                    "risk": risk,
                    "reason": reason,
                }
            )

        findings.append(
            {
                "work_item_id": item_id,
                "title": title,
                "owner": owner,
                "state": state,

                # Sprint-level timing
                "days_in_sprint": timing["elapsed_days"],
                "days_remaining": remaining_days,

                # Item-level timing
                "item_age_days": item_age_days,
                "days_since_update": days_since_update,
                "days_in_current_state": days_in_current_state,

                # Date evidence
                "created_date": item_timing["created_date"],
                "changed_date": item_timing["changed_date"],
                "state_change_date": item_timing["state_change_date"],
                "target_date": item_timing["target_date"],
                "due_status": item_timing["due_status"],
                "state_age_basis": item_timing["state_age_basis"],

                # Progress evidence
                "item_updated_in_sprint": progress[
                    "item_updated_in_sprint"
                ],
                "state_progressed_in_sprint": progress[
                    "state_progressed_in_sprint"
                ],
                "progress_observed": progress_observed,
                "progress_basis": progress["progress_basis"],

                "progress": (
                    "Observed activity/progression"
                    if progress_observed is True
                    else "No observed activity/progression"
                    if progress_observed is False
                    else "UNKNOWN — activity/progression timestamps unavailable"
                ),

                # Risk
                "risk": risk,
                "reason": reason,

                # Evidence
                "observed": observed,
                "inferred": inferred,
                "aging_signal": aging_signal,
            }
        )

    # ---------------------------------------------------------------
    # Sort findings
    # ---------------------------------------------------------------

    findings.sort(
        key=lambda finding: (
            RISK_ORDER.get(
                finding["risk"],
                99,
            ),
            -(
                finding["days_in_current_state"]
                if finding["days_in_current_state"] is not None
                else -1
            ),
            -(
                finding["item_age_days"]
                if finding["item_age_days"] is not None
                else -1
            ),
            str(finding["work_item_id"]),
        )
    )

    aging_items.sort(
        key=lambda item: (
            RISK_ORDER.get(item["risk"], 99),
            -(
                item["days_in_current_state"]
                if item["days_in_current_state"] is not None
                else -1
            ),
            -(
                item["item_age_days"]
                if item["item_age_days"] is not None
                else -1
            ),
        )
    )

    deadline_risks.sort(
        key=lambda item: (
            RISK_ORDER.get(item["risk"], 99),
            str(item["target_date"] or ""),
        )
    )

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------

    completed_count = len(completed_items)

    new_count = sum(
        str(item.get("state") or "").casefold()
        in NEW_STATES
        for item in unfinished_items
    )

    active_count = sum(
        str(item.get("state") or "").casefold()
        in ACTIVE_STATES
        for item in unfinished_items
    )

    unassigned_count = sum(
        not item.get("assigned_to")
        for item in unfinished_items
    )

    at_risk = [
        finding
        for finding in findings
        if finding["risk"]
        in {"CRITICAL", "HIGH", "MEDIUM"}
    ]

    no_observed_progress = [
        finding
        for finding in findings
        if finding["progress_observed"] is False
        and not str(finding["state"]).casefold() in DONE_STATES
    ]

    completion_rate = (
        completed_count / len(items) * 100
        if items
        else 0.0
    )

    progress_gap_pct = round(
        elapsed_pct * 100 - completion_rate,
        1,
    )

    # ---------------------------------------------------------------
    # Overall health
    # ---------------------------------------------------------------

    critical_count = sum(
        finding["risk"] == "CRITICAL"
        for finding in findings
    )

    high_count = sum(
        finding["risk"] == "HIGH"
        for finding in findings
    )

    if critical_count > 0:
        overall = "CRITICAL"
    elif high_count > 0:
        overall = "AT RISK"
    elif at_risk:
        overall = "WATCH"
    else:
        overall = "HEALTHY"

    # ---------------------------------------------------------------
    # Deterministic health score
    #
    # This is a risk signal, not a prediction.
    # ---------------------------------------------------------------

    health_score = 0

    # Progress gap
    if progress_gap_pct >= 50:
        health_score += 30
    elif progress_gap_pct >= 30:
        health_score += 20
    elif progress_gap_pct >= 15:
        health_score += 10

    # High / critical findings
    health_score += min(
        25,
        critical_count * 10 + high_count * 5,
    )

    # No observable progress
    if findings:
        no_progress_pct = (
            len(no_observed_progress)
            / len(findings)
            * 100
        )

        if no_progress_pct >= 50:
            health_score += 20
        elif no_progress_pct >= 25:
            health_score += 10

    # Deadline exposure
    health_score += min(
        15,
        len(deadline_risks) * 5,
    )

    # Workload concentration
    if workload:
        concentrated_workload = [
            owner["active_work_pct"]
            for owner in workload
            if owner.get("owner") != "Unassigned"
            and owner.get("assessment") in {"HIGH", "ELEVATED"}
        ]
        if concentrated_workload:
            max_share = max(concentrated_workload)
            health_score += 10 if max_share >= 50 else 5

    health_score = min(
        100,
        max(0, health_score),
    )

    if health_score <= 20:
        score_status = "HEALTHY"
    elif health_score <= 40:
        score_status = "WATCH"
    elif health_score <= 60:
        score_status = "AT RISK"
    elif health_score <= 80:
        score_status = "HIGH RISK"
    else:
        score_status = "CRITICAL"

    # Don't allow the numeric score to contradict a directly observed
    # critical condition.
    if overall == "CRITICAL":
        score_status = "CRITICAL"

    # ---------------------------------------------------------------
    # Operational warnings
    # ---------------------------------------------------------------
    # Missing optional item timestamps are handled per item and are deliberately
    # not promoted into a noisy board-level "data quality" section.
    warnings: list[str] = []

    # ---------------------------------------------------------------
    # Final report
    # ---------------------------------------------------------------

    return {
        "sprint": {
            "name": sprint.get("name"),
            "start": start.isoformat(),
            "end": finish.isoformat(),
        },

        "generated_date": current_date.isoformat(),

        "timing_available": True,

        "timing": timing,

        "overall_status": overall,
        "overall_health": overall,
        "health_status": overall,

        "health_score": health_score,
        "health_score_status": score_status,

        "findings": findings,

        "aging_items": aging_items,

        "deadline_risks": deadline_risks,

        "workload": workload,

        "summary": {
            "work_item_count": len(items),
            "unfinished_item_count": unfinished_total,
            "at_risk_count": len(at_risk),
            "no_observed_progress_count": len(
                no_observed_progress
            ),
            "completed_count": completed_count,
            "completion_rate": round(
                completion_rate,
                1,
            ),
            "new_count": new_count,
            "active_count": active_count,
            "unassigned_count": unassigned_count,
            "deadline_risk_count": len(
                deadline_risks
            ),
            "overloaded_owner_count": len(
                overloaded_owners
            ),
            "progress_gap_pct": progress_gap_pct,

            # Useful manager-facing metrics
            "aging_item_count": len(
                aging_items
            ),
            "items_with_state_duration": sum(
                finding["days_in_current_state"]
                is not None
                for finding in findings
            ),
            "items_without_state_duration": sum(
                finding["days_in_current_state"]
                is None
                for finding in findings
            ),
        },

        "warnings": warnings,
    }