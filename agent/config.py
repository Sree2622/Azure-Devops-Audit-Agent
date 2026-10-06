"""Runtime and environment configuration for the Azure DevOps AI Agent.

Azure DevOps project/team are request-scoped values. They are deliberately not
stored in environment variables so a web user can choose the target project
and team at runtime.

Only organization credentials and model configuration remain in the environment.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

ORG = (os.getenv("AZURE_DEVOPS_ORG") or "").strip()
PAT = (os.getenv("AZURE_DEVOPS_PAT") or "").strip()
GOOGLE_API_KEY = (os.getenv("GOOGLE_API_KEY") or "").strip()

API_VERSION = "7.1"
REQUEST_TIMEOUT = int(os.getenv("AZURE_DEVOPS_REQUEST_TIMEOUT", "30"))

_project_var: ContextVar[str] = ContextVar("azure_project", default="")
_team_var: ContextVar[str] = ContextVar("azure_team", default="")


def set_runtime_context(project: str, team: str):
    """Set the Azure DevOps project/team for the current request context."""
    project = (project or "").strip()
    team = (team or "").strip()

    if not project:
        raise ValueError("Azure DevOps project is required.")
    if not team:
        raise ValueError("Azure DevOps team is required.")

    return (
        _project_var.set(project),
        _team_var.set(team),
    )


def reset_runtime_context(tokens) -> None:
    """Restore the previous project/team context."""
    project_token, team_token = tokens
    _project_var.reset(project_token)
    _team_var.reset(team_token)


def get_project() -> str:
    return _project_var.get()


def get_team() -> str:
    return _team_var.get()


def org_url() -> str:
    return f"https://dev.azure.com/{quote(ORG, safe='')}"


def base_url() -> str:
    project = get_project()
    if not project:
        return org_url()
    return f"{org_url()}/{quote(project, safe='')}"


def configuration_error() -> str | None:
    """Return a credential/configuration error, if any."""
    if not ORG:
        return "AZURE_DEVOPS_ORG is not configured."
    if not PAT:
        return "AZURE_DEVOPS_PAT is not configured."
    if not GOOGLE_API_KEY:
        return "GOOGLE_API_KEY is not configured."
    return None


def runtime_configuration_error() -> str | None:
    """Return an error when a request has no selected project/team."""
    if not get_project():
        return "No Azure DevOps project has been selected."
    if not get_team():
        return "No Azure DevOps team has been selected."
    return None
