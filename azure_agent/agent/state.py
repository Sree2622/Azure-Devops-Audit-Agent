"""Shared LangGraph state for the Azure DevOps AI Agent."""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from typing_extensions import Annotated

from langgraph.graph.message import add_messages


class PendingAction(TypedDict, total=False):
    """Exact mutation saved while waiting for user confirmation."""

    name: str
    args: dict[str, Any]


class ActionRecord(TypedDict, total=False):
    """Record of an operation performed by the agent."""

    operation_id: Optional[str]
    operation: str
    status: str
    wiki_page: Optional[str]
    affected_items: list[Any]


class ErrorRecord(TypedDict, total=False):
    """Structured execution error."""

    operation: Optional[str]
    category: Optional[str]
    error: str
    message: Optional[str]


class AgentState(TypedDict, total=False):
    """State shared by all LangGraph nodes.

    The state intentionally separates:

    1. Conversation messages
    2. Current request information
    3. Tool/action results
    4. Confirmation state
    5. Deterministic analysis output
    6. Audit/Wiki information
    7. Final user-facing response

    Mutation confirmation is represented entirely through
    ``pending_action`` and ``awaiting_confirmation``. It is never
    represented as an unfinished Gemini function call.
    """

    # ========================================================
    # Conversation
    # ========================================================

    messages: Annotated[list[Any], add_messages]

    # ========================================================
    # Current request
    # ========================================================

    user_query: str
    intent: Optional[str]

    # ========================================================
    # Agent execution
    # ========================================================

    tool_results: list[Any]
    actions_performed: list[ActionRecord]
    errors: list[ErrorRecord]

    # ========================================================
    # Confirmation
    # ========================================================

    # Exact tool name + exact arguments waiting for confirmation.
    pending_action: Optional[PendingAction]

    # True while the application is waiting for explicit user
    # confirmation of pending_action.
    awaiting_confirmation: bool

    # Optional structured clarification requested by the agent.
    pending_question: Optional[dict[str, Any]]

    # ========================================================
    # RAID
    # ========================================================

    issues_detected: list[Any]

    # Evidence discovered by adaptive, read-only investigation.
    exploratory_findings: list[Any]

    # ========================================================
    # Deterministic Sprint Health
    # ========================================================

    sprint_health: dict[str, Any]

    # ========================================================
    # Audit / Wiki
    # ========================================================

    audit_operation: Optional[str]
    audit_type: Optional[str]
    audit_status: Optional[str]
    audit_summary: Optional[str]
    audit_details: dict[str, Any]
    wiki_published: bool

    # ========================================================
    # Final response
    # ========================================================

    final_response: str