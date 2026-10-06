"""Vercel FastAPI entry point for the Azure DevOps Audit Agent."""

from __future__ import annotations

from typing import Any

import base64

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from agent.config import (
    API_VERSION,
    ORG,
    PAT,
    base_url,
    configuration_error,
    get_project,
    get_team,
    org_url,
    reset_runtime_context,
    set_runtime_context,
)


app = FastAPI(
    title="Azure DevOps Audit Logger",
    version="1.0.0",
)


def _auth_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": "Basic " + base64.b64encode(f":{PAT or ''}".encode("utf-8")).decode("ascii"),
    }


def _azure_get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    error = configuration_error()
    if error:
        raise HTTPException(status_code=500, detail=error)

    try:
        response = requests.get(
            url,
            headers=_auth_headers(),
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Azure DevOps request failed: {exc}")

    if not response.ok:
        try:
            payload = response.json()
            message = payload.get("message") or response.text
        except ValueError:
            message = response.text

        raise HTTPException(
            status_code=response.status_code if response.status_code < 500 else 502,
            detail=str(message)[:1500],
        )

    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Azure DevOps returned invalid JSON.")


class AuditRequest(BaseModel):
    project: str = Field(min_length=1, max_length=200)
    team: str = Field(min_length=1, max_length=200)
    query: str = Field(
        default="Analyze the current Azure DevOps board and identify meaningful delivery risks, workload concerns, aging work, deadline pressure, dependencies, and other evidence-backed observations.",
        min_length=1,
        max_length=4000,
    )


@app.get("/api")
def api_root() -> dict[str, Any]:
    """Small routing probe used by local Vercel development and deployment checks."""
    return {"ok": True, "service": "Azure DevOps Audit Logger", "api": True}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "Azure DevOps Audit Logger",
        "configured": not bool(configuration_error()),
    }


@app.get("/api/projects")
def projects() -> dict[str, Any]:
    payload = _azure_get(
        f"{org_url()}/_apis/projects",
        params={
            "api-version": "7.1-preview.1",
            "$top": 200,
            "stateFilter": "wellFormed",
        },
    )

    values = payload.get("value", [])
    return {
        "projects": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "state": item.get("state"),
                "visibility": item.get("visibility"),
            }
            for item in values
            if item.get("name")
        ]
    }


@app.get("/api/teams")
def teams(project: str) -> dict[str, Any]:
    project = (project or "").strip()
    if not project:
        raise HTTPException(status_code=400, detail="project is required.")

    
    from urllib.parse import quote

    project_ref = quote(project, safe="")

    payload = _azure_get(
        f"{org_url()}/_apis/projects/{project_ref}/teams",
        params={
            "api-version": "7.1",
            "$top": 200,
        },
    )

    result = []

    for item in payload.get("value", []):
        if not isinstance(item, dict):
            continue

        result.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "project_id": item.get("projectId"),
                "project_name": item.get("projectName") or project,
            }
        )

    result = [
        item
        for item in result
        if item.get("id") and item.get("name")
    ]

    result.sort(
        key=lambda item: str(item.get("name") or "").casefold()
    )

    return {"teams": result}
@app.post("/api/audit")
def audit(request: AuditRequest) -> dict[str, Any]:
    """Run one audit against the project/team selected by the user."""
    project = request.project.strip()
    team = request.team.strip()

    # Validate that the selected team belongs to the selected project before
    # invoking the agent. This prevents cross-project/team configuration drift.
    available_teams = teams(project)["teams"]
    selected = next(
        (
            item
            for item in available_teams
            if str(item.get("name", "")).casefold() == team.casefold()
        ),
        None,
    )
    if not selected:
        raise HTTPException(
            status_code=400,
            detail=f"Team '{team}' was not found in project '{project}'.",
        )

    tokens = set_runtime_context(project, team)

    try:
        # Keep lightweight endpoints independent from the full agent import.
        # This makes /api/projects and /api/teams available even if an agent
        # dependency has an import/runtime issue; the audit endpoint reports
        # that issue explicitly when invoked.
        from agent.graph import graph

        state = {
            "messages": [HumanMessage(content=request.query.strip())],
            "user_query": request.query.strip(),
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
            "audit_report": "",
            "wiki_published": False,
            "final_response": "",
        }

        result = graph.invoke(state)

        if not isinstance(result, dict):
            raise HTTPException(
                status_code=500,
                detail="Agent returned an invalid state.",
            )

        return {
            "success": True,
            "project": project,
            "team": team,
            "status": result.get("audit_status") or "Completed",
            "summary": result.get("audit_summary") or result.get("final_response") or "",
            "report": result.get("audit_report") or "",
            "details": result.get("audit_details") or {},
            "wiki_published": bool(result.get("wiki_published")),
            "actions": result.get("actions_performed") or [],
            "errors": result.get("errors") or [],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {str(exc)[:1500]}",
        )
    finally:
        reset_runtime_context(tokens)
