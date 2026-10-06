"""CLI entry point for the Azure DevOps AI Agent."""

from __future__ import annotations

from typing import Any

from .graph import graph
from .config import ORG, PAT, PROJECT, TEAM, GOOGLE_API_KEY


# ============================================================
# CONFIGURATION
# ============================================================

MAX_SESSION_MESSAGES = 20

EXIT_COMMANDS = {
    "exit",
    "quit",
}



# ============================================================
# CONFIGURATION VALIDATION
# ============================================================

def validate_configuration() -> list[str]:
    """Return missing required configuration names.

    Secret values are never printed.
    """

    required = {
        "AZURE_DEVOPS_ORG": ORG,
        "AZURE_DEVOPS_PROJECT": PROJECT,
        "AZURE_DEVOPS_PAT": PAT,
        "AZURE_DEVOPS_TEAM": TEAM,
        "GOOGLE_API_KEY": GOOGLE_API_KEY,
    }

    return [
        name
        for name, value in required.items()
        if not value
    ]


# ============================================================
# MESSAGE HELPERS
# ============================================================

def _message_content(
    message: Any,
) -> str:
    """Convert a LangChain message content value to text."""

    content = getattr(
        message,
        "content",
        "",
    )

    if isinstance(
        content,
        str,
    ):
        return content

    if isinstance(
        content,
        list,
    ):
        parts: list[str] = []

        for item in content:
            if isinstance(
                item,
                dict,
            ):
                if item.get(
                    "type"
                ) == "text":
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

    if content is None:
        return ""

    return str(
        content
    )


def _message_type(
    message: Any,
) -> str:
    return str(
        getattr(
            message,
            "type",
            "",
        )
        or ""
    ).casefold()


def _display_message(
    state: dict[str, Any],
) -> str:
    """Select the latest useful user-facing response."""

    messages = state.get(
        "messages",
        []
    )

    if not messages:
        return (
            "The agent completed the request "
            "without returning a message."
        )

    # Prefer the latest AI message. This prevents a raw ToolMessage
    # from being displayed if the audit node did not add an AI response.
    for message in reversed(
        messages
    ):
        if _message_type(
            message
        ) == "ai":
            content = _message_content(
                message
            ).strip()

            if content:
                return content

    # Fallback to the latest message.
    return _message_content(
        messages[-1]
    ).strip() or (
        "The agent completed the request."
    )


# ============================================================
# STATE HELPERS
# ============================================================

def _initial_state() -> dict[str, Any]:
    """Create a clean application state for a new CLI session."""

    return {
        "messages": [],
        "user_query": "",
        "intent": None,
        "tool_results": [],
        "actions_performed": [],
        "errors": [],
        "pending_action": None,
        "awaiting_confirmation": False,
        "pending_question": None,
        "issues_detected": [],
        "exploratory_findings": [],
        "sprint_health": {},
        "audit_operation": None,
        "audit_type": None,
        "audit_status": None,
        "audit_summary": None,
        "audit_details": {},
        "wiki_published": False,
        "final_response": "",
    }


def _compact_state(
    state: dict[str, Any],
) -> dict[str, Any]:
    """Bound conversation history while retaining application state."""

    messages = state.get(
        "messages",
        []
    )

    state["messages"] = messages[
        -MAX_SESSION_MESSAGES:
    ]

    return state


# ============================================================
# STATUS DISPLAY
# ============================================================

def _print_operation_status(
    state: dict[str, Any],
) -> None:
    """Print concise execution/audit status when available."""

    audit_status = state.get(
        "audit_status"
    )

    wiki_published = state.get(
        "wiki_published"
    )

    actions = state.get(
        "actions_performed"
    ) or []

    if audit_status:
        print(
            f"\n[AUDIT] Status: {audit_status}"
        )

    if wiki_published:
        print(
            "[AUDIT] Wiki: Published"
        )

    if actions:
        latest_action = actions[-1]

        operation_id = latest_action.get(
            "operation_id"
        )

        wiki_page = latest_action.get(
            "wiki_page"
        )

        if operation_id:
            print(
                f"[AUDIT] Operation ID: {operation_id}"
            )

        if wiki_page:
            print(
                f"[AUDIT] Wiki page: {wiki_page}"
            )


# ============================================================
# MAIN CLI
# ============================================================

def main() -> None:
    """Run the interactive Azure DevOps AI Agent."""

    print("=" * 50)
    print("Azure DevOps AI Agent")
    print("=" * 50)

    missing = validate_configuration()

    if missing:
        print(
            "Configuration error: missing "
            + ", ".join(missing)
        )
        return

    print(
        f"Project: {PROJECT}"
    )

    print(
        "Type 'exit' or 'quit' to close."
    )

    print(
        "For pending changes, reply 'yes' to confirm "
        "or 'cancel' to discard."
    )

    session_state = _initial_state()

    while True:
        try:
            user_input = input(
                "\nYou: "
            ).strip()

            # ------------------------------------------------
            # Ignore accidental empty input
            # ------------------------------------------------

            if not user_input:
                continue

            command = user_input.casefold()

            # ------------------------------------------------
            # Exit
            # ------------------------------------------------

            if command in EXIT_COMMANDS:
                print(
                    "Goodbye!"
                )
                break

            # ------------------------------------------------
            # Add user message
            # ------------------------------------------------

            session_state.setdefault(
                "messages",
                []
            ).append(
                {
                    "role": "user",
                    "content": user_input,
                }
            )

            # Keep state bounded before invoking the graph.
            session_state = _compact_state(
                session_state
            )

            # ------------------------------------------------
            # Execute graph
            # ------------------------------------------------

            result = graph.invoke(
                session_state
            )

            if not isinstance(
                result,
                dict,
            ):
                print(
                    "\nAgent Error: graph returned "
                    "an invalid state."
                )
                continue

            # ------------------------------------------------
            # Preserve returned application state
            # ------------------------------------------------

            session_state = result

            session_state = _compact_state(
                session_state
            )

            # ------------------------------------------------
            # Store final response
            # ------------------------------------------------

            final_response = _display_message(
                session_state
            )

            session_state[
                "final_response"
            ] = final_response

            # ------------------------------------------------
            # Display response
            # ------------------------------------------------

            print(
                "\nAgent:"
            )
            print(
                "-" * 50
            )
            print(
                final_response
            )
            print(
                "-" * 50
            )

            # ------------------------------------------------
            # Display audit information
            # ------------------------------------------------

            _print_operation_status(
                session_state
            )

        except KeyboardInterrupt:
            print(
                "\n\nGoodbye!"
            )
            break

        except EOFError:
            print(
                "\n\nGoodbye!"
            )
            break

        except Exception as exc:
            # Do not terminate the entire interactive session because
            # one request failed.
            print(
                "\nAgent Error: "
                f"{str(exc)[:1000]}"
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()