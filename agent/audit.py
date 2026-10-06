import secrets
import json
from datetime import datetime, timezone
from typing import Any


def get_next_operation_id(operation_type: str) -> str:
    """Generate a durable, collision-resistant audit identifier.

    Vercel Functions are stateless and their local filesystem is not a durable
    counter store, so sequential file-backed IDs are unsafe in production.
    The timestamp plus random suffix remains traceable while avoiding
    collisions across concurrent serverless invocations.
    """
    operation = _clean_text(operation_type).upper() or "AUDIT"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(3).upper()
    return f"{operation}-{timestamp}-{suffix}"

def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        values = [_clean_text(item) for item in value]
        return ", ".join(item for item in values if item)
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value).strip()

def _escape_table(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return "—"
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")

def _format_tools(value: Any) -> str:
    if isinstance(value, str):
        tools = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        tools = [_clean_text(item) for item in value if _clean_text(item)]
    else:
        text = _clean_text(value)
        return _escape_table(text) if text else "—"
    return ", ".join(f"`{tool}`" for tool in tools) if tools else "—"

def _status_badge(status: Any) -> str:
    normalized = _clean_text(status).lower()
    groups = {
        "✅ Completed": {"completed", "complete", "success", "successful", "succeeded"},
        "❌ Failed": {"failed", "failure", "error"},
        "🟠 Partially Completed": {"partial", "partially completed", "partially_complete", "partial success"},
        "🔄 In Progress": {"in progress", "running", "processing"},
        "⏳ Pending": {"pending", "waiting"},
        "⚪ Cancelled": {"cancelled", "canceled"},
    }
    for badge, values in groups.items():
        if normalized in values:
            return badge
    return "⚪ Unknown" if not normalized else _clean_text(status)

def _health_icon(status: Any) -> str:
    normalized = _clean_text(status).upper()
    icons = {
        "🟢": {"HEALTHY", "NORMAL"},
        "🟡": {"WATCH", "MODERATE"},
        "🟠": {"AT RISK", "ELEVATED"},
        "🔴": {"HIGH RISK", "CRITICAL"},
    }
    return next((icon for icon, values in icons.items() if normalized in values), "⚪")

def _risk_icon(risk: Any) -> str:
    normalized = _clean_text(risk).upper()
    icons = {
        "🔴": {"CRITICAL", "HIGH", "HIGH RISK"},
        "🟠": {"AT RISK", "MEDIUM", "ELEVATED"},
        "🟡": {"WATCH", "LOW", "MODERATE"},
        "🟢": {"HEALTHY", "NORMAL"},
    }
    return next((icon for icon, values in icons.items() if normalized in values), "⚪")

def _safe_percentage(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0 or number > 100:
        if 0 <= number <= 1:
            return number * 100.0
        return default
    if 0 <= number <= 1:
        return number * 100.0
    return number

def _format_percent(value: Any, default: float | None = None) -> str:
    percentage = _safe_percentage(value, default)
    if percentage is None:
        return "Unknown"
    return f"{percentage:.1f}%"

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _display_owner(value: Any) -> str:
    return _clean_text(value) or "Unassigned"

def _truncate(value: Any, length: int = 80) -> str:
    text = _clean_text(value)
    if not text:
        return "—"
    if len(text) <= length:
        return text
    return text[:max(1, length - 3)].rstrip() + "..."

def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not headers:
        return ""
    output = [
        "| " + " | ".join(_escape_table(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        normalized = list(row[:len(headers)])
        while len(normalized) < len(headers):
            normalized.append("—")
        output.append("| " + " | ".join(_escape_table(value) for value in normalized) + " |")
    return "\n".join(output)

def _bullet_list(items: list[Any]) -> str:
    cleaned = [_clean_text(item) for item in items if _clean_text(item)]
    if not cleaned:
        return "_None identified._"
    return "\n".join(f"- {item}" for item in cleaned)

def _generated_timestamp() -> str:
    return datetime.now().strftime("%d %B %Y, %H:%M")

def _get_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}

def _get_list(value: Any) -> list:
    return value if isinstance(value, list) else []

def _get_health_data(review: dict) -> tuple[dict | None, str, float]:
    health = review.get("sprint_health")
    if not isinstance(health, dict):
        status = _clean_text(review.get("health_status") or "UNKNOWN").upper()
        score = _safe_float(review.get("health_score"), 0.0)
        return None, status, score
    status = _clean_text(review.get("health_status") or health.get("health_status") or "UNKNOWN").upper()
    score = _safe_float(review.get("health_score") if review.get("health_score") is not None else health.get("health_score"), 0.0)
    return health, status, score

def _get_findings(health: dict | None) -> list[dict]:
    if not isinstance(health, dict):
        return []
    return [finding for finding in _get_list(health.get("findings")) if isinstance(finding, dict)]

def _get_workload(review: dict) -> list[dict]:
    return [item for item in _get_list(review.get("workload")) if isinstance(item, dict)]

def _get_aging_items(review: dict) -> list[dict]:
    return [item for item in _get_list(review.get("aging_items")) if isinstance(item, dict)]

def _get_deadline_risks(review: dict) -> list[dict]:
    return [item for item in _get_list(review.get("deadline_risks")) if isinstance(item, dict)]

def _get_raid(review: dict) -> dict:
    raid = review.get("raid")
    if not isinstance(raid, dict):
        return {"risks": [], "assumptions": [], "issues": [], "dependencies": []}
    return {
        "risks": _get_list(raid.get("risks")),
        "assumptions": _get_list(raid.get("assumptions")),
        "issues": _get_list(raid.get("issues")),
        "dependencies": _get_list(raid.get("dependencies")),
    }

def _format_sprint_dates(sprint: dict) -> tuple[str, str]:
    if not isinstance(sprint, dict):
        return "Unknown", "Unknown"
    start = sprint.get("start") or sprint.get("startDate") or sprint.get("start_date")
    finish = sprint.get("end") or sprint.get("finish") or sprint.get("finishDate") or sprint.get("finish_date") or sprint.get("endDate") or sprint.get("end_date")
    return _clean_text(start) or "Unknown", _clean_text(finish) or "Unknown"

def _format_date(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return "Unknown"
    if "T" in text:
        return text.split("T", 1)[0]
    return text[:10]


def _score_band(score: Any) -> str:
    value = _safe_float(score, 0.0)
    if value <= 20:
        return "HEALTHY"
    if value <= 40:
        return "WATCH"
    if value <= 60:
        return "AT RISK"
    if value <= 80:
        return "HIGH RISK"
    return "CRITICAL"


def _deadline_status(status: Any) -> str:
    normalized = _clean_text(status).upper()
    if normalized == "OVERDUE":
        return "🔴 OVERDUE"
    if normalized in {"DUE_SOON", "DUE SOON"}:
        return "🟠 DUE SOON"
    if normalized in {"DUE_TODAY", "DUE TODAY"}:
        return "🔴 DUE TODAY"
    if normalized == "ON_TRACK":
        return "🟢 ON TRACK"
    return "⚪ UNKNOWN"

def _attention_status(item: dict) -> str:
    risk = _clean_text(item.get("risk")).upper()
    if risk in {"CRITICAL", "HIGH", "HIGH RISK"}:
        return "🔴 HIGH RISK"
    if risk in {"AT RISK", "ELEVATED", "MEDIUM"}:
        return "🟠 AT RISK"
    if risk in {"WATCH", "MODERATE", "LOW"}:
        return "🟡 WATCH"
    if risk in {"HEALTHY", "NORMAL"}:
        return "🟢 NORMAL"
    return "⚪ UNKNOWN"

def _build_generic_report(operation_id: str, operation: str, status: str, summary: str, details: dict) -> str:
    details = details or {}
    project = details.get("Project", "Unknown")
    generated = _generated_timestamp()
    excluded = {"Project", "Tools Executed", "User Request"}
    rows = [[f"**{_clean_text(key)}**", value] for key, value in details.items() if key not in excluded]
    report = f"""# 🤖 Azure DevOps Audit Report

> 🔍 **Automated engineering activity report**
>
> Final execution outcome recorded by the Azure DevOps AI Agent.

---

## 📋 Audit Information

{_markdown_table(
    ["Field", "Details"],
    [
        ["Audit ID", f"`{operation_id}`"],
        ["Operation", operation],
        ["Project", project],
        ["Status", _status_badge(status)],
        ["Generated", generated],
    ],
)}

---

## 📝 Executive Summary

{summary or "_No summary was recorded._"}
"""
    user_request = details.get("User Request", "")
    if user_request:
        report += f"""

---

## 💬 User Request

> {_clean_text(user_request)}
"""
    report += f"""

---

## 🔧 Execution

**Tools executed:** {_format_tools(details.get("Tools Executed", ""))}
"""
    if rows:
        report += f"""

---

## 📊 Details

{_markdown_table(
    ["Field", "Value"],
    rows,
)}
"""
    report += f"""

---

## 🔐 Audit Trail

{_markdown_table(
    ["Field", "Value"],
    [
        ["Audit ID", f"`{operation_id}`"],
        ["Operation", operation],
        ["Status", _status_badge(status)],
        ["Agent", "Azure DevOps AI Agent"],
    ],
)}

---

> 🔒 _This report contains the final operation outcome and excludes internal reasoning and intermediate model execution._
"""
    return report

def _build_board_report(operation_id: str, operation: str, status: str, summary: str, details: dict) -> str:
    details = details or {}
    project = details.get("Project", "Unknown")
    generated = _generated_timestamp()
    return f"""# 📊 Azure DevOps Board Review

> 📌 **Project board assessment**
>
> Current board, backlog, work-item and delivery information recorded by the AI Agent.

---

## 📋 Audit Information

{_markdown_table(
    ["Field", "Details"],
    [
        ["Audit ID", f"`{operation_id}`"],
        ["Operation", "Board Review"],
        ["Project", project],
        ["Status", _status_badge(status)],
        ["Generated", generated],
    ],
)}

---

## 📝 Executive Summary

{summary or "_No executive summary was recorded._"}

---

## 🔧 Execution Details

{_markdown_table(
    ["Field", "Details"],
    [
        [
            "Tools Executed",
            _format_tools(details.get("Tools Executed", "")),
        ],
        [
            "Analysis Type",
            "Board + Sprint + Progress + Workload + Dates + RAID",
        ],
    ],
)}

---

## 🔐 Audit Trail

{_markdown_table(
    ["Field", "Value"],
    [
        ["Audit ID", f"`{operation_id}`"],
        ["Operation", "Board Review"],
        ["Status", _status_badge(status)],
        ["Agent", "Azure DevOps AI Agent"],
    ],
)}

---

> 🤖 _Generated automatically by the Azure DevOps AI Agent._
"""

def _build_comprehensive_board_report(operation_id: str, details: dict) -> str:
    """Render a compact, manager-friendly deterministic Board Review.

    The renderer intentionally separates executive interpretation from detailed
    evidence.  It avoids wide tables for narrative findings and avoids
    repeating the same issue in Current Issues, RAID, Key Findings and Actions.
    """
    details = details or {}
    review = details.get("Board Review")
    if not isinstance(review, dict):
        return _build_generic_report(
            operation_id, "Board Review", "Failed",
            "Structured Board Review data was not available.", details
        )

    board = _get_dict(review.get("board"))
    health, health_status, health_score = _get_health_data(review)
    findings = _get_findings(health)
    workload = _get_workload(review)
    aging_items = _get_aging_items(review)
    deadline_risks = _get_deadline_risks(review)
    raid = _get_raid(review)
    metrics = _get_dict(review.get("metrics"))
    timing = _get_dict(review.get("timing"))

    total = max(_safe_int(board.get("total_items"), 0), 0)
    completed = min(max(_safe_int(board.get("completed_items"), 0), 0), total)
    unfinished = max(total - completed, 0)
    active = max(_safe_int(board.get("active_items"), 0), 0)
    new = max(_safe_int(board.get("new_items"), 0), 0)
    unassigned = _safe_int(board.get("unassigned_items"), 0)
    completed_pct = (completed / total * 100.0) if total else 0.0

    elapsed_pct = _safe_percentage(
        metrics.get("sprint_elapsed_pct", timing.get("elapsed_pct")), None
    )
    remaining_raw = metrics.get("days_remaining", timing.get("remaining_days"))
    remaining_days = _safe_int(remaining_raw) if remaining_raw is not None else None
    elapsed_days = _safe_int(timing.get("elapsed_days")) if timing.get("elapsed_days") is not None else None
    total_days = _safe_int(timing.get("total_days")) if timing.get("total_days") is not None else None
    gap = (elapsed_pct - completed_pct) if elapsed_pct is not None else None

    observed_completion_pace = None
    required_completion_pace = None
    pace_ratio = None
    if elapsed_days is not None and elapsed_days > 0:
        observed_completion_pace = completed / elapsed_days
    if remaining_days is not None and remaining_days > 0:
        required_completion_pace = unfinished / remaining_days
    if observed_completion_pace and required_completion_pace is not None:
        pace_ratio = required_completion_pace / observed_completion_pace

    aging_count = _safe_int(metrics.get("aging_count", len(aging_items)))
    deadline_count = _safe_int(metrics.get("deadline_risk_count", len(deadline_risks)))
    limited_count = _safe_int(metrics.get("limited_progress_count", 0))
    overloaded_count = _safe_int(metrics.get("overloaded_owner_count", 0))

    sprint = _get_dict(health.get("sprint") if health else {})
    sprint_name = _clean_text(sprint.get("name")) or "Current Sprint"
    sprint_start, sprint_end = _format_sprint_dates(sprint)
    project = details.get("Project", "Unknown")
    generated = _generated_timestamp()

    issues = [x for x in raid.get("issues", []) if isinstance(x, dict)]
    risks = [x for x in raid.get("risks", []) if isinstance(x, dict)]
    assumptions = [x for x in raid.get("assumptions", []) if isinstance(x, (dict, str))]
    dependencies = [x for x in raid.get("dependencies", []) if isinstance(x, dict)]
    adaptive_investigations = [
        x for x in _get_list(details.get("Adaptive Investigation"))
        if isinstance(x, dict)
    ]

    exploratory_findings: list[dict[str, Any]] = []
    for investigation in adaptive_investigations:
        for finding in _get_list(investigation.get("findings")):
            if isinstance(finding, dict):
                enriched = dict(finding)
                enriched["focus"] = investigation.get("focus", "all")
                exploratory_findings.append(enriched)

    def severity_label(value: Any) -> str:
        text = _clean_text(value).upper() or "UNKNOWN"
        return f"{_risk_icon(text)} {text}"

    lines: list[str] = [
        f"# 📊 Board Review — `{operation_id}`",
        "",
    ]

    # ------------------------------------------------------------------
    # Executive header
    # ------------------------------------------------------------------
    if health:
        score_band = _score_band(health_score)
        lines.extend([
            f"> {_health_icon(health_status)} **OVERALL HEALTH — {health_status}**",
            ">",
            f"> 🏃 **{sprint_name}**  ·  📅 **{sprint_start} → {sprint_end}**  ·  ⏱️ **{_format_percent(elapsed_pct)} elapsed**  ·  **{remaining_days if remaining_days is not None else 'Unknown'} days remaining**",
            f"> 🎯 **Deterministic risk score: {health_score:.0f}/100 ({score_band})**",
        ])
        if score_band != health_status:
            lines.append("> ℹ️ Overall status reflects the highest-severity deterministic condition; the numeric score is a separate aggregate risk signal.")
        lines.append("")
    else:
        lines.extend([
            "> ⚪ **OVERALL HEALTH — PARTIALLY ASSESSABLE**",
            ">",
            "> Sprint-health data was not available for a complete time-based assessment.",
            "",
        ])

    # ------------------------------------------------------------------
    # Executive snapshot: intentionally compact, not a giant dashboard.
    # ------------------------------------------------------------------
    lines.extend(["## 📌 Executive Snapshot", ""])
    snapshot_rows = [
        ["Delivery", f"**{completed}/{total} completed ({completed_pct:.1f}%)**", f"{unfinished} unfinished"],
        ["Execution", f"**{active} active**", f"{new} New"],
        ["Time pressure", f"**{gap:.1f} pts behind**" if gap is not None and gap > 0 else (f"**{abs(gap):.1f} pts ahead**" if gap is not None else "**Unknown**"), f"{_format_percent(elapsed_pct)} sprint elapsed" if elapsed_pct is not None else "Sprint timing unknown"],
        ["Deadlines", f"**{deadline_count} unfinished exposed**" if deadline_count else "**None identified**", "Overdue / due today / due soon" if deadline_count else "No deterministic exposure"],
        ["Attention", f"**{aging_count} aging**", f"{limited_count} limited-progress confirmed"],
        ["Ownership", f"**{overloaded_count} concentrated contributor(s)**", f"{unassigned} unassigned"],
    ]
    lines.extend([_markdown_table(["Area", "Signal", "Context"], snapshot_rows), ""])

    # ------------------------------------------------------------------
    # Delivery outlook: deterministic pace comparison. This is an indicator,
    # not a forecast, and assumes the current unfinished scope remains in scope.
    # ------------------------------------------------------------------
    if remaining_days is not None and remaining_days > 0:
        lines.extend(["## ⚡ Delivery Outlook", ""])
        if required_completion_pace is not None:
            lines.append(
                f"> **{unfinished} unfinished items** remain with **{remaining_days} day(s)** left — about **{required_completion_pace:.2f} items/day** would be required to finish all current unfinished scope."
            )
        if observed_completion_pace is not None:
            lines.append(
                f"> Observed completion pace so far: **{observed_completion_pace:.2f} items/day** ({completed} completed across {elapsed_days} elapsed day(s))."
            )
        if pace_ratio is not None:
            lines.append(
                f"> **Required pace is {pace_ratio:.1f}× the observed completion pace.** This is a deterministic delivery-pressure indicator, not a prediction of future velocity."
            )
        lines.append("")

    # ------------------------------------------------------------------
    # Current issues: compact executive table.
    # ------------------------------------------------------------------
    lines.extend(["## 🚨 Current Issues", ""])
    if issues:
        rows = []
        for idx, issue in enumerate(issues[:8], 1):
            severity = _clean_text(issue.get("severity") or "MEDIUM").upper()
            title = _clean_text(issue.get("issue") or issue.get("description") or "Current delivery issue")
            owner = _display_owner(issue.get("owner"))
            scope = f"#{issue.get('work_item_id')}" if issue.get("work_item_id") is not None else "Sprint"
            evidence = _clean_text(issue.get("observed") or issue.get("evidence")) or "Evidence not recorded."
            action = _clean_text(issue.get("action") or issue.get("recommendation")) or "Review the condition."
            rows.append([
                f"**I-{idx:03d}**  {severity_label(severity)}",
                f"**{title}**<br><sub>{scope} · {owner}</sub>",
                _truncate(evidence, 105),
                _truncate(action, 105),
            ])
        lines.extend([
            _markdown_table(["Priority", "Issue", "Evidence", "Action"], rows),
            "",
        ])
        if len(issues) > 8:
            lines.append(f"> +{len(issues) - 8} additional current issue(s) in the deterministic register.")
            lines.append("")
    else:
        lines.extend(["> 🟢 **No confirmed current issues were identified by the deterministic checks.**", ""])

    # ------------------------------------------------------------------
    # Adaptive exploratory findings. These are deliberately separated from
    # confirmed issues and risks. The agent may discover them dynamically.
    # ------------------------------------------------------------------
    if exploratory_findings:
        lines.extend(["## 🔎 Exploratory Findings", "",
                      "> These observations were discovered during adaptive investigation. They are not automatically defects or blockers.", ""])
        rows = []
        for finding in exploratory_findings[:8]:
            ftype = _clean_text(finding.get("type")).replace("_", " ").title() or "Observation"
            evidence = _clean_text(finding.get("evidence")) or "Evidence recorded by investigation."
            interpretation = _clean_text(finding.get("interpretation")) or "Further context may be required."
            scope = finding.get("work_item_id")
            if scope is None and finding.get("work_item_ids"):
                ids = finding.get("work_item_ids")
                scope = ", ".join(f"#{x}" for x in ids[:5])
                if len(ids) > 5:
                    scope += " …"
            elif scope is not None:
                scope = f"#{scope}"
            else:
                scope = "Board"
            rows.append([
                f"**{ftype}**",
                _truncate(scope, 50),
                _truncate(evidence, 110),
                _truncate(interpretation, 110),
            ])
        lines.extend([_markdown_table(["Observation", "Scope", "Observed Evidence", "Interpretation"], rows), ""])
        if len(exploratory_findings) > 8:
            lines.append(f"> +{len(exploratory_findings) - 8} additional exploratory observation(s).")
            lines.append("")

    # ------------------------------------------------------------------
    # Executive assessment: concise interpretation, not another table.
    # ------------------------------------------------------------------
    lines.extend(["## 🎯 Executive Assessment", ""])
    assessment: list[str] = []
    if total:
        assessment.append(f"**{completed} of {total}** items are complete; **{unfinished}** remain unfinished.")
    if gap is not None and gap >= 15:
        assessment.append(f"Sprint time is **{gap:.1f} percentage points ahead of completion**, indicating material delivery pressure.")
    if deadline_count:
        due_today = sum(1 for x in deadline_risks if _clean_text(x.get("due_status")).upper() == "DUE_TODAY")
        overdue = sum(1 for x in deadline_risks if _clean_text(x.get("due_status")).upper() == "OVERDUE")
        due_soon = sum(1 for x in deadline_risks if _clean_text(x.get("due_status")).upper() == "DUE_SOON")
        parts = []
        if overdue: parts.append(f"{overdue} overdue")
        if due_today: parts.append(f"{due_today} due today")
        if due_soon: parts.append(f"{due_soon} due soon")
        assessment.append(f"**{deadline_count}** unfinished items have deadline exposure ({', '.join(parts)}).")
    if overloaded_count:
        assessment.append(f"**{overloaded_count}** contributor(s) meet the deterministic active-work concentration threshold.")
    if new and elapsed_pct is not None and elapsed_pct >= 35:
        assessment.append(f"**{new}** unfinished items remain in New after {elapsed_pct:.1f}% of the sprint has elapsed.")
    if limited_count:
        assessment.append(f"**{limited_count}** items have confirmed limited progress based on available timestamps.")
    if not assessment:
        assessment.append("No material exception was produced by the deterministic Board Review checks.")
    lines.extend([_bullet_list(assessment), ""])

    # ------------------------------------------------------------------
    # Health and delivery detail.
    # ------------------------------------------------------------------
    if health:
        lines.extend([
            "## 🏁 Sprint Health", "",
            _markdown_table(["Signal", "Value"], [
                ["Sprint", sprint_name],
                ["Window", f"{sprint_start} → {sprint_end}"],
                ["Duration", f"{total_days} days" if total_days is not None else "Unknown"],
                ["Elapsed", f"{elapsed_days} days ({_format_percent(elapsed_pct)})" if elapsed_days is not None and elapsed_pct is not None else "Unknown"],
                ["Remaining", f"{remaining_days} days" if remaining_days is not None else "Unknown"],
                ["Completion gap", f"{gap:.1f} percentage points behind" if gap is not None and gap > 0 else (f"{abs(gap):.1f} percentage points ahead" if gap is not None and gap < 0 else "Aligned")],
            ]),
            "",
            "### 📈 Delivery Flow",
            "",
            _markdown_table(["Completed", "Active", "New", "Unfinished"], [[completed, active, new, unfinished]]),
            "",
        ])

    if aging_items or limited_count:
        attention = list(aging_items)
        seen = {_clean_text(x.get("work_item_id")) for x in attention}
        for finding in findings:
            fid = _clean_text(finding.get("work_item_id"))
            if fid and fid not in seen and finding.get("progress_observed") is False:
                attention.append(finding)
        if attention:
            lines.extend(["### 🕒 Time-Based Attention", ""])
            rows = []
            for item in attention[:10]:
                rows.append([
                    f"#{item.get('work_item_id')}" if item.get("work_item_id") is not None else "—",
                    _truncate(item.get("title"), 42),
                    item.get("state", "Unknown"),
                    _display_owner(item.get("owner")),
                    f"{_safe_int(item.get('item_age_days'))}d" if item.get("item_age_days") is not None else "—",
                    f"{_safe_int(item.get('days_in_current_state'))}d" if item.get("days_in_current_state") is not None else "—",
                    _attention_status(item),
                ])
            lines.extend([
                _markdown_table(["ID", "Work Item", "State", "Owner", "Age", "In State", "Assessment"], rows),
                "",
            ])
            if len(attention) > 10:
                lines.extend([f"> +{len(attention) - 10} additional time-based item(s).", ""])

    # ------------------------------------------------------------------
    # Deadline section: summarize first, then provide evidence.
    # ------------------------------------------------------------------
    if deadline_risks:
        overdue = sum(1 for x in deadline_risks if _clean_text(x.get("due_status")).upper() == "OVERDUE")
        due_today = sum(1 for x in deadline_risks if _clean_text(x.get("due_status")).upper() == "DUE_TODAY")
        due_soon = sum(1 for x in deadline_risks if _clean_text(x.get("due_status")).upper() == "DUE_SOON")
        lines.extend([
            "## 🚨 Deadline Exposure", "",
            _markdown_table(["Exposure", "Count"], [
                ["Overdue", overdue],
                ["Due today", due_today],
                ["Due soon", due_soon],
                ["Total unfinished exposed", len(deadline_risks)],
            ]),
            "",
            "### Affected Work Items",
            "",
        ])
        rows = []
        for item in deadline_risks[:12]:
            rows.append([
                f"#{item.get('work_item_id')}" if item.get("work_item_id") is not None else "—",
                _truncate(item.get("title"), 42),
                item.get("state", "Unknown"),
                _display_owner(item.get("owner")),
                _format_date(item.get("target_date") or item.get("due_date")),
                _deadline_status(item.get("due_status")),
            ])
        lines.extend([_markdown_table(["ID", "Work Item", "State", "Owner", "Deadline", "Status"], rows), ""])
        if len(deadline_risks) > 12:
            lines.extend([f"> +{len(deadline_risks) - 12} additional deadline-exposed item(s).", ""])

    # ------------------------------------------------------------------
    # Workload: explicitly explain denominators.
    # ------------------------------------------------------------------
    lines.extend(["## 👥 Workload", ""])
    if workload:
        rows = []
        for entry in workload:
            rows.append([
                _display_owner(entry.get("owner")),
                _safe_int(entry.get("active_items")),
                _safe_int(entry.get("new_items")),
                _safe_int(entry.get("unfinished_items", entry.get("in_scope_items", 0))),
                _format_percent(entry.get("board_share")),
                _format_percent(entry.get("active_work_pct")),
                severity_label(entry.get("status") or "NORMAL"),
            ])
        lines.extend([
            _markdown_table(["Assignee", "Active", "New", "Unfinished", "Unfinished Board Share", "Active Workload Share", "Assessment"], rows),
            "",
            "> **Unfinished Board Share** = owner's unfinished items ÷ all unfinished items.  ",
            "> **Active Workload Share** = owner's active items ÷ all active items.  ",
            "> A concentration assessment is relative; it does not by itself prove that a person is overloaded.",
            "",
        ])
    else:
        lines.extend(["> ⚪ Workload data unavailable.", ""])

    # ------------------------------------------------------------------
    # RAID: keep it a register, not a duplicate of the whole report.
    # ------------------------------------------------------------------
    lines.extend(["## 🧩 RAID Register", ""])

    lines.extend(["### 🔴 Risks", ""])
    if risks:
        for idx, risk in enumerate(risks[:5], 1):
            affected = risk.get("affected_work_item_ids") or []
            if affected:
                scope = ", ".join(f"#{x}" for x in affected[:10]) + (" …" if len(affected) > 10 else "")
            else:
                scope = f"#{risk.get('work_item_id')}" if risk.get("work_item_id") is not None else "Sprint"
            lines.extend([
                f"**R-{idx:03d} · {severity_label(risk.get('severity'))}**  ",
                f"{_truncate(risk.get('risk') or risk.get('description') or risk.get('inferred'), 120)}  ",
                f"*Scope:* {scope} · *Owner:* {_display_owner(risk.get('owner'))}  ",
                f"*Evidence:* {_clean_text(risk.get('observed') or risk.get('evidence')) or 'Not recorded.'}",
                "",
            ])
        if len(risks) > 5:
            lines.append(f"> +{len(risks) - 5} additional deterministic risk(s).\n")
    else:
        lines.extend(["> 🟢 **No deterministic risks were identified.**", ""])

    lines.extend(["### 🟡 Assumptions", ""])
    if assumptions:
        for idx, entry in enumerate(assumptions[:5], 1):
            text = (entry.get("assumption") or entry.get("text") or entry.get("description") or str(entry)) if isinstance(entry, dict) else str(entry)
            lines.append(f"- **A-{idx:03d}:** {_clean_text(text)}")
    else:
        lines.append("> 🟢 **No assumptions requiring executive action were identified.**")
    lines.append("")

    lines.extend(["### 🔴 Issues", ""])
    if issues:
        lines.append("> Current Issues above are the authoritative executive issue list; RAID Issues are not duplicated here.")
    else:
        lines.append("> 🟢 **No confirmed current issues were identified.**")
    lines.append("")

    lines.extend(["### 🔗 Dependencies", ""])
    if dependencies:
        lines.append(f"> **{len(dependencies)}** dependency relationship(s) were observed. Relationship status remains **UNKNOWN** unless Azure DevOps provides explicit status evidence.")
        rows = []
        for idx, entry in enumerate(dependencies[:8], 1):
            source = entry.get("work_item_id") or entry.get("source")
            target = entry.get("dependency_work_item_id") or entry.get("target")
            raw_relation = _clean_text(entry.get("relation") or entry.get("type") or "Related")
            relation_label = (
                "Depends on" if "dependency-forward" in raw_relation.casefold()
                else "Dependency" if "dependency-reverse" in raw_relation.casefold()
                else "Dependency" if "dependency" in raw_relation.casefold()
                else raw_relation
            )
            rows.append([
                f"D-{idx:03d}",
                f"#{source}" if source is not None else "—",
                relation_label,
                f"#{target}" if target is not None else "—",
                _clean_text(entry.get("status")) or "UNKNOWN",
            ])
        lines.extend([_markdown_table(["ID", "Source", "Relationship", "Target", "Status"], rows), ""])
        if len(dependencies) > 8:
            lines.append(f"> +{len(dependencies) - 8} additional dependency relationship(s).\n")
    elif review.get("dependency_data_available") is False:
        lines.extend(["> ⚪ Dependency relationships were not available in the retrieved data.", ""])
    else:
        lines.extend(["> 🟢 **No explicit dependency relationships were observed.**", ""])

    # ------------------------------------------------------------------
    # Key findings and actions: synthesis, not another copy of the issue list.
    # ------------------------------------------------------------------
    lines.extend(["## 🔎 Key Findings", ""])
    finding_rows = []
    if deadline_count:
        due_today = sum(1 for x in deadline_risks if _clean_text(x.get("due_status")).upper() == "DUE_TODAY")
        overdue = sum(1 for x in deadline_risks if _clean_text(x.get("due_status")).upper() == "OVERDUE")
        finding_rows.append(["Deadline exposure", f"{deadline_count} unfinished items exposed ({due_today} due today, {overdue} overdue).", "Immediate delivery attention is warranted."])
    if gap is not None and gap >= 15:
        finding_rows.append(["Delivery pace", f"Completion is {gap:.1f} percentage points behind sprint elapsed time.", "Remaining work must be evaluated against the 7-day window."])
    if overloaded_count:
        finding_rows.append(["Active concentration", f"{overloaded_count} contributor(s) meet the active-work concentration threshold.", "Consider workload balancing if the concentration is not intentional."])
    if new and elapsed_pct is not None and elapsed_pct >= 35:
        finding_rows.append(["Unstarted scope", f"{new} unfinished items remain New at {elapsed_pct:.1f}% sprint elapsed.", "Confirm which New items are committed and feasible."])
    if finding_rows:
        lines.extend([_markdown_table(["Finding", "Observed", "Why It Matters"], finding_rows[:4]), ""])
    else:
        lines.extend(["> 🟢 **No additional synthesis was required beyond the issue register.**", ""])

    lines.extend(["## 🎯 Recommended Actions", ""])
    action_rows = []
    seen_actions = set()
    for issue in sorted(issues, key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "WATCH": 4, "HEALTHY": 5}.get(_clean_text(x.get("severity", "UNKNOWN")).upper(), 9)):
        action = _clean_text(issue.get("action") or issue.get("recommendation"))
        if not action or action.casefold() in seen_actions:
            continue
        seen_actions.add(action.casefold())
        action_rows.append((issue.get("severity") or "MEDIUM", action))
    if action_rows:
        for idx, (severity, action) in enumerate(action_rows[:6], 1):
            lines.append(f"**{idx}. {severity_label(severity)}** — {action}")
            lines.append("")
    else:
        lines.extend(["> 🟢 **No immediate action was generated from the deterministic findings.**", ""])

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    lines.extend([
        "---", "",
        f"> **Audit:** `{operation_id}`  ·  **Project:** `{_clean_text(project) or 'Unknown'}`  ·  **Generated:** {generated}",
        f"> **Scope:** {total} work items  ·  **Analysis:** Board · Sprint · Progress · Aging · Workload · Deadlines · RAID",
        "> _Deterministic Azure DevOps evidence is the source of truth; UNKNOWN is never treated as a negative fact._",
        "",
    ])
    return "\n".join(lines)

def _build_sprint_report(operation_id: str, operation: str, status: str, summary: str, details: dict) -> str:
    details = details or {}
    project = details.get("Project", "Unknown")
    generated = _generated_timestamp()
    excluded = {"Project", "Tools Executed", "User Request"}
    rows = [[f"**{_clean_text(key)}**", value] for key, value in details.items() if key not in excluded]
    details_section = _markdown_table(["Field", "Value"], rows) if rows else "_No additional sprint details were recorded._"
    return f"""# 🏃 Sprint Operation Report

> 📅 **Azure DevOps sprint / iteration activity**
>
> Technical execution audit recorded by the AI Agent.

---

## 📋 Audit Information

{_markdown_table(
    ["Field", "Details"],
    [
        ["Audit ID", f"`{operation_id}`"],
        ["Operation", operation],
        ["Project", project],
        ["Status", _status_badge(status)],
        ["Generated", generated],
    ],
)}

---

## 📝 Result

{summary or "_No operation summary was recorded._"}

---

## 📅 Sprint Details

{details_section}

---

## 🔧 Execution

**Tools executed:** {_format_tools(details.get("Tools Executed", ""))}

---

## 🔐 Audit Trail

{_markdown_table(
    ["Field", "Value"],
    [
        ["Audit ID", f"`{operation_id}`"],
        ["Operation", operation],
        ["Status", _status_badge(status)],
        ["Agent", "Azure DevOps AI Agent"],
    ],
)}

---

> 🤖 _Generated automatically by the Azure DevOps AI Agent._
"""

def _build_workitem_report(operation_id: str, operation: str, status: str, summary: str, details: dict) -> str:
    details = details or {}
    project = details.get("Project", "Unknown")
    generated = _generated_timestamp()
    excluded = {"Project", "Tools Executed", "User Request"}
    rows = [[f"**{_clean_text(key)}**", value] for key, value in details.items() if key not in excluded]
    details_section = _markdown_table(["Field", "Value"], rows) if rows else "_No additional work-item details were recorded._"
    return f"""# 📝 Work Item Operation Report

> 🛠️ **Azure DevOps work-item activity**
>
> Technical execution audit recorded by the AI Agent.

---

## 📋 Audit Information

{_markdown_table(
    ["Field", "Details"],
    [
        ["Audit ID", f"`{operation_id}`"],
        ["Operation", operation],
        ["Project", project],
        ["Status", _status_badge(status)],
        ["Generated", generated],
    ],
)}

---

## 📝 Operation Result

{summary or "_No operation summary was recorded._"}

---

## 🔎 Work Item Details

{details_section}

---

## 🔧 Execution

**Tools executed:** {_format_tools(details.get("Tools Executed", ""))}

---

## 🔐 Audit Trail

{_markdown_table(
    ["Field", "Value"],
    [
        ["Audit ID", f"`{operation_id}`"],
        ["Operation", operation],
        ["Status", _status_badge(status)],
        ["Agent", "Azure DevOps AI Agent"],
    ],
)}

---

> 🤖 _Generated automatically by the Azure DevOps AI Agent._
"""

def build_audit_report(operation_id: str, operation: str, status: str, summary: str, details: dict) -> str:
    details = details or {}
    operation_id = _clean_text(operation_id) or get_next_operation_id(_clean_text(operation) or "AUDIT")
    operation_upper = operation_id.split("-", 1)[0].upper()
    summary = _clean_text(summary)
    if isinstance(details.get("Board Review"), dict):
        return _build_comprehensive_board_report(operation_id, details)
    if operation_upper == "BOARD":
        return _build_board_report(operation_id, operation, status, summary, details)
    if operation_upper == "SPRINT":
        return _build_sprint_report(operation_id, operation, status, summary, details)
    if operation_upper == "WORKITEM":
        return _build_workitem_report(operation_id, operation, status, summary, details)
    return _build_generic_report(operation_id, operation, status, summary, details)