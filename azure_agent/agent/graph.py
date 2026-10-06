"""LangGraph orchestration for the Azure DevOps AI Agent.

Execution model:

    Normal request
        |
        v
      Agent
        |
        +---- read-only tool(s) ----> Agent ----+
        |                                       |
        |                                       v
        +---- proposed write ----> Confirmation
                                        |
                         +--------------+--------------+
                         |                             |
                        yes                           no
                         |                             |
                         v                             v
                 Direct execution               Direct cancellation
                         |                             |
                         v                             |
                       Audit                           |
                         |                             |
                         +--------------+--------------+
                                        |
                                        v
                                       END

Important:
- Gemini decides which read tools are needed.
- Python/LangGraph enforces mutation confirmation.
- Confirmed mutations execute the exact saved payload.
- Gemini is NEVER asked to reconstruct a confirmed function call.
- Confirmation and cancellation turns NEVER call Gemini.
- Automatic audit publication is owned by audit_node().
- publish_wiki_report is NOT exposed to Gemini.
- Audit reports are published automatically through publish_to_wiki().
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .audit import build_audit_report, get_next_operation_id
from .config import PROJECT
from .model import model
from .prompts import SYSTEM_PROMPT
from .state import AgentState
from .tools import (
    add_item_to_board,
    add_sprint,
    get_board_summary,
    get_iterations,
    get_project_teams,
    get_valid_work_item_states,
    get_work_item,
    link_work_items,
    move_work_items,
    read_azure_board,
    read_backlog,
    read_sprint_health,
    read_sprints,
    read_test_cases,
    read_work_items,
    review_board,
    investigate_board,
    update_work_item,
    write_raid_issue,
)
from .wiki import publish_to_wiki


# ============================================================
# CONFIGURATION
# ============================================================

MAX_TOOL_CALLS_PER_REQUEST = 12
MAX_HISTORY_MESSAGES = 20
MAX_AUDIT_SUMMARY_LENGTH = 5000

CONFIRMATION_WORDS = {
    "yes",
    "y",
    "confirm",
    "confirmed",
    "proceed",
    "approved",
}

CANCELLATION_WORDS = {
    "no",
    "n",
    "cancel",
    "cancelled",
    "stop",
    "abort",
}


# ============================================================
# TOOLS
# ============================================================

# IMPORTANT:
#
# publish_wiki_report is intentionally NOT included here.
#
# Audit publication is controlled by audit_node() and publish_to_wiki().
# Gemini must not independently publish the same audit again.
#
# This prevents:
#
#     audit_node() -> Wiki
#
# followed by:
#
#     Gemini -> publish_wiki_report()
#
# which previously caused duplicate Wiki publishing and unnecessary
# confirmation requests.
tools = [
    read_work_items,
    read_azure_board,
    read_backlog,
    review_board,
    investigate_board,
    add_item_to_board,
    add_sprint,
    update_work_item,
    get_valid_work_item_states,
    get_board_summary,
    read_sprints,
    read_sprint_health,
    get_project_teams,
    read_test_cases,
    move_work_items,
    write_raid_issue,
    get_iterations,
    get_work_item,
    link_work_items,
]


# Only actual Azure DevOps state-changing operations belong here.
#
# Wiki audit publication is deliberately excluded because audit_node()
# owns automatic audit publication.
WRITE_TOOLS = {
    "add_item_to_board",
    "update_work_item",
    "add_sprint",
    "move_work_items",
    "write_raid_issue",
    "link_work_items",
}


TOOL_BY_NAME = {
    tool.name: tool
    for tool in tools
}


# Gemini receives only the tools defined above.
#
# In particular, Gemini cannot call publish_wiki_report().
llm = model.bind_tools(tools)


# ============================================================
# MESSAGE HELPERS
# ============================================================

def _message_type(message: Any) -> str:
    """Safely obtain a LangChain message type."""

    return str(
        getattr(
            message,
            "type",
            "",
        )
        or ""
    ).casefold()


def _message_content(message: Any) -> str:
    """Normalize message content to plain text."""

    content = getattr(
        message,
        "content",
        "",
    )

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []

        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(
                        str(
                            item.get(
                                "text",
                                "",
                            )
                        )
                    )
            else:
                parts.append(
                    str(item)
                )

        return "\n".join(parts)

    return str(content)


def _latest_human_message(
    state: AgentState,
) -> Any | None:
    """Return the latest human message."""

    messages = state.get(
        "messages",
        []
    )

    for message in reversed(messages):
        if _message_type(message) == "human":
            return message

    return None


def _latest_human_text(
    state: AgentState,
) -> str:
    """Return the latest human message as text."""

    message = _latest_human_message(
        state
    )

    if message is None:
        return ""

    return _message_content(
        message
    ).strip()


def _is_confirmation_text(
    text: str,
) -> bool:
    """Return True for an explicit confirmation response."""

    return (
        text.strip().casefold()
        in CONFIRMATION_WORDS
    )


def _is_cancellation_text(
    text: str,
) -> bool:
    """Return True for an explicit cancellation response."""

    return (
        text.strip().casefold()
        in CANCELLATION_WORDS
    )


# ============================================================
# CONFIRMATION HELPERS
# ============================================================

def _format_pending_action(
    pending: dict[str, Any],
) -> str:
    """Create a concise confirmation message for the user."""

    name = pending.get(
        "name",
        "unknown operation",
    )

    args = pending.get(
        "args",
        {},
    )

    try:
        argument_text = json.dumps(
            args,
            default=str,
            ensure_ascii=False,
        )
    except Exception:
        argument_text = str(args)

    return (
        "⚠️ **Confirmation required**\n\n"
        "This action will modify Azure DevOps.\n\n"
        f"**Action:** `{name}`\n"
        f"**Parameters:** `{argument_text}`\n\n"
        "Reply **yes** to execute this exact action, "
        "or **cancel** to discard it."
    )


# ============================================================
# PENDING ACTION EXECUTION
# ============================================================

def execute_pending_action(
    state: AgentState,
) -> dict[str, Any]:
    """Execute the exact saved mutation without calling Gemini.

    This node is reached ONLY after an explicit confirmation.

    Critical design rule:

        user -> yes
             -> execute_pending_action
             -> Azure DevOps
             -> audit
             -> END

    Gemini is never invoked in this path.

    The tool name and arguments come exclusively from the saved
    pending_action state. Gemini is not allowed to reconstruct them.
    """

    pending = (
        state.get(
            "pending_action"
        )
        or {}
    )

    tool_name = pending.get(
        "name"
    )

    arguments = (
        pending.get(
            "args"
        )
        or {}
    )

    if not tool_name:
        return {
            "messages": [
                AIMessage(
                    content=(
                        "The confirmation could not be executed "
                        "because no pending Azure DevOps action "
                        "was available."
                    )
                )
            ],
            "pending_action": None,
            "awaiting_confirmation": False,
        }

    # Security boundary:
    # Only explicitly approved mutation tools can be executed here.
    if tool_name not in WRITE_TOOLS:
        result = {
            "success": False,
            "status": "Failed",
            "operation": "Pending action",
            "errors": [
                {
                    "category": "security",
                    "message": (
                        f"'{tool_name}' is not an approved "
                        "state-changing operation."
                    ),
                }
            ],
        }

        return {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        result,
                        default=str,
                        ensure_ascii=False,
                    ),
                    name=tool_name,
                    tool_call_id="pending-action",
                ),
                AIMessage(
                    content=(
                        "The pending action was rejected because "
                        "it is not an approved Azure DevOps mutation."
                    )
                ),
            ],
            "pending_action": None,
            "awaiting_confirmation": False,
        }

    tool_instance = TOOL_BY_NAME.get(
        tool_name
    )

    if tool_instance is None:
        result = {
            "success": False,
            "status": "Failed",
            "operation": tool_name,
            "errors": [
                {
                    "category": "configuration",
                    "message": (
                        "The saved Azure DevOps tool is no longer "
                        "available."
                    ),
                }
            ],
        }

    else:
        try:
            result = tool_instance.invoke(
                arguments
            )

            if not isinstance(
                result,
                dict,
            ):
                result = {
                    "success": True,
                    "status": "Completed",
                    "operation": tool_name,
                    "result": result,
                }

        except Exception as exc:
            error_text = str(
                exc
            )[:1500]

            result = {
                "success": False,
                "status": "Failed",
                "operation": tool_name,
                "errors": [
                    {
                        "category": "execution",
                        "message": error_text,
                    }
                ],
                "error": error_text,
            }

    success = bool(
        result.get(
            "success"
        )
    )

    status = str(
        result.get(
            "status",
            "Completed"
            if success
            else "Failed",
        )
    ).casefold()

    if status in {
        "partial",
        "partially completed",
    }:
        user_text = (
            "The Azure DevOps operation partially completed. "
            "The recorded result contains the successful and "
            "failed portions."
        )

    elif status in {
        "no-op",
        "no_change",
        "no changes required",
    }:
        user_text = (
            "No Azure DevOps change was required because "
            "the requested state was already present."
        )

    elif success:
        user_text = (
            "The confirmed Azure DevOps operation "
            "completed successfully."
        )

    else:
        error = result.get(
            "error"
        )

        if not error:
            errors = (
                result.get(
                    "errors"
                )
                or []
            )

            if errors:
                first_error = errors[0]

                if isinstance(
                    first_error,
                    dict,
                ):
                    error = first_error.get(
                        "message"
                    )
                else:
                    error = str(
                        first_error
                    )

        if error:
            user_text = (
                "The confirmed Azure DevOps operation failed: "
                f"{str(error)[:700]}"
            )
        else:
            user_text = (
                "The confirmed Azure DevOps operation did not complete."
            )

    return {
        "messages": [
            ToolMessage(
                content=json.dumps(
                    result,
                    default=str,
                    ensure_ascii=False,
                ),
                name=tool_name,
                tool_call_id="pending-action",
            ),
            AIMessage(
                content=user_text
            ),
        ],
        "pending_action": None,
        "awaiting_confirmation": False,
    }


# ============================================================
# PENDING ACTION CANCELLATION
# ============================================================

def cancel_pending_action(
    state: AgentState,
) -> dict[str, Any]:
    """Cancel the saved mutation without calling Gemini."""

    return {
        "messages": [
            AIMessage(
                content=(
                    "❌ The pending Azure DevOps change was cancelled. "
                    "No changes were made."
                )
            )
        ],
        "pending_action": None,
        "awaiting_confirmation": False,
    }


# ============================================================
# START ROUTING
# ============================================================

def route_start(
    state: AgentState,
) -> Literal[
    "execute_pending",
    "cancel_pending",
    "agent",
]:
    """Route confirmation/cancellation before Gemini.

    This is the most important protection against the Gemini
    function-call history error.

    If a confirmation is pending:

        YES  -> execute_pending
        NO   -> cancel_pending
        other -> agent

    Normally the third case asks Gemini to handle a new message,
    but when awaiting confirmation we intercept non-confirmation
    text inside agent() and do not allow Gemini to process it.
    """

    if state.get(
        "awaiting_confirmation"
    ) and state.get(
        "pending_action"
    ):
        latest_text = _latest_human_text(
            state
        )

        if _is_confirmation_text(
            latest_text
        ):
            return "execute_pending"

        if _is_cancellation_text(
            latest_text
        ):
            return "cancel_pending"

    return "agent"


# ============================================================
# AGENT NODE
# ============================================================

def _bounded_messages(
    state: AgentState,
) -> list[Any]:
    """Return bounded conversation history."""

    messages = state.get(
        "messages",
        []
    )

    return messages[
        -MAX_HISTORY_MESSAGES:
    ]


def _extract_write_calls(
    response: Any,
) -> list[dict[str, Any]]:
    """Return only tool calls that mutate Azure DevOps."""

    calls = getattr(
        response,
        "tool_calls",
        None,
    ) or []

    return [
        call
        for call in calls
        if call.get(
            "name"
        ) in WRITE_TOOLS
    ]


def _proposal_from_calls(
    calls: list[dict[str, Any]],
) -> str:
    """Format exact mutation proposals."""

    proposals: list[str] = []

    for call in calls:
        name = call.get(
            "name",
            "unknown",
        )

        args = call.get(
            "args",
            {},
        )

        try:
            serialized = json.dumps(
                args,
                default=str,
                ensure_ascii=False,
            )
        except Exception:
            serialized = str(args)

        proposals.append(
            f"`{name}` → `{serialized}`"
        )

    return "\n".join(
        proposals
    )


def agent(
    state: AgentState,
) -> dict[str, Any]:
    """Main Gemini reasoning node.

    Read operations may execute automatically.

    Mutation calls are intercepted and converted into a saved
    pending action requiring explicit confirmation.
    """

    # --------------------------------------------------------
    # HARD CONFIRMATION BOUNDARY
    # --------------------------------------------------------
    #
    # This is a second layer of protection in addition to route_start().
    #
    # Even if graph routing changes unexpectedly, a pending confirmation
    # is NEVER sent to Gemini.
    #
    if state.get(
        "awaiting_confirmation"
    ):
        latest_text = _latest_human_text(
            state
        )

        if _is_cancellation_text(
            latest_text
        ):
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "❌ The pending Azure DevOps change "
                            "was cancelled. No changes were made."
                        )
                    )
                ],
                "pending_action": None,
                "awaiting_confirmation": False,
            }

        if _is_confirmation_text(
            latest_text
        ):
            # This should normally never be reached because route_start()
            # sends confirmation directly to execute_pending.
            #
            # It is intentionally NOT an llm.invoke() call.
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "The confirmation is being handled "
                            "by the saved-action execution path."
                        )
                    )
                ]
            }

        pending = (
            state.get(
                "pending_action"
            )
            or {}
        )

        return {
            "messages": [
                AIMessage(
                    content=_format_pending_action(
                        pending
                    )
                )
            ]
        }

    # --------------------------------------------------------
    # GEMINI INPUT
    # --------------------------------------------------------

    messages = _bounded_messages(
        state
    )

    prompt_messages = [
        SystemMessage(
            content=SYSTEM_PROMPT
        )
    ] + messages

    # --------------------------------------------------------
    # GEMINI INVOCATION
    # --------------------------------------------------------

    try:
        response = llm.invoke(
            prompt_messages
        )

    except Exception as exc:
        error_text = str(
            exc
        )

        if (
            "429" in error_text
            or "RESOURCE_EXHAUSTED" in error_text
        ):
            response = AIMessage(
                content=(
                    "Gemini API quota has temporarily been exhausted. "
                    "Please retry shortly. No Azure DevOps changes were made."
                )
            )

        else:
            response = AIMessage(
                content=(
                    "The agent could not complete this request: "
                    f"{error_text[:700]}"
                )
            )

    # --------------------------------------------------------
    # INTERCEPT MUTATION CALLS
    # --------------------------------------------------------

    write_calls = _extract_write_calls(
        response
    )

    if write_calls:
        # Safest execution contract:
        # only one exact mutation is staged at a time.
        first_call = write_calls[0]

        tool_name = first_call.get(
            "name"
        )

        tool_args = (
            first_call.get(
                "args"
            )
            or {}
        )

        proposal = _proposal_from_calls(
            write_calls
        )

        if len(write_calls) > 1:
            proposal_text = (
                "Gemini proposed multiple Azure DevOps changes. "
                "Only the first exact mutation will be staged "
                "for confirmation:\n\n"
                f"{proposal}"
            )
        else:
            proposal_text = proposal

        confirmation_message = AIMessage(
            content=(
                "⚠️ **Confirmation required**\n\n"
                "This action will modify Azure DevOps.\n\n"
                f"**Proposed change:**\n{proposal_text}\n\n"
                "Reply **yes** to execute the exact saved action, "
                "or **cancel** to discard it."
            )
        )

        # Preserve the original user request for the audit layer.
        original_query = _latest_human_text(
            state
        )

        return {
            "messages": [
                confirmation_message
            ],
            "pending_action": {
                "name": tool_name,
                "args": tool_args,
                "original_query": original_query,
            },
            "awaiting_confirmation": True,
        }

    # --------------------------------------------------------
    # NORMAL READ-ONLY RESPONSE
    # --------------------------------------------------------

    return {
        "messages": [
            response
        ]
    }


# ============================================================
# TOOL ROUTING
# ============================================================

def _current_request_tool_count(
    state: AgentState,
) -> int:
    """Count tool messages belonging to the current user request."""

    messages = state.get(
        "messages",
        []
    )

    latest_human_index = -1

    for index in range(
        len(messages) - 1,
        -1,
        -1,
    ):
        if _message_type(
            messages[index]
        ) == "human":
            latest_human_index = index
            break

    if latest_human_index < 0:
        return 0

    return sum(
        1
        for message in messages[
            latest_human_index + 1:
        ]
        if _message_type(
            message
        ) == "tool"
    )


def should_continue(
    state: AgentState,
) -> Literal[
    "tools",
    "audit",
]:
    """Route Gemini tool calls or finish the current request."""

    messages = state.get(
        "messages",
        []
    )

    if not messages:
        return "audit"

    last_message = messages[-1]

    tool_calls = getattr(
        last_message,
        "tool_calls",
        None,
    ) or []

    if not tool_calls:
        return "audit"

    tool_count = _current_request_tool_count(
        state
    )

    if tool_count >= MAX_TOOL_CALLS_PER_REQUEST:
        return "audit"

    return "tools"


# ============================================================
# AUDIT HELPERS
# ============================================================

def _find_latest_user_index(
    messages: list[Any],
) -> int:
    """Find the latest human message index."""

    for index in range(
        len(messages) - 1,
        -1,
        -1,
    ):
        if _message_type(
            messages[index]
        ) == "human":
            return index

    return -1


def _parse_tool_result(
    message: Any,
) -> dict[str, Any]:
    """Parse a ToolMessage into a structured dictionary."""

    raw = getattr(
        message,
        "content",
        ""
    )

    if isinstance(
        raw,
        dict,
    ):
        return raw

    if isinstance(
        raw,
        str,
    ):
        try:
            parsed = json.loads(
                raw
            )

            if isinstance(
                parsed,
                dict,
            ):
                return parsed

            return {
                "success": True,
                "status": "Completed",
                "result": parsed,
            }

        except (
            TypeError,
            json.JSONDecodeError,
        ):
            return {
                "success": False,
                "status": "Failed",
                "error": raw[:1500],
            }

    return {
        "success": False,
        "status": "Failed",
        "error": str(raw)[:1500],
    }


def _determine_operation_status(
    results: list[dict[str, Any]],
) -> str:
    """Determine aggregate operation status from actual tool results."""

    if not results:
        return "Completed"

    statuses = [
        str(
            result.get(
                "status",
                ""
            )
        ).casefold()
        for result in results
    ]

    successes = [
        bool(
            result.get(
                "success"
            )
        )
        for result in results
    ]

    if any(
        status in {
            "partial",
            "partially completed",
        }
        for status in statuses
    ):
        return "Partially Completed"

    if any(
        success is False
        for success in successes
    ):
        if any(
            successes
        ):
            return "Partially Completed"

        return "Failed"

    if statuses and all(
        status in {
            "no-op",
            "no_change",
            "no changes required",
        }
        for status in statuses
    ):
        return "No Changes Required"

    return "Completed"


def _assistant_summary(
    messages: list[Any],
) -> str:
    """Extract the latest useful AI response."""

    for message in reversed(
        messages
    ):
        if _message_type(
            message
        ) != "ai":
            continue

        text = _message_content(
            message
        ).strip()

        if not text:
            continue

        return text

    return "Azure DevOps operation completed."


def _compact_audit_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep audit evidence compact."""

    compact: list[dict[str, Any]] = []

    for result in results:
        compact.append(
            {
                "operation": result.get(
                    "operation"
                ),
                "status": result.get(
                    "status"
                ),
                "success": result.get(
                    "success"
                ),
                "affected_items": result.get(
                    "affected_items"
                ),
                "error": result.get(
                    "error"
                ),
                "errors": result.get(
                    "errors"
                ),
            }
        )

    return compact


# ============================================================
# AUDIT OPERATION CLASSIFICATION
# ============================================================

def _classify_audit_operation(
    user_query: str,
    tool_names: list[str],
) -> tuple[str, str]:
    """Determine audit category and display name.

    User intent is preferred over individual tool names because a
    single request can involve several read operations.
    """

    query = user_query.casefold()

    # --------------------------------------------------------
    # Explicit Board Review / project analysis
    # --------------------------------------------------------

    board_terms = {
        "board review",
        "review my board",
        "review the board",
        "analyse board",
        "analyze board",
        "analyse the board",
        "analyze the board",
        "project health",
        "board health",
        "executive review",
    }

    if (
        any(
            term in query
            for term in board_terms
        )
        or "review_board" in tool_names
    ):
        return (
            "BOARD",
            "Comprehensive Board Review",
        )

    # --------------------------------------------------------
    # RAID
    # --------------------------------------------------------

    raid_terms = {
        "raid",
        "risk analysis",
        "risk review",
        "issue analysis",
        "dependency analysis",
        "assumption analysis",
    }

    if any(
        term in query
        for term in raid_terms
    ):
        return (
            "BOARD",
            "Comprehensive Board Review",
        )

    # --------------------------------------------------------
    # Sprint
    # --------------------------------------------------------

    if (
        "add_sprint" in tool_names
        or any(
            term in query
            for term in {
                "sprint health",
                "sprint readiness",
                "sprint review",
                "sprint analysis",
                "iteration health",
            }
        )
    ):
        return (
            "SPRINT",
            "Sprint Operation",
        )

    # --------------------------------------------------------
    # Work-item writes
    # --------------------------------------------------------

    if "add_item_to_board" in tool_names:
        return (
            "WORKITEM",
            "Work Item Creation",
        )

    if "update_work_item" in tool_names:
        return (
            "WORKITEM",
            "Work Item Update",
        )

    if "move_work_items" in tool_names:
        return (
            "WORKITEM",
            "Work Item Movement",
        )

    if "link_work_items" in tool_names:
        return (
            "WORKITEM",
            "Work Item Linking",
        )

    if "write_raid_issue" in tool_names:
        return (
            "WORKITEM",
            "RAID Issue Creation",
        )

    # --------------------------------------------------------
    # Read-only board/backlog analysis
    # --------------------------------------------------------

    if (
        "read_sprint_health" in tool_names
        or "read_sprints" in tool_names
    ):
        return (
            "BOARD",
            "Sprint Health Review",
        )

    if "read_backlog" in tool_names:
        return (
            "BOARD",
            "Backlog Review",
        )

    if (
        "read_azure_board" in tool_names
        or "get_board_summary" in tool_names
        or "read_work_items" in tool_names
    ):
        return (
            "BOARD",
            "Board Review",
        )

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    return (
        "WORKITEM",
        "Azure DevOps Operation",
    )


# ============================================================
# AUDIT NODE
# ============================================================

def audit_node(
    state: AgentState,
) -> dict[str, Any]:
    """Create and publish the current operation audit.

    Only messages belonging to the latest user request are considered.

    Conversation history and internal reasoning are never written as
    audit evidence.

    Automatic Wiki publication is performed here.

    Gemini does NOT publish audit reports.
    """

    messages = state.get(
        "messages",
        []
    )

    if not messages:
        return {
            "wiki_published": False
        }

    # --------------------------------------------------------
    # Current request boundary
    # --------------------------------------------------------

    latest_user_index = _find_latest_user_index(
        messages
    )

    if latest_user_index < 0:
        return {
            "wiki_published": False
        }

    current_messages = messages[
        latest_user_index + 1:
    ]

    # --------------------------------------------------------
    # Tool results for current request
    # --------------------------------------------------------

    tool_messages = [
        message
        for message in current_messages
        if _message_type(
            message
        ) == "tool"
    ]

    if not tool_messages:
        return {
            "wiki_published": False
        }

    tool_names = [
        str(
            getattr(
                message,
                "name",
                ""
            )
            or ""
        )
        for message in tool_messages
    ]

    parsed_results = [
        _parse_tool_result(
            message
        )
        for message in tool_messages
    ]

    # --------------------------------------------------------
    # Original user request
    # --------------------------------------------------------
    #
    # For normal requests this is the latest human message.
    #
    # For confirmed mutations the latest human message is "yes".
    # In that case, recover the original request from pending_action.
    #
    pending = (
        state.get(
            "pending_action"
        )
        or {}
    )

    original_pending_query = pending.get(
        "original_query"
    )

    user_message = messages[
        latest_user_index
    ]

    user_query = _message_content(
        user_message
    )

    if (
        _is_confirmation_text(
            user_query
        )
        and original_pending_query
    ):
        user_query = str(
            original_pending_query
        )

    if not user_query:
        user_query = "Azure DevOps operation"

    # --------------------------------------------------------
    # Operation classification
    # --------------------------------------------------------

    operation_type, operation_name = (
        _classify_audit_operation(
            user_query,
            tool_names,
        )
    )

    operation_status = _determine_operation_status(
        parsed_results
    )

    # --------------------------------------------------------
    # Final assistant summary
    # --------------------------------------------------------

    summary = _assistant_summary(
        current_messages
    )

    if len(summary) > MAX_AUDIT_SUMMARY_LENGTH:
        summary = (
            summary[
                :MAX_AUDIT_SUMMARY_LENGTH
            ]
            + "\n\n[Summary truncated]"
        )

    # --------------------------------------------------------
    # Unique operation ID
    # --------------------------------------------------------

    operation_id = get_next_operation_id(
        operation_type
    )

    # --------------------------------------------------------
    # Extract deterministic Board Review / Sprint Health evidence
    # --------------------------------------------------------

    board_review_evidence = None
    sprint_health_evidence = None
    adaptive_evidence: list[dict[str, Any]] = []

    for result in parsed_results:
        if not isinstance(
            result,
            dict,
        ):
            continue

        if (
            result.get(
                "evidence"
            )
            and result.get(
                "operation"
            ) == "Board Review"
        ):
            board_review_evidence = result.get(
                "evidence"
            )

        if result.get(
            "sprint_health"
        ):
            sprint_health_evidence = result.get(
                "sprint_health"
            )

        if result.get("operation") == "Adaptive board investigation" and result.get("success"):
            adaptive_evidence.append({
                "focus": result.get("focus", "all"),
                "finding_count": result.get("finding_count", 0),
                "findings": result.get("findings", []),
                "evidence_policy": result.get("evidence_policy"),
            })

    # Some tools may wrap the Board Review result differently.
    if board_review_evidence is None:
        for result in parsed_results:
            if (
                isinstance(
                    result,
                    dict,
                )
                and isinstance(
                    result.get(
                        "evidence"
                    ),
                    dict,
                )
                and (
                    "Board Review"
                    in result.get(
                        "evidence",
                        {},
                    )
                )
            ):
                board_review_evidence = result[
                    "evidence"
                ]

    # --------------------------------------------------------
    # Audit details
    # --------------------------------------------------------

    details: dict[str, Any] = {
        "Project": PROJECT or "Unknown",
        "Operation Type": operation_type,
        "User Request": user_query,
        "Tools Executed": tool_names,
        "Tool Outcome": _compact_audit_results(
            parsed_results
        ),
    }

    if board_review_evidence is not None:
        details[
            "Board Review"
        ] = board_review_evidence

    if sprint_health_evidence is not None:
        details[
            "Sprint Health"
        ] = sprint_health_evidence

    if adaptive_evidence:
        details[
            "Adaptive Investigation"
        ] = adaptive_evidence

    # --------------------------------------------------------
    # Build audit Markdown
    # --------------------------------------------------------

    try:
        report = build_audit_report(
            operation_id=operation_id,
            operation=operation_name,
            status=operation_status,
            summary=summary,
            details=details,
        )

    except Exception as exc:
        return {
            "wiki_published": False,
            "audit_operation": operation_name,
            "audit_type": operation_type,
            "audit_status": "Audit Generation Failed",
            "errors": [
                {
                    "operation": operation_name,
                    "error": (
                        "Could not build the audit report: "
                        f"{str(exc)[:1000]}"
                    ),
                }
            ],
        }

    # --------------------------------------------------------
    # Wiki category
    # --------------------------------------------------------

    category_map = {
        "BOARD": "Board Reviews",
        "SPRINT": "Sprint Operations",
        "WORKITEM": "Work Item Operations",
    }

    category = category_map.get(
        operation_type,
        "Work Item Operations",
    )

    # --------------------------------------------------------
    # Automatic Wiki publication
    # --------------------------------------------------------
    #
    # This is the ONLY audit publication path.
    #
    # Gemini does not have a publish_wiki_report tool anymore.
    #
    # Therefore:
    #
    #     audit_node()
    #          |
    #          +--> publish_to_wiki()
    #
    # happens exactly once.
    #

    try:
        wiki_result = publish_to_wiki(
            operation_id=operation_id,
            content=report,
            category=category,
        )

    except Exception as exc:
        wiki_result = {
            "success": False,
            "status": "Failed",
            "error": str(exc)[:1500],
        }

    if wiki_result.get(
        "success"
    ):
        page_path = wiki_result.get(
            "page_path"
        )

        print(
            f"\n[AUDIT] {operation_id} published to Wiki"
        )

        if page_path:
            print(
                f"[AUDIT] Wiki page: {page_path}"
            )

        return {
            "wiki_published": True,
            "audit_operation": operation_name,
            "audit_type": operation_type,
            "audit_status": operation_status,
            "audit_summary": summary,
            "audit_details": details,
            "actions_performed": [
                {
                    "operation_id": operation_id,
                    "operation": operation_name,
                    "wiki_page": page_path,
                }
            ],
        }

    # --------------------------------------------------------
    # Wiki publishing failure
    # --------------------------------------------------------

    error_message = wiki_result.get(
        "error"
    )

    if not error_message:
        errors = (
            wiki_result.get(
                "errors"
            )
            or []
        )

        if errors:
            first_error = errors[0]

            if isinstance(
                first_error,
                dict,
            ):
                error_message = first_error.get(
                    "message"
                )
            else:
                error_message = str(
                    first_error
                )

    error_message = (
        error_message
        or "Unknown Wiki publishing error"
    )

    print(
        f"\n[AUDIT] Wiki publishing failed: "
        f"{error_message}"
    )

    return {
        "wiki_published": False,
        "audit_operation": operation_name,
        "audit_type": operation_type,
        "audit_status": "Wiki Publishing Failed",
        "audit_summary": summary,
        "audit_details": details,
        "errors": [
            {
                "operation": operation_name,
                "error": error_message,
            }
        ],
    }


# ============================================================
# BUILD LANGGRAPH
# ============================================================

builder = StateGraph(
    AgentState
)


# ============================================================
# NODES
# ============================================================

builder.add_node(
    "agent",
    agent,
)

builder.add_node(
    "tools",
    ToolNode(
        tools,
        handle_tool_errors=True,
    ),
)

builder.add_node(
    "execute_pending",
    execute_pending_action,
)

builder.add_node(
    "cancel_pending",
    cancel_pending_action,
)

builder.add_node(
    "audit",
    audit_node,
)


# ============================================================
# START ROUTING
# ============================================================

builder.add_conditional_edges(
    START,
    route_start,
    {
        "execute_pending": "execute_pending",
        "cancel_pending": "cancel_pending",
        "agent": "agent",
    },
)


# ============================================================
# CONFIRMED ACTION
# ============================================================
#
# CRITICAL:
#
# execute_pending -> audit -> END
#
# There is NO route back to Gemini.
#
# Therefore the following sequence cannot happen anymore:
#
#     yes
#      ↓
#     Gemini
#      ↓
#     old function-call history
#      ↓
#     400 INVALID_ARGUMENT
#

builder.add_edge(
    "execute_pending",
    "audit",
)


# ============================================================
# CANCELLED ACTION
# ============================================================
#
# Cancellation does not touch Azure DevOps and does not call Gemini.

builder.add_edge(
    "cancel_pending",
    END,
)


# ============================================================
# AGENT ROUTING
# ============================================================

builder.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        "audit": "audit",
    },
)


# ============================================================
# READ TOOL LOOP
# ============================================================

builder.add_edge(
    "tools",
    "agent",
)


# ============================================================
# AUDIT -> END
# ============================================================

builder.add_edge(
    "audit",
    END,
)


# ============================================================
# COMPILE
# ============================================================

graph = builder.compile()
