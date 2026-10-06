"""Compact, failure-safe Azure DevOps tools.

This module is the Azure DevOps integration layer for the agent.

Design rules:
- Read operations are deterministic and read-only.
- Write operations never invent Azure DevOps values.
- Exact iteration paths come from Azure DevOps classification data.
- Work-item states are validated against the configured work-item type.
- Missing data is represented as UNKNOWN rather than guessed.
- Tool failures return structured results instead of raising into LangGraph.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional
from urllib.parse import quote

import requests
from langchain_core.tools import tool

from .config import API_VERSION, BASE_URL, ORG_URL, PAT, PROJECT, REQUEST_TIMEOUT


SESSION = requests.Session()


FIELD_MAP = {
    "state": "System.State",
    "title": "System.Title",
    "description": "System.Description",
    "priority": "Microsoft.VSTS.Common.Priority",
    "assigned_to": "System.AssignedTo",
    "iteration": "System.IterationPath",
    "area": "System.AreaPath",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def headers(content_type: str = "application/json") -> dict[str, str]:
    """Return Azure DevOps authentication headers."""
    return {
        "Content-Type": content_type,
        "Authorization": requests.auth._basic_auth_str("", PAT or ""),
    }


def _error(operation: str, response: requests.Response) -> dict[str, Any]:
    """Convert an HTTP failure into a compact structured result."""
    try:
        payload = response.json()
        reason = (
            payload.get("message")
            or payload.get("error")
            or payload.get("Message")
            or response.text
        )
    except ValueError:
        reason = response.text

    code = response.status_code

    if code in {401, 403}:
        category = "authentication/permission"
    elif code == 404:
        category = "not found"
    elif code == 409:
        category = "conflict"
    elif code == 400:
        category = "validation"
    elif code == 429:
        category = "rate limited"
    else:
        category = "request failed"

    message = str(reason)[:1500]

    return {
        "success": False,
        "status": "Failed",
        "operation": operation,
        "http_status": code,
        "errors": [
            {
                "category": category,
                "message": message,
            }
        ],
        "error": message,
    }


def _safe_get(
    url: str,
    operation: str,
    *,
    params: Optional[dict[str, Any]] = None,
) -> tuple[Optional[requests.Response], Optional[dict[str, Any]]]:
    """GET helper that converts request exceptions into structured errors."""
    try:
        response = SESSION.get(
            url,
            headers=headers(),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            return None, _error(operation, response)
        return response, None
    except requests.RequestException as exc:
        return None, {
            "success": False,
            "status": "Failed",
            "operation": operation,
            "errors": [
                {
                    "category": "network",
                    "message": str(exc)[:1500],
                }
            ],
            "error": str(exc)[:1500],
        }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _field(fields: dict[str, Any], *names: str) -> Any:
    """Return the first available field alias."""
    for name in names:
        if name in fields:
            return fields[name]
    return None


def _display_identity(value: Any) -> Optional[str]:
    """Normalize Azure identity objects into a display string."""
    if isinstance(value, dict):
        return (
            value.get("displayName")
            or value.get("uniqueName")
            or value.get("mail")
            or value.get("id")
        )

    if value is None:
        return None

    return str(value)


def _relation_id(url: Any) -> Optional[str]:
    """Extract the work-item ID from an Azure DevOps relation URL."""
    if not url:
        return None

    text = str(url).rstrip("/")

    if not text:
        return None

    candidate = text.split("/")[-1]

    return candidate if candidate.isdigit() else None


def _relation_type(relation: dict[str, Any]) -> str:
    return str(relation.get("rel") or "")


def _is_dependency_relation(relation: dict[str, Any]) -> bool:
    """Detect Azure DevOps dependency relation types."""
    rel = _relation_type(relation).casefold()

    return (
        "dependency" in rel
        or "predecessor" in rel
        or "successor" in rel
    )


# ---------------------------------------------------------------------------
# Work-item compaction
# ---------------------------------------------------------------------------

def _compact(item: dict[str, Any]) -> dict[str, Any]:
    """Convert a full Azure work item into a stable compact representation."""

    fields = item.get("fields", item) or {}
    relations = item.get("relations") or []

    owner = _field(
        fields,
        "System.AssignedTo",
        "assigned_to",
        "assignedTo",
    )

    parent_id: Optional[str] = None
    children: list[str] = []
    dependencies: list[dict[str, Any]] = []
    related_items: list[dict[str, Any]] = []

    for relation in relations:
        rel = _relation_type(relation)
        related_id = _relation_id(relation.get("url"))

        if not related_id:
            continue

        if rel == "System.LinkTypes.Hierarchy-Reverse":
            parent_id = related_id

        elif rel == "System.LinkTypes.Hierarchy-Forward":
            children.append(related_id)

        elif _is_dependency_relation(relation):
            dependencies.append(
                {
                    "type": rel,
                    "work_item_id": related_id,
                }
            )

        elif rel:
            related_items.append(
                {
                    "type": rel,
                    "work_item_id": related_id,
                }
            )

    work_item_id = _field(
        fields,
        "System.Id",
        "id",
    )

    work_item_type = _field(
        fields,
        "System.WorkItemType",
        "type",
    )

    title = _field(
        fields,
        "System.Title",
        "title",
    )

    state = _field(
        fields,
        "System.State",
        "state",
    )

    created_date = _field(
        fields,
        "System.CreatedDate",
        "created_date",
        "createdDate",
    )

    changed_date = _field(
        fields,
        "System.ChangedDate",
        "changed_date",
        "changedDate",
    )

    state_change_date = _field(
        fields,
        "System.StateChangeDate",
        "state_change_date",
        "stateChangeDate",
    )

    target_date = _field(
        fields,
        "Microsoft.VSTS.Scheduling.TargetDate",
        "target_date",
        "targetDate",
    )

    due_date = _field(
        fields,
        "Microsoft.VSTS.Scheduling.DueDate",
        "System.DueDate",
        "due_date",
        "dueDate",
    )

    original_estimate = _field(
        fields,
        "Microsoft.VSTS.Scheduling.OriginalEstimate",
        "original_estimate",
    )

    remaining_work = _field(
        fields,
        "Microsoft.VSTS.Scheduling.RemainingWork",
        "remaining_work",
    )

    completed_work = _field(
        fields,
        "Microsoft.VSTS.Scheduling.CompletedWork",
        "completed_work",
    )

    return {
        "id": work_item_id,
        "type": work_item_type,
        "title": title,
        "state": state,
        "assigned_to": _display_identity(owner),
        "priority": _field(
            fields,
            "Microsoft.VSTS.Common.Priority",
            "priority",
        ),
        "iteration": _field(
            fields,
            "System.IterationPath",
            "iteration",
        ),
        "area": _field(
            fields,
            "System.AreaPath",
            "area",
        ),
        "created_date": created_date,
        "changed_date": changed_date,
        "state_change_date": state_change_date,
        "target_date": target_date,
        "due_date": due_date,
        "original_estimate": original_estimate,
        "remaining_work": remaining_work,
        "completed_work": completed_work,
        "parent_id": parent_id,
        "children": children,
        "dependencies": dependencies,
        "related_items": related_items,
        "relations_retrieved": "relations" in item,
        "relation_count": len(relations),
    }


# ---------------------------------------------------------------------------
# WIQL
# ---------------------------------------------------------------------------

def _query(
    query: str,
    limit: int = 50,
    operation: str = "Query work items",
) -> dict[str, Any]:
    """Run WIQL and retrieve compact work-item records."""

    try:
        response = SESSION.post(
            f"{BASE_URL}/_apis/wit/wiql",
            params={"api-version": API_VERSION},
            headers=headers(),
            json={"query": query},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {
            "success": False,
            "status": "Failed",
            "operation": operation,
            "errors": [
                {
                    "category": "network",
                    "message": str(exc)[:1500],
                }
            ],
            "error": str(exc)[:1500],
        }

    if not response.ok:
        return _error(operation, response)

    try:
        payload = response.json()
    except ValueError:
        return {
            "success": False,
            "status": "Failed",
            "operation": operation,
            "errors": [
                {
                    "category": "response",
                    "message": "Azure DevOps returned invalid JSON.",
                }
            ],
        }

    ids = [
        str(item.get("id"))
        for item in payload.get("workItems", [])
        if item.get("id") is not None
    ][:limit]

    if not ids:
        return {
            "success": True,
            "status": "Completed",
            "operation": operation,
            "items": [],
            "count": 0,
        }

    try:
        response = SESSION.get(
            f"{BASE_URL}/_apis/wit/workitems",
            params={
                "ids": ",".join(ids),
                "$expand": "all",
                "api-version": API_VERSION,
            },
            headers=headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Read work items",
            "errors": [
                {
                    "category": "network",
                    "message": str(exc)[:1500],
                }
            ],
            "error": str(exc)[:1500],
        }

    if not response.ok:
        return _error("Read work items", response)

    try:
        values = response.json().get("value", [])
    except ValueError:
        values = []

    items = [_compact(item) for item in values]

    return {
        "success": True,
        "status": "Completed",
        "operation": operation,
        "items": items,
        "count": len(items),
    }


# ---------------------------------------------------------------------------
# Read-only work-item tools
# ---------------------------------------------------------------------------

@tool
def read_work_items() -> dict:
    """Read up to 20 recently changed work items. Read-only; compact output."""
    return _query(
        """
        SELECT [System.Id]
        FROM WorkItems
        WHERE [System.TeamProject] = @project
        ORDER BY [System.ChangedDate] DESC
        """,
        20,
        "Read recent work items",
    )


@tool
def get_board_summary() -> dict:
    """Read current project work items for board-level analysis.

    Returns state, owner, iteration, dates, priority, relations and scheduling
    fields needed by deterministic Board Review calculations.
    """
    return _query(
        """
        SELECT [System.Id]
        FROM WorkItems
        WHERE [System.TeamProject] = @project
        ORDER BY [System.ChangedDate] DESC
        """,
        100,
        "Read board work items",
    )


@tool
def read_azure_board() -> dict:
    """Read Azure DevOps board definitions only."""
    response, error = _safe_get(
        f"{BASE_URL}/_apis/work/boards",
        "Read board definitions",
        params={"api-version": API_VERSION},
    )

    if error:
        return error

    try:
        boards = response.json().get("value", [])
    except ValueError:
        boards = []

    return {
        "success": True,
        "status": "Completed",
        "operation": "Read board definitions",
        "boards": [
            {
                "id": board.get("id"),
                "name": board.get("name"),
            }
            for board in boards
        ],
    }


@tool
def read_backlog() -> dict:
    """Read backlog items ordered by configured priority."""
    return _query(
        """
        SELECT [System.Id]
        FROM WorkItems
        WHERE [System.TeamProject] = @project
        ORDER BY [Microsoft.VSTS.Common.Priority] ASC
        """,
        100,
        "Read backlog",
    )


@tool
def read_test_cases() -> dict:
    """Read Test Case work items for coverage analysis."""
    return _query(
        """
        SELECT [System.Id]
        FROM WorkItems
        WHERE [System.TeamProject] = @project
          AND [System.WorkItemType] = 'Test Case'
        ORDER BY [System.ChangedDate] DESC
        """,
        100,
        "Read test cases",
    )


@tool
def get_work_item(work_item_id: int) -> dict:
    """Read one work item including actual hierarchy and relation data."""

    response, error = _safe_get(
        f"{BASE_URL}/_apis/wit/workitems/{work_item_id}",
        "Read work item",
        params={
            "$expand": "all",
            "api-version": API_VERSION,
        },
    )

    if error:
        error["affected_items"] = [work_item_id]
        return error

    try:
        item = _compact(response.json())
    except ValueError:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Read work item",
            "affected_items": [work_item_id],
            "errors": [
                {
                    "category": "response",
                    "message": "Azure DevOps returned invalid JSON.",
                }
            ],
        }

    return {
        "success": True,
        "status": "Completed",
        "operation": "Read work item",
        "affected_items": [work_item_id],
        "item": item,
    }


@tool
def get_project_teams() -> dict:
    """Discover project teams and their GUIDs.

    Team GUIDs must be resolved from Azure DevOps instead of being guessed
    from the project name.
    """

    response, error = _safe_get(
        f"{ORG_URL}/_apis/teams",
        "Discover project teams",
        params={"api-version": API_VERSION},
    )

    if error:
        return error

    try:
        teams = response.json().get("value", [])
    except ValueError:
        teams = []

    project_teams = []

    for team in teams:
        project = team.get("project") or {}

        if project.get("name") == PROJECT:
            project_teams.append(
                {
                    "id": team.get("id"),
                    "name": team.get("name"),
                    "project_id": project.get("id"),
                    "project_name": project.get("name"),
                }
            )

    return {
        "success": True,
        "status": "Completed",
        "operation": "Discover project teams",
        "teams": project_teams,
    }


# ---------------------------------------------------------------------------
# Sprint / iteration discovery
# ---------------------------------------------------------------------------

@tool
def read_sprints() -> dict:
    """Read all configured project iterations/sprints.

    The response preserves Azure DevOps' exact classification path and all
    available date representations.
    """

    response, error = _safe_get(
        f"{BASE_URL}/_apis/wit/classificationnodes/Iterations",
        "Read sprints",
        params={
            "$depth": 10,
            "api-version": API_VERSION,
        },
    )

    if error:
        return error

    try:
        root = response.json()
    except ValueError:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Read sprints",
            "errors": [
                {
                    "category": "response",
                    "message": "Azure DevOps returned invalid JSON.",
                }
            ],
        }

    found: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        if node.get("name"):
            attributes = node.get("attributes") or {}

            found.append(
                {
                    "name": node.get("name"),
                    "id": node.get("identifier"),
                    "path": node.get("path"),
                    "attributes": attributes,
                    # Preserve alternate date locations so downstream code
                    # never assumes one particular Azure representation.
                    "startDate": (
                        node.get("startDate")
                        or node.get("start")
                        or attributes.get("startDate")
                        or attributes.get("start")
                    ),
                    "finishDate": (
                        node.get("finishDate")
                        or node.get("finish")
                        or node.get("end")
                        or attributes.get("finishDate")
                        or attributes.get("finish")
                        or attributes.get("end")
                    ),
                }
            )

        for child in node.get("children", []) or []:
            visit(child)

    visit(root)

    return {
        "success": True,
        "status": "Completed",
        "operation": "Read sprints",
        "sprints": found[:200],
        "count": len(found),
    }


@tool
def get_iterations() -> dict:
    """Get Azure DevOps iterations and their exact System.IterationPath.

    Never construct a work-item iteration path from a sprint name manually.
    """

    result = read_sprints.invoke({})

    if not result.get("success"):
        return result

    iterations = []

    for sprint in result.get("sprints", []):
        classification_path = sprint.get("path")

        work_item_path = None

        if classification_path:
            # Azure classification nodes expose a synthetic "\Iteration\"
            # segment. System.IterationPath uses the project iteration path.
            work_item_path = classification_path.replace(
                "\\Iteration\\",
                "\\",
            ).lstrip("\\")

        iterations.append(
            {
                "name": sprint.get("name"),
                "id": sprint.get("id"),
                "work_item_iteration_path": work_item_path,
                "classification_path": classification_path,
                "attributes": sprint.get("attributes", {}),
                "startDate": sprint.get("startDate"),
                "finishDate": sprint.get("finishDate"),
            }
        )

    return {
        "success": True,
        "status": "Completed",
        "operation": "Get iterations",
        "iterations": iterations,
        "count": len(iterations),
    }


@tool
def read_sprint_health(sprint_name: Optional[str] = None) -> dict:
    """Read and deterministically calculate sprint health.

    Missing sprint dates do not crash the operation. The result explicitly
    reports timing as unavailable/unknown when Azure DevOps does not provide
    sufficient dates.
    """

    from .sprint_health import (
        build_sprint_health_report,
        select_sprint,
    )

    sprints = read_sprints.invoke({})

    if not sprints.get("success"):
        return sprints

    sprint = select_sprint(
        sprints.get("sprints", []),
        date.today(),
        sprint_name,
    )

    if not sprint:
        return {
            "success": True,
            "status": "Completed",
            "operation": "Read sprint health",
            "sprint_health": None,
            "warnings": [
                "No active or requested sprint could be identified."
            ],
        }

    iteration_path = None

    classification_path = sprint.get("path")

    if classification_path:
        iteration_path = classification_path.replace(
            "\\Iteration\\",
            "\\",
        ).lstrip("\\")

    if not iteration_path:
        return {
            "success": True,
            "status": "Completed",
            "operation": "Read sprint health",
            "sprint_health": {
                "timing_available": False,
                "overall_status": "UNKNOWN",
                "health_status": "UNKNOWN",
                "health_score": None,
                "sprint": {
                    "name": sprint.get("name"),
                    "path": sprint.get("path"),
                },
                "summary": {},
                "warnings": [
                    "The sprint has no usable System.IterationPath."
                ],
            },
            "warnings": [
                "Sprint work items could not be queried because the exact "
                "iteration path was unavailable."
            ],
        }

    escaped_path = iteration_path.replace("'", "''")

    result = _query(
        f"""
        SELECT [System.Id]
        FROM WorkItems
        WHERE [System.TeamProject] = @project
          AND [System.IterationPath] = '{escaped_path}'
        ORDER BY [System.ChangedDate] DESC
        """,
        100,
        "Read sprint work items",
    )

    if not result.get("success"):
        return result

    report = build_sprint_health_report(
        sprint,
        result.get("items", []),
        date.today(),
    )

    return {
        "success": True,
        "status": "Completed",
        "operation": "Read sprint health",
        "sprint_health": report,
    }


# ---------------------------------------------------------------------------
# Deterministic Board Review
# ---------------------------------------------------------------------------

@tool
def investigate_board(focus: str = "all") -> dict:
    """Run a focused exploratory investigation over the current board.

    This is an adaptive, read-only companion to ``review_board``.  Use it when
    the baseline review reveals an unusual pattern worth investigating, or
    when the user asks for a broader/open-ended audit.  ``focus`` may be a
    hint such as ``deadlines``, ``workload``, ``duplicates``, ``dependencies``,
    ``states``, or ``all``.  The investigation reports evidence and does not
    claim that a pattern is a confirmed defect.
    """
    from .adaptive_audit import investigate

    board = get_board_summary.invoke({})
    if not board.get("success"):
        return board

    try:
        result = investigate(board.get("items", []), focus)
    except Exception as exc:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Adaptive board investigation",
            "errors": [{"category": "investigation", "message": str(exc)[:1500]}],
        }

    result["affected_items"] = [
        item.get("id") for item in board.get("items", []) if item.get("id") is not None
    ]
    return result


@tool
def review_board(sprint_name: Optional[str] = None) -> dict:
    """Create a deterministic comprehensive Board Review.

    Combines:
    - current work-item data
    - sprint timing
    - completion/progress
    - aging
    - workload concentration
    - deadline coverage
    - RAID evidence

    This function does not call Gemini and does not publish to Wiki.
    """

    from .board_review import build_board_review

    board = get_board_summary.invoke({})

    if not board.get("success"):
        return board

    sprint = read_sprint_health.invoke(
        {"sprint_name": sprint_name}
    )

    warnings: list[str] = []

    if not sprint.get("success"):
        warnings.append(
            sprint.get(
                "error",
                "Sprint health data could not be retrieved.",
            )
        )
        sprint_health = None
    else:
        sprint_health = sprint.get("sprint_health")

        warnings.extend(
            sprint.get("warnings", []) or []
        )

    try:
        report = build_board_review(
            board.get("items", []),
            sprint_health,
            warnings,
        )
    except Exception as exc:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Board Review",
            "errors": [
                {
                    "category": "report_generation",
                    "message": str(exc)[:1500],
                }
            ],
        }

    return {
        "success": True,
        "status": "Completed",
        "operation": "Board Review",
        "affected_items": [
            item.get("id")
            for item in board.get("items", [])
            if item.get("id") is not None
        ],
        "evidence": report,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Work-item state validation
# ---------------------------------------------------------------------------

def _valid_states_for_type(work_item_type: str) -> dict[str, Any]:
    """Read the configured System.State values for a work-item type."""

    if not work_item_type:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Read valid work item states",
            "errors": [
                {
                    "category": "validation",
                    "message": "Work item type is unavailable.",
                }
            ],
        }

    encoded_type = quote(
        str(work_item_type),
        safe="",
    )

    response, error = _safe_get(
        f"{BASE_URL}/_apis/wit/workitemtypes/{encoded_type}/fields",
        "Read valid work item states",
        params={"api-version": API_VERSION},
    )

    if error:
        return error

    try:
        values = response.json().get("value", [])
    except ValueError:
        values = []

    field = next(
        (
            entry
            for entry in values
            if entry.get("referenceName") == "System.State"
        ),
        None,
    )

    allowed_values = (field or {}).get("allowedValues") or []

    return {
        "success": True,
        "status": "Completed",
        "operation": "Read valid work item states",
        "states": allowed_values,
        "evidence": {
            "work_item_type": work_item_type,
        },
    }


@tool
def get_valid_work_item_states(work_item_id: int) -> dict:
    """Retrieve the actual configured states for a work item's type."""

    before = get_work_item.invoke(
        {"work_item_id": work_item_id}
    )

    if not before.get("success"):
        return before

    item = before.get("item") or {}

    result = _valid_states_for_type(
        item.get("type")
    )

    result["affected_items"] = [work_item_id]

    return result


# ---------------------------------------------------------------------------
# Write: create work item
# ---------------------------------------------------------------------------

@tool
def add_item_to_board(
    title: str,
    description: str,
    work_item_type: str,
    priority: int = 2,
    assignee: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
) -> dict:
    """Create a work item.

    STATE-CHANGING:
    The graph must obtain explicit confirmation before invoking this tool.
    """

    if not title.strip():
        return {
            "success": False,
            "status": "Failed",
            "operation": "Create work item",
            "errors": [
                {
                    "category": "validation",
                    "message": "Title cannot be empty.",
                }
            ],
        }

    if not work_item_type.strip():
        return {
            "success": False,
            "status": "Failed",
            "operation": "Create work item",
            "errors": [
                {
                    "category": "validation",
                    "message": "Work item type cannot be empty.",
                }
            ],
        }

    operations = [
        {
            "op": "add",
            "path": "/fields/System.Title",
            "value": title,
        },
        {
            "op": "add",
            "path": "/fields/System.Description",
            "value": description,
        },
        {
            "op": "add",
            "path": "/fields/Microsoft.VSTS.Common.Priority",
            "value": priority,
        },
    ]

    if assignee:
        operations.append(
            {
                "op": "add",
                "path": "/fields/System.AssignedTo",
                "value": assignee,
            }
        )

    if acceptance_criteria:
        operations.append(
            {
                "op": "add",
                "path": "/fields/Microsoft.VSTS.Common.AcceptanceCriteria",
                "value": acceptance_criteria,
            }
        )

    encoded_type = quote(
        work_item_type,
        safe="",
    )

    try:
        response = SESSION.post(
            f"{BASE_URL}/_apis/wit/workitems/${encoded_type}",
            params={"api-version": API_VERSION},
            headers=headers("application/json-patch+json"),
            json=operations,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Create work item",
            "errors": [
                {
                    "category": "network",
                    "message": str(exc)[:1500],
                }
            ],
        }

    if not response.ok:
        return _error("Create work item", response)

    try:
        item = _compact(response.json())
    except ValueError:
        item = None

    return {
        "success": True,
        "status": "Completed",
        "operation": "Create work item",
        "item": item,
    }


# ---------------------------------------------------------------------------
# Write: update work item
# ---------------------------------------------------------------------------

@tool
def update_work_item(
    work_item_id: int,
    field: str,
    value: str,
) -> dict:
    """Update a supported work-item field after validation.

    Supported fields:
    state, title, description, priority, assigned_to, iteration, area.

    STATE-CHANGING:
    The graph must obtain explicit confirmation before invoking this tool.
    """

    normalized_field = field.strip().lower()

    azure_field = FIELD_MAP.get(normalized_field)

    if not azure_field:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Update work item",
            "affected_items": [work_item_id],
            "errors": [
                {
                    "category": "validation",
                    "message": (
                        f"Unsupported field '{field}'. "
                        f"Supported: {', '.join(FIELD_MAP)}"
                    ),
                }
            ],
        }

    before = get_work_item.invoke(
        {"work_item_id": work_item_id}
    )

    if not before.get("success"):
        return before

    old = before.get("item") or {}

    old_value = old.get(normalized_field)

    if (
        old_value is not None
        and str(old_value).casefold() == str(value).casefold()
    ):
        return {
            "success": True,
            "status": "No-Op",
            "operation": "Update work item",
            "affected_items": [work_item_id],
            "changes": [],
            "evidence": {
                "before": old,
            },
            "warnings": [
                "Work item already has the requested value."
            ],
        }

    # ---------------------------------------------------------------
    # State validation
    # ---------------------------------------------------------------

    if normalized_field == "state":
        valid = _valid_states_for_type(
            old.get("type")
        )

        if not valid.get("success"):
            valid["affected_items"] = [work_item_id]
            return valid

        states = valid.get("states") or []

        if states:
            normalized_states = {
                str(state).casefold()
                for state in states
            }

            if value.casefold() not in normalized_states:
                return {
                    "success": False,
                    "status": "Failed",
                    "operation": "Update work item",
                    "affected_items": [work_item_id],
                    "errors": [
                        {
                            "category": "validation",
                            "message": (
                                f"'{value}' is not a configured state "
                                f"for {old.get('type')}."
                            ),
                        }
                    ],
                    "evidence": {
                        "current_state": old.get("state"),
                        "valid_states": states,
                    },
                }

    # ---------------------------------------------------------------
    # Priority validation
    # ---------------------------------------------------------------

    patch_value: Any = value

    if normalized_field == "priority":
        try:
            patch_value = int(value)
        except (TypeError, ValueError):
            return {
                "success": False,
                "status": "Failed",
                "operation": "Update work item",
                "affected_items": [work_item_id],
                "errors": [
                    {
                        "category": "validation",
                        "message": "Priority must be an integer.",
                    }
                ],
            }

    # ---------------------------------------------------------------
    # Patch
    # ---------------------------------------------------------------

    patch = [
        {
            "op": "add",
            "path": f"/fields/{azure_field}",
            "value": patch_value,
        }
    ]

    try:
        response = SESSION.patch(
            f"{BASE_URL}/_apis/wit/workitems/{work_item_id}",
            params={"api-version": API_VERSION},
            headers=headers("application/json-patch+json"),
            json=patch,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Update work item",
            "affected_items": [work_item_id],
            "errors": [
                {
                    "category": "network",
                    "message": str(exc)[:1500],
                }
            ],
            "evidence": {
                "before": old,
            },
        }

    if not response.ok:
        result = _error(
            "Update work item",
            response,
        )
        result["affected_items"] = [work_item_id]
        result["evidence"] = {
            "before": old,
        }
        return result

    # ---------------------------------------------------------------
    # Verification
    # ---------------------------------------------------------------

    verified = get_work_item.invoke(
        {"work_item_id": work_item_id}
    )

    if not verified.get("success"):
        return {
            "success": False,
            "status": "Partially Completed",
            "operation": "Update work item",
            "affected_items": [work_item_id],
            "changes": [
                f"Requested {normalized_field} update"
            ],
            "errors": [
                {
                    "category": "verification",
                    "message": (
                        "Azure DevOps accepted the update, but "
                        "verification could not be completed."
                    ),
                }
            ],
            "evidence": {
                "before": old,
            },
        }

    updated = verified.get("item") or {}

    actual = updated.get(normalized_field)

    requested = str(value)

    if normalized_field == "priority":
        matches = str(actual) == requested
    else:
        matches = (
            str(actual or "").casefold()
            == requested.casefold()
        )

    if not matches:
        return {
            "success": False,
            "status": "Partially Completed",
            "operation": "Update work item",
            "affected_items": [work_item_id],
            "changes": [
                f"Requested {normalized_field} update"
            ],
            "errors": [
                {
                    "category": "verification",
                    "message": (
                        "Azure DevOps response did not contain "
                        "the requested value."
                    ),
                }
            ],
            "evidence": {
                "before": old,
                "after": updated,
                "requested": value,
                "actual": actual,
            },
        }

    return {
        "success": True,
        "status": "Completed",
        "operation": "Update work item",
        "affected_items": [work_item_id],
        "changes": [
            f"{normalized_field}: {old_value} -> {actual}"
        ],
        "evidence": {
            "before": old,
            "after": updated,
        },
    }


# ---------------------------------------------------------------------------
# Write: create / associate sprint
# ---------------------------------------------------------------------------

@tool
def add_sprint(
    sprint_name: str,
    start_date: str,
    finish_date: str,
) -> dict:
    """Create or repair a sprint/team association.

    STATE-CHANGING:
    The graph must obtain explicit confirmation before invoking this tool.

    Important:
    - The sprint iteration is created first.
    - The project team is resolved through Azure DevOps.
    - Team association is separately verified.
    """

    if not sprint_name.strip():
        return {
            "success": False,
            "status": "Failed",
            "operation": "Create sprint",
            "errors": [
                {
                    "category": "validation",
                    "message": "Sprint name cannot be empty.",
                }
            ],
        }

    teams = get_project_teams.invoke({})

    if not teams.get("success"):
        return teams

    configured_name = os.getenv(
        "AZURE_DEVOPS_TEAM"
    )

    available = teams.get("teams", [])

    team = None

    if configured_name:
        team = next(
            (
                entry
                for entry in available
                if str(entry.get("name", "")).casefold()
                == configured_name.casefold()
            ),
            None,
        )

    if not team and len(available) == 1:
        team = available[0]

    if not team:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Create sprint",
            "errors": [
                {
                    "category": "configuration",
                    "message": (
                        f"Configured team "
                        f"'{configured_name or '(unset)'}' "
                        "could not be resolved. "
                        "Available teams: "
                        + (
                            ", ".join(
                                str(entry.get("name"))
                                for entry in available
                            )
                            or "none"
                        )
                        + "."
                    ),
                }
            ],
        }

    # ---------------------------------------------------------------
    # Check existing iterations
    # ---------------------------------------------------------------

    sprints = read_sprints.invoke({})

    if not sprints.get("success"):
        return sprints

    matches = [
        sprint
        for sprint in sprints.get("sprints", [])
        if str(sprint.get("name", "")).casefold()
        == sprint_name.casefold()
    ]

    created = False

    if matches:
        iteration = matches[0]
    else:
        try:
            response = SESSION.post(
                f"{BASE_URL}/_apis/wit/classificationnodes/Iterations",
                params={"api-version": API_VERSION},
                headers=headers(),
                json={
                    "name": sprint_name,
                    "attributes": {
                        "startDate": (
                            f"{start_date}T00:00:00Z"
                        ),
                        "finishDate": (
                            f"{finish_date}T23:59:59Z"
                        ),
                    },
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            return {
                "success": False,
                "status": "Failed",
                "operation": "Create sprint",
                "errors": [
                    {
                        "category": "network",
                        "message": str(exc)[:1500],
                    }
                ],
            }

        if not response.ok:
            return _error(
                "Create sprint",
                response,
            )

        try:
            iteration = response.json()
        except ValueError:
            return {
                "success": False,
                "status": "Failed",
                "operation": "Create sprint",
                "errors": [
                    {
                        "category": "response",
                        "message": (
                            "Azure DevOps returned invalid JSON "
                            "after sprint creation."
                        ),
                    }
                ],
            }

        created = True

    iteration_id = iteration.get(
        "identifier"
    )

    iteration_path = iteration.get("path")

    base = {
        "operation": "Create sprint",
        "affected_items": [],
        "changes": [
            (
                "Classification iteration created"
                if created
                else "Existing classification iteration reused"
            )
        ],
        "evidence": {
            "iteration": {
                "name": iteration.get("name"),
                "id": iteration_id,
                "path": iteration_path,
                "attributes": iteration.get("attributes", {}),
            },
            "team": team,
        },
    }

    if not iteration_id:
        return {
            **base,
            "success": False,
            "status": (
                "Partially Completed"
                if created
                else "Failed"
            ),
            "errors": [
                {
                    "category": "response",
                    "message": (
                        "Azure DevOps returned no iteration identifier."
                    ),
                }
            ],
        }

    # ---------------------------------------------------------------
    # Check team association
    # ---------------------------------------------------------------

    team_id = team.get("id")

    if not team_id:
        return {
            **base,
            "success": False,
            "status": "Partially Completed",
            "errors": [
                {
                    "category": "configuration",
                    "message": (
                        "Resolved team has no GUID."
                    )
                }
            ],
        }

    response, error = _safe_get(
        f"{BASE_URL}/{team_id}/_apis/work/teamsettings/iterations",
        "Read team iteration settings",
        params={"api-version": API_VERSION},
    )

    if error:
        return {
            **base,
            "success": False,
            "status": (
                "Partially Completed"
                if created
                else "Failed"
            ),
            "errors": error.get("errors", []),
        }

    try:
        current_iterations = response.json().get(
            "value",
            [],
        )
    except ValueError:
        current_iterations = []

    already_associated = any(
        str(entry.get("id")) == str(iteration_id)
        for entry in current_iterations
    )

    if not already_associated:
        try:
            response = SESSION.post(
                f"{BASE_URL}/{team_id}/_apis/work/teamsettings/iterations",
                params={"api-version": API_VERSION},
                headers=headers(),
                json={"id": iteration_id},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            return {
                **base,
                "success": False,
                "status": (
                    "Partially Completed"
                    if created
                    else "Failed"
                ),
                "errors": [
                    {
                        "category": "network",
                        "message": str(exc)[:1500],
                    }
                ],
            }

        if not response.ok:
            error_result = _error(
                "Assign sprint to team",
                response,
            )

            return {
                **base,
                "success": False,
                "status": (
                    "Partially Completed"
                    if created
                    else "Failed"
                ),
                "errors": error_result.get(
                    "errors",
                    [],
                ),
            }

        base["changes"].append(
            "Iteration associated with team"
        )

    # ---------------------------------------------------------------
    # Verify team association
    # ---------------------------------------------------------------

    response, error = _safe_get(
        f"{BASE_URL}/{team_id}/_apis/work/teamsettings/iterations",
        "Verify team iteration association",
        params={"api-version": API_VERSION},
    )

    if error:
        return {
            **base,
            "success": False,
            "status": "Partially Completed",
            "errors": error.get(
                "errors",
                [],
            ),
        }

    try:
        verified_iterations = response.json().get(
            "value",
            [],
        )
    except ValueError:
        verified_iterations = []

    verified = any(
        str(entry.get("id")) == str(iteration_id)
        for entry in verified_iterations
    )

    if not verified:
        return {
            **base,
            "success": False,
            "status": "Partially Completed",
            "errors": [
                {
                    "category": "verification",
                    "message": (
                        "The iteration exists, but its "
                        "association with the team could "
                        "not be verified."
                    ),
                }
            ],
        }

    warnings: list[str] = []

    if not created and already_associated:
        warnings.append(
            "Sprint already exists and is already associated "
            "with the team."
        )

    status = (
        "Completed"
        if created or not already_associated
        else "No-Op"
    )

    return {
        **base,
        "success": True,
        "status": status,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Write: move work items
# ---------------------------------------------------------------------------

@tool
def move_work_items(
    work_item_ids: list[int],
    iteration_path: str,
) -> dict:
    """Move work items to an existing exact System.IterationPath.

    STATE-CHANGING:
    The graph must obtain explicit confirmation before invoking this tool.
    """

    if not work_item_ids:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Move work items",
            "errors": [
                {
                    "category": "validation",
                    "message": "No work item IDs were supplied.",
                }
            ],
        }

    if not iteration_path.strip():
        return {
            "success": False,
            "status": "Failed",
            "operation": "Move work items",
            "affected_items": work_item_ids,
            "errors": [
                {
                    "category": "validation",
                    "message": "Iteration path cannot be empty.",
                }
            ],
        }

    iterations = get_iterations.invoke({})

    if not iterations.get("success"):
        return {
            **iterations,
            "operation": "Move work items",
            "affected_items": work_item_ids,
        }

    actual_paths = {
        item.get("work_item_iteration_path")
        for item in iterations.get("iterations", [])
        if item.get("work_item_iteration_path")
    }

    if iteration_path not in actual_paths:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Move work items",
            "affected_items": work_item_ids,
            "errors": [
                {
                    "category": "validation",
                    "code": "INVALID_ITERATION_PATH",
                    "message": (
                        "The supplied path is not a valid "
                        "System.IterationPath. Use get_iterations "
                        "and pass work_item_iteration_path, not "
                        "classification_path."
                    ),
                }
            ],
        }

    results = []

    for work_item_id in work_item_ids:
        result = update_work_item.invoke(
            {
                "work_item_id": work_item_id,
                "field": "iteration",
                "value": iteration_path,
            }
        )

        results.append(result)

    failed = [
        result
        for result in results
        if not result.get("success")
    ]

    successful = [
        result
        for result in results
        if result.get("success")
    ]

    if not failed:
        status = "Completed"
    elif successful:
        status = "Partially Completed"
    else:
        status = "Failed"

    return {
        "success": not failed,
        "status": status,
        "operation": "Move work items",
        "affected_items": work_item_ids,
        "iteration_path": iteration_path,
        "results": results,
        "summary": {
            "requested": len(work_item_ids),
            "successful": len(successful),
            "failed": len(failed),
        },
    }


# ---------------------------------------------------------------------------
# Write: hierarchy linking
# ---------------------------------------------------------------------------

@tool
def link_work_items(
    parent_id: int,
    child_id: int,
) -> dict:
    """Link an existing child work item to an existing parent.

    Uses Azure DevOps hierarchy relations.

    STATE-CHANGING:
    The graph must obtain explicit confirmation before invoking this tool.
    """

    child = get_work_item.invoke(
        {"work_item_id": child_id}
    )

    if not child.get("success"):
        return child

    current = child.get("item") or {}

    if str(current.get("parent_id")) == str(parent_id):
        return {
            "success": True,
            "status": "No-Op",
            "operation": "Link work items",
            "affected_items": [
                parent_id,
                child_id,
            ],
            "message": (
                "The requested hierarchy link already exists."
            ),
        }

    relation_url = (
        f"{BASE_URL}/_apis/wit/workItems/{parent_id}"
    )

    patch = [
        {
            "op": "add",
            "path": "/relations/-",
            "value": {
                "rel": "System.LinkTypes.Hierarchy-Reverse",
                "url": relation_url,
                "attributes": {
                    "comment": (
                        "Linked by Azure DevOps AI Agent"
                    )
                },
            },
        }
    ]

    try:
        response = SESSION.patch(
            f"{BASE_URL}/_apis/wit/workitems/{child_id}",
            params={"api-version": API_VERSION},
            headers=headers(
                "application/json-patch+json"
            ),
            json=patch,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Link work items",
            "affected_items": [
                parent_id,
                child_id,
            ],
            "errors": [
                {
                    "category": "network",
                    "message": str(exc)[:1500],
                }
            ],
        }

    if not response.ok:
        result = _error(
            "Link work items",
            response,
        )
        result["affected_items"] = [
            parent_id,
            child_id,
        ]
        return result

    # Verify the relation.
    verified = get_work_item.invoke(
        {"work_item_id": child_id}
    )

    if not verified.get("success"):
        return {
            "success": False,
            "status": "Partially Completed",
            "operation": "Link work items",
            "affected_items": [
                parent_id,
                child_id,
            ],
            "changes": [
                "Hierarchy link request accepted"
            ],
            "errors": [
                {
                    "category": "verification",
                    "message": (
                        "The hierarchy link was submitted, "
                        "but verification failed."
                    ),
                }
            ],
        }

    verified_parent = (
        verified.get("item", {})
        .get("parent_id")
    )

    if str(verified_parent) != str(parent_id):
        return {
            "success": False,
            "status": "Partially Completed",
            "operation": "Link work items",
            "affected_items": [
                parent_id,
                child_id,
            ],
            "errors": [
                {
                    "category": "verification",
                    "message": (
                        "Azure DevOps did not report the "
                        "requested hierarchy relationship "
                        "after the update."
                    ),
                }
            ],
        }

    return {
        "success": True,
        "status": "Completed",
        "operation": "Link work items",
        "affected_items": [
            parent_id,
            child_id,
        ],
        "changes": [
            "Hierarchy link created and verified"
        ],
        "evidence": {
            "parent_id": parent_id,
            "child_id": child_id,
        },
    }


# ---------------------------------------------------------------------------
# RAID
# ---------------------------------------------------------------------------

@tool
def write_raid_issue(
    title: str,
    description: str,
    priority: int = 2,
) -> dict:
    """Create a confirmed RAID Issue work item.

    STATE-CHANGING:
    The graph must obtain explicit confirmation before invoking this tool.
    """

    return add_item_to_board.invoke(
        {
            "title": title,
            "description": description,
            "work_item_type": "Issue",
            "priority": priority,
        }
    )


# ---------------------------------------------------------------------------
# Wiki publishing
# ---------------------------------------------------------------------------

@tool
def publish_wiki_report(
    path: str,
    content: str,
) -> dict:
    """Publish a requested report to an absolute Azure DevOps Wiki path.

    Missing parent pages are created by wiki.py.

    STATE-CHANGING:
    The graph must obtain explicit confirmation before invoking this tool.
    """

    if not path.strip():
        return {
            "success": False,
            "status": "Failed",
            "operation": "Publish Wiki report",
            "errors": [
                {
                    "category": "validation",
                    "message": "Wiki path cannot be empty.",
                }
            ],
        }

    if not content.strip():
        return {
            "success": False,
            "status": "Failed",
            "operation": "Publish Wiki report",
            "errors": [
                {
                    "category": "validation",
                    "message": "Wiki content cannot be empty.",
                }
            ],
        }

    from .wiki import publish_path

    try:
        result = publish_path(
            path,
            content,
        )
    except Exception as exc:
        return {
            "success": False,
            "status": "Failed",
            "operation": "Publish Wiki report",
            "errors": [
                {
                    "category": "wiki",
                    "message": str(exc)[:1500],
                }
            ],
        }

    result.setdefault(
        "operation",
        "Publish Wiki report",
    )

    result.setdefault(
        "status",
        "Completed"
        if result.get("success")
        else "Failed",
    )

    return result