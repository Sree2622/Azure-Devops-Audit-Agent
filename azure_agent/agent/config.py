"""Shared Azure DevOps configuration for the agent.

All Azure DevOps modules import their connection settings from this module so
there is one configuration source and one API-version definition.
"""

from __future__ import annotations

import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

ORG = (os.getenv("AZURE_DEVOPS_ORG") or "").strip()
PROJECT = (os.getenv("AZURE_DEVOPS_PROJECT") or "").strip()
PAT = (os.getenv("AZURE_DEVOPS_PAT") or "").strip()
TEAM = (os.getenv("AZURE_DEVOPS_TEAM") or "").strip()
GOOGLE_API_KEY = (os.getenv("GOOGLE_API_KEY") or "").strip()

API_VERSION = "7.1"
REQUEST_TIMEOUT = 30

BASE_URL = f"https://dev.azure.com/{quote(ORG, safe='')}/{quote(PROJECT, safe='')}"
ORG_URL = f"https://dev.azure.com/{quote(ORG, safe='')}"


def configuration_error() -> str | None:
    """Return the first missing required Azure DevOps setting, if any."""
    if not ORG:
        return "AZURE_DEVOPS_ORG is not configured."
    if not PROJECT:
        return "AZURE_DEVOPS_PROJECT is not configured."
    if not PAT:
        return "AZURE_DEVOPS_PAT is not configured."
    return None
