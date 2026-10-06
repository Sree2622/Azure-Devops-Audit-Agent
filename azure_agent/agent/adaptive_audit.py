"""Deterministic exploratory analysis for adaptive Azure DevOps audits.

This module is deliberately broader than the baseline Board Review.  It finds
interesting patterns without declaring every pattern a defect.  The LLM may
choose which investigation to run; this module only reports evidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .sprint_health import ACTIVE_STATES, DONE_STATES


def _state(item: dict[str, Any]) -> str:
    return str(item.get("state") or "Unknown").strip()


def _done(item: dict[str, Any]) -> bool:
    return _state(item).casefold() in DONE_STATES


def _active(item: dict[str, Any]) -> bool:
    return _state(item).casefold() in ACTIVE_STATES


def _owner(item: dict[str, Any]) -> str:
    return str(item.get("assigned_to") or "Unassigned").strip()


def _title(item: dict[str, Any]) -> str:
    return str(item.get("title") or "").strip()


def _investigate_deadlines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for item in items:
        if _done(item):
            continue
        target = item.get("target_date") or item.get("due_date")
        if not target:
            continue
        findings.append({
            "type": "DEADLINE_STATE",
            "evidence": "Target date is present on unfinished work.",
            "work_item_id": item.get("id"),
            "title": _title(item),
            "state": _state(item),
            "owner": _owner(item),
            "target_date": target,
            "classification": "OBSERVED",
        })
    return findings


def _investigate_duplicates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if _done(item):
            continue
        title = _title(item)
        if title:
            groups[title.casefold()].append(item)

    findings = []
    for group in groups.values():
        if len(group) < 2:
            continue
        findings.append({
            "type": "POTENTIAL_DUPLICATE_SCOPE",
            "classification": "OBSERVED",
            "title": _title(group[0]),
            "work_item_ids": [item.get("id") for item in group],
            "evidence": "Multiple unfinished work items have the same title.",
            "interpretation": "Potential duplicate scope; identical titles do not prove duplication.",
        })
    return sorted(findings, key=lambda x: (-len(x["work_item_ids"]), x["title"].casefold()))


def _investigate_workload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = [item for item in items if not _done(item) and _active(item)]
    counts = Counter(_owner(item) for item in active)
    total = len(active)
    if not total:
        return []

    return [
        {
            "type": "ACTIVE_CONCENTRATION",
            "classification": "OBSERVED",
            "owner": owner,
            "active_items": count,
            "active_share_pct": round(count / total * 100, 1),
            "evidence": f"{count} of {total} active work items are assigned to {owner}.",
            "interpretation": "Concentration may warrant review; overload is not established by ownership alone.",
        }
        for owner, count in counts.most_common()
        if count >= 2 and count / total >= 0.25
    ]


def _investigate_state_patterns(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unfinished = [item for item in items if not _done(item)]
    states = Counter(_state(item) for item in unfinished)
    total = len(unfinished)
    if not total:
        return []

    return [
        {
            "type": "STATE_CONCENTRATION",
            "classification": "OBSERVED",
            "state": state,
            "count": count,
            "share_pct": round(count / total * 100, 1),
            "evidence": f"{count} of {total} unfinished items are in {state}.",
            "interpretation": "State concentration is an observation; delivery impact requires context.",
        }
        for state, count in states.most_common()
        if count / total >= 0.50
    ]


def _investigate_relations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for item in items:
        relations = item.get("dependencies") or item.get("relations")
        if not isinstance(relations, list):
            continue
        dependency_count = sum(
            1 for relation in relations
            if isinstance(relation, dict)
            and "dependency" in str(relation.get("rel") or relation.get("type") or "").casefold()
        )
        if dependency_count:
            findings.append({
                "type": "DEPENDENCY_DENSITY",
                "classification": "OBSERVED",
                "work_item_id": item.get("id"),
                "title": _title(item),
                "dependency_count": dependency_count,
                "evidence": f"{dependency_count} dependency relationship(s) are attached to this work item.",
                "interpretation": "Dependency presence does not establish blockage or delay.",
            })
    return findings


def investigate(items: list[dict[str, Any]], focus: str = "all") -> dict[str, Any]:
    """Run a focused exploratory investigation over already retrieved items.

    ``focus`` is a hint, not a rigid audit category.  ``all`` performs the
    inexpensive local checks.  No finding is treated as proof of impact.
    """
    normalized = (focus or "all").strip().casefold()
    selected = {
        "deadline": _investigate_deadlines,
        "deadlines": _investigate_deadlines,
        "workload": _investigate_workload,
        "ownership": _investigate_workload,
        "duplicates": _investigate_duplicates,
        "scope": _investigate_duplicates,
        "state": _investigate_state_patterns,
        "states": _investigate_state_patterns,
        "dependencies": _investigate_relations,
        "relations": _investigate_relations,
    }

    if normalized in selected:
        checks = [selected[normalized]]
    else:
        checks = [
            _investigate_deadlines,
            _investigate_duplicates,
            _investigate_workload,
            _investigate_state_patterns,
            _investigate_relations,
        ]

    findings: list[dict[str, Any]] = []
    for check in checks:
        findings.extend(check(items))

    return {
        "success": True,
        "status": "Completed",
        "operation": "Adaptive board investigation",
        "focus": normalized or "all",
        "finding_count": len(findings),
        "findings": findings,
        "evidence_policy": "Findings are OBSERVED patterns; interpretations are not proof of impact.",
    }
