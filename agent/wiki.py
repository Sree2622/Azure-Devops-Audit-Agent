"""Azure DevOps Wiki publishing utilities.

Reliable Azure DevOps Wiki publishing for the AI Audit Agent.

Publishing hierarchy:

    /Agent Audit/
        /Board Reviews/
            /BOARD-XXXX
        /Sprint Operations/
            /SPRINT-XXXX
        /Work Item Operations/
            /WORKITEM-XXXX

The implementation supports both page creation and page updates.

IMPORTANT:
Azure DevOps requires the current page ETag in the If-Match header
when updating an existing Wiki page.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import requests
from .config import API_VERSION, PAT, REQUEST_TIMEOUT, base_url, get_project, org_url, configuration_error

AUDIT_ROOT = "/Agent Audit"

AUDIT_CATEGORIES = {
    "Board Reviews": (
        "Executive Board Review reports generated "
        "by the Azure DevOps AI Agent."
    ),
    "Sprint Operations": (
        "Sprint and iteration operation reports generated "
        "by the Azure DevOps AI Agent."
    ),
    "Work Item Operations": (
        "Technical work-item operation audit reports generated "
        "by the Azure DevOps AI Agent."
    ),
}


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()


# ============================================================
# CONFIGURATION VALIDATION
# ============================================================

def _configuration_error() -> str | None:
    """Return a configuration error, if the shared Azure settings are incomplete."""
    return configuration_error()


# ============================================================
# AUTHENTICATION
# ============================================================

def headers(
    *,
    if_match: str | None = None,
) -> dict[str, str]:
    """Return Azure DevOps REST API headers."""

    result = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": requests.auth._basic_auth_str(
            "",
            PAT,
        ),
    }

    if if_match:
        result["If-Match"] = if_match

    return result


# ============================================================
# URL HELPERS
# ============================================================

def _encode_query_path(path: str) -> str:
    """Encode Wiki path for the path query parameter."""

    return quote(
        path,
        safe="/",
    )


def _wiki_list_url() -> str:
    return (
        f"{base_url()}/_apis/wiki/wikis"
        f"?api-version={API_VERSION}"
    )



def _wiki_pages_url(
    wiki_id: str,
    path: str,
    *,
    include_content: bool = False,
) -> str:
    """Build Wiki page API URL."""

    encoded_path = _encode_query_path(path)

    return (
        f"{base_url()}/_apis/wiki/wikis/"
        f"{quote(str(wiki_id), safe='')}/pages"
        f"?path={encoded_path}"
        f"&includeContent="
        f"{str(include_content).lower()}"
        f"&api-version={API_VERSION}"
    )


# ============================================================
# RESPONSE HELPERS
# ============================================================

def _response_message(
    response: requests.Response,
) -> str:
    """Extract the most useful Azure DevOps error message."""

    try:
        data = response.json()

        if isinstance(data, dict):

            message = data.get("message")

            if message:
                return str(message)

            error_code = data.get("typeKey")

            if error_code:
                return str(error_code)

            inner = data.get("innerException")

            if isinstance(inner, dict):

                inner_message = inner.get("message")

                if inner_message:
                    return str(inner_message)

    except (ValueError, TypeError):
        pass

    text = (response.text or "").strip()

    if text:
        return text[:4000]

    return f"HTTP {response.status_code}"


def _extract_etag(
    response: requests.Response,
) -> str | None:
    """Extract ETag from response headers or JSON body."""

    etag = (
        response.headers.get("ETag")
        or response.headers.get("etag")
    )

    if etag:
        return etag

    try:
        data = response.json()

        if isinstance(data, dict):

            value = (
                data.get("eTag")
                or data.get("etag")
            )

            if value:
                return str(value)

    except (ValueError, TypeError):
        pass

    return None


def _diagnostic_response(
    response: requests.Response,
) -> dict[str, Any]:
    """Return structured Azure error diagnostics."""

    return {
        "status_code": response.status_code,
        "reason": response.reason,
        "url": response.url,
        "error": _response_message(response),
    }


def _looks_like_existing_page(
    response: requests.Response,
) -> bool:
    """Determine whether Azure says the page already exists."""

    message = _response_message(response).casefold()

    markers = {
        "already exists",
        "alreadyexists",
        "wikipagealreadyexistsexception",
        "page already exists",
        "pageexists",
    }

    return any(
        marker in message
        for marker in markers
    )


def _looks_like_version_conflict(
    response: requests.Response,
) -> bool:
    """Detect stale/missing page-version conflicts."""

    message = _response_message(response).casefold()

    markers = {
        "version",
        "etag",
        "if-match",
        "precondition",
        "conflict",
        "modified",
    }

    return (
        response.status_code in {400, 409, 412}
        and any(
            marker in message
            for marker in markers
        )
    )


# ============================================================
# WIKI DISCOVERY
# ============================================================

def get_wiki_id() -> str:
    """Find the project Wiki and return its ID."""

    configuration_error = _configuration_error()

    if configuration_error:
        raise RuntimeError(
            configuration_error
        )

    try:
        response = SESSION.get(
            _wiki_list_url(),
            headers=headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Wiki discovery request failed: {exc}"
        ) from exc

    if response.status_code != 200:
        diagnostic = _diagnostic_response(response)

        raise RuntimeError(
            "Unable to list Azure DevOps Wikis. "
            f"HTTP {diagnostic['status_code']}: "
            f"{diagnostic['error']}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Azure DevOps returned invalid JSON while "
            "listing Wikis."
        ) from exc

    wikis = data.get("value", [])

    if not isinstance(wikis, list):
        raise RuntimeError(
            "Azure DevOps Wiki response has an invalid "
            "'value' structure."
        )

    if not wikis:
        raise RuntimeError(
            f"No Azure DevOps Wiki was found for "
            f"project '{get_project()}'."
        )

    preferred_name = f"{get_project()}.wiki"

    # --------------------------------------------------------
    # Prefer project Wiki
    # --------------------------------------------------------

    for wiki in wikis:

        if not isinstance(wiki, dict):
            continue

        name = str(
            wiki.get("name") or ""
        ).strip()

        wiki_type = str(
            wiki.get("type") or ""
        ).strip()

        if (
            name.casefold()
            == preferred_name.casefold()
            and wiki.get("id")
        ):
            return str(wiki["id"])

    # --------------------------------------------------------
    # Prefer projectWiki over codeWiki
    # --------------------------------------------------------

    for wiki in wikis:

        if not isinstance(wiki, dict):
            continue

        if (
            wiki.get("type") == "projectWiki"
            and wiki.get("id")
        ):
            return str(wiki["id"])

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    for wiki in wikis:

        if not isinstance(wiki, dict):
            continue

        if wiki.get("id"):
            return str(wiki["id"])

    raise RuntimeError(
        "Azure DevOps returned Wiki entries without IDs."
    )


# ============================================================
# PAGE LOOKUP
# ============================================================

def get_page(
    wiki_id: str,
    path: str,
) -> dict[str, Any]:
    """Retrieve Wiki page metadata."""

    try:
        response = SESSION.get(
            _wiki_pages_url(
                wiki_id,
                path,
                include_content=False,
            ),
            headers=headers(),
            timeout=REQUEST_TIMEOUT,
        )

    except requests.RequestException as exc:
        return {
            "success": False,
            "exists": False,
            "status_code": None,
            "error": str(exc),
        }

    if response.status_code == 200:

        etag = _extract_etag(response)

        try:
            data = response.json()
        except ValueError:
            data = {}

        return {
            "success": True,
            "exists": True,
            "status_code": 200,
            "etag": etag,
            "data": data,
        }

    if response.status_code == 404:

        return {
            "success": True,
            "exists": False,
            "status_code": 404,
        }

    return {
        "success": False,
        "exists": False,
        **_diagnostic_response(response),
    }



# ============================================================
# PATH VALIDATION
# ============================================================

def _normalize_path(
    path: str,
) -> str:
    """Normalize an absolute Wiki path."""

    if not isinstance(path, str):
        raise ValueError(
            "Wiki path must be a string."
        )

    path = path.strip()

    if not path:
        raise ValueError(
            "Wiki path cannot be empty."
        )

    if not path.startswith("/"):
        raise ValueError(
            "Wiki path must be absolute."
        )

    parts = [
        part.strip()
        for part in path.split("/")
        if part.strip()
    ]

    if not parts:
        raise ValueError(
            "Wiki path must contain a page name."
        )

    # Prevent accidental dot-path traversal.
    if any(
        part in {".", ".."}
        for part in parts
    ):
        raise ValueError(
            "Wiki path contains an invalid path component."
        )

    return "/" + "/".join(parts)


# ============================================================
# OPERATION ID VALIDATION
# ============================================================

def _validate_operation_id(
    operation_id: str,
) -> bool:
    """Validate generated audit operation IDs."""

    if not isinstance(
        operation_id,
        str,
    ):
        return False

    value = operation_id.strip()

    return bool(
        re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]*",
            value,
        )
    )


# ============================================================
# PAGE CREATION / UPDATE
# ============================================================

def _create_or_update_page(
    wiki_id: str,
    path: str,
    content: str,
    *,
    retries: int = 1,
) -> dict[str, Any]:
    """Create a page or safely update an existing page."""

    lookup = get_page(
        wiki_id,
        path,
    )

    if not lookup.get("success"):
        return {
            "success": False,
            "path": path,
            "status": "Failed",
            "error": (
                "Unable to determine whether Wiki page exists: "
                f"{lookup.get('error')}"
            ),
            "status_code": lookup.get("status_code"),
        }

    # ========================================================
    # CREATE
    # ========================================================

    if not lookup.get("exists"):

        try:
            response = SESSION.put(
                _wiki_pages_url(
                    wiki_id,
                    path,
                ),
                headers=headers(),
                json={
                    "content": content,
                },
                timeout=REQUEST_TIMEOUT,
            )

        except requests.RequestException as exc:
            return {
                "success": False,
                "path": path,
                "status": "Failed",
                "error": str(exc),
            }

        if response.status_code == 201:

            return {
                "success": True,
                "path": path,
                "status": "Created",
                "created": True,
                "updated": False,
                "etag": _extract_etag(response),
            }

        # Race condition:
        # another process created it after our GET.
        if response.status_code in {400, 409} and (
            _looks_like_existing_page(response)
        ):
            if retries > 0:
                return _create_or_update_page(
                    wiki_id,
                    path,
                    content,
                    retries=retries - 1,
                )

        return {
            "success": False,
            "path": path,
            "status": "Failed",
            **_diagnostic_response(response),
        }

    # ========================================================
    # UPDATE
    # ========================================================

    etag = lookup.get("etag")

    if not etag:
        return {
            "success": False,
            "path": path,
            "status": "Failed",
            "error": (
                "Wiki page exists, but Azure DevOps did not "
                "return an ETag. Cannot safely update the page."
            ),
        }

    try:
        response = SESSION.put(
            _wiki_pages_url(
                wiki_id,
                path,
            ),
            headers=headers(
                if_match=str(etag)
            ),
            json={
                "content": content,
            },
            timeout=REQUEST_TIMEOUT,
        )

    except requests.RequestException as exc:
        return {
            "success": False,
            "path": path,
            "status": "Failed",
            "error": str(exc),
        }

    if response.status_code == 200:

        return {
            "success": True,
            "path": path,
            "status": "Updated",
            "created": False,
            "updated": True,
            "etag": _extract_etag(response),
        }

    # --------------------------------------------------------
    # Stale ETag
    # --------------------------------------------------------

    if (
        _looks_like_version_conflict(response)
        and retries > 0
    ):
        return _create_or_update_page(
            wiki_id,
            path,
            content,
            retries=retries - 1,
        )

    return {
        "success": False,
        "path": path,
        "status": "Failed",
        **_diagnostic_response(response),
    }


# ============================================================
# ENSURE PAGE
# ============================================================

def ensure_page(
    wiki_id: str,
    path: str,
    title: str | None = None,
    body: str = "",
) -> dict[str, Any]:
    """Ensure that a Wiki page exists.

    Existing pages are intentionally left unchanged.
    """

    try:
        normalized_path = _normalize_path(path)
    except ValueError as exc:
        return {
            "success": False,
            "path": path,
            "error": str(exc),
        }

    lookup = get_page(
        wiki_id,
        normalized_path,
    )

    if not lookup.get("success"):
        return {
            "success": False,
            "path": normalized_path,
            "error": lookup.get("error"),
            "status_code": lookup.get("status_code"),
        }

    if lookup.get("exists"):

        return {
            "success": True,
            "path": normalized_path,
            "already_exists": True,
            "created": False,
            "etag": lookup.get("etag"),
        }

    page_title = (
        title
        or normalized_path.rstrip("/").split("/")[-1]
        or "Wiki Page"
    )

    page_content = body.strip()

    if page_content:
        content = (
            f"# {page_title}\n\n"
            f"{page_content}"
        )
    else:
        content = f"# {page_title}\n"

    result = _create_or_update_page(
        wiki_id,
        normalized_path,
        content,
    )

    if result.get("success"):

        result["already_exists"] = False

    return result


# ============================================================
# GENERIC PATH PUBLISHING
# ============================================================

def publish_path(
    path: str,
    content: str,
) -> dict[str, Any]:
    """Publish content to any absolute Wiki path."""

    configuration_error = _configuration_error()

    if configuration_error:
        return {
            "success": False,
            "status": "Failed",
            "error": configuration_error,
        }

    try:
        normalized_path = _normalize_path(path)
    except ValueError as exc:
        return {
            "success": False,
            "status": "Failed",
            "error": str(exc),
        }

    if content is None:
        content = ""

    if not isinstance(content, str):
        content = str(content)

    try:
        wiki_id = get_wiki_id()

        parts = [
            part
            for part in normalized_path.split("/")
            if part
        ]

        # ----------------------------------------------------
        # Ensure ancestors
        # ----------------------------------------------------

        for index in range(
            1,
            len(parts),
        ):

            ancestor = (
                "/"
                + "/".join(
                    parts[:index]
                )
            )

            ancestor_result = ensure_page(
                wiki_id=wiki_id,
                path=ancestor,
                title=parts[index - 1],
                body="Wiki navigation page.",
            )

            if not ancestor_result.get("success"):

                return {
                    "success": False,
                    "status": "Failed",
                    "path": normalized_path,
                    "wiki_id": wiki_id,
                    "error": (
                        "Could not create or locate "
                        f"{ancestor}: "
                        f"{ancestor_result.get('error')}"
                    ),
                }

        # ----------------------------------------------------
        # Create/update target
        # ----------------------------------------------------

        result = _create_or_update_page(
            wiki_id,
            normalized_path,
            content,
        )

        result.update(
            {
                "page_path": normalized_path,
                "wiki_id": wiki_id,
            }
        )

        return result

    except requests.RequestException as exc:

        return {
            "success": False,
            "status": "Failed",
            "path": normalized_path,
            "error": str(exc),
        }

    except Exception as exc:

        return {
            "success": False,
            "status": "Failed",
            "path": normalized_path,
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
        }


# ============================================================
# STANDARD AUDIT PUBLISHING
# ============================================================

def publish_to_wiki(
    operation_id: str,
    content: str,
    category: str = "General",
) -> dict[str, Any]:
    """Publish an audit report under /Agent Audit."""

    configuration_error = _configuration_error()

    if configuration_error:
        return {
            "success": False,
            "status": "Failed",
            "error": configuration_error,
        }

    if not operation_id:
        return {
            "success": False,
            "status": "Failed",
            "error": "operation_id is required.",
        }

    operation_id = str(
        operation_id
    ).strip()

    if not _validate_operation_id(
        operation_id
    ):
        return {
            "success": False,
            "status": "Failed",
            "error": (
                "Invalid operation_id. "
                "Expected characters such as BOARD-0001."
            ),
        }

    if content is None:
        content = ""

    if not isinstance(content, str):
        content = str(content)

    category = (
        str(category).strip()
        or "General"
    )

    category = category.strip("/")

    if not category:
        category = "General"

    if "/" in category:
        return {
            "success": False,
            "status": "Failed",
            "error": (
                "Wiki audit category must be a single "
                "path component."
            ),
        }

    try:
        wiki_id = get_wiki_id()

        # ----------------------------------------------------
        # Root
        # ----------------------------------------------------

        root_result = ensure_page(
            wiki_id=wiki_id,
            path=AUDIT_ROOT,
            title="Agent Audit",
            body=(
                "Audit reports generated by the "
                "Azure DevOps AI Agent."
            ),
        )

        if not root_result.get("success"):

            return {
                "success": False,
                "status": "Failed",
                "error": (
                    "Could not create or locate "
                    f"{AUDIT_ROOT}: "
                    f"{root_result.get('error')}"
                ),
            }

        # ----------------------------------------------------
        # Category
        # ----------------------------------------------------

        category_path = (
            f"{AUDIT_ROOT}/{category}"
        )

        category_description = (
            AUDIT_CATEGORIES.get(
                category,
                "Azure DevOps AI Agent operation reports.",
            )
        )

        category_result = ensure_page(
            wiki_id=wiki_id,
            path=category_path,
            title=category,
            body=category_description,
        )

        if not category_result.get("success"):

            return {
                "success": False,
                "status": "Failed",
                "error": (
                    "Could not create or locate "
                    f"{category_path}: "
                    f"{category_result.get('error')}"
                ),
            }

        # ----------------------------------------------------
        # Target
        # ----------------------------------------------------

        page_path = (
            f"{category_path}/{operation_id}"
        )

        result = _create_or_update_page(
            wiki_id=wiki_id,
            path=page_path,
            content=content,
            retries=1,
        )

        result.update(
            {
                "page_path": page_path,
                "wiki_id": wiki_id,
                "category": category,
                "operation_id": operation_id,
            }
        )

        if result.get("success"):

            result["status"] = "Completed"

        else:

            result["status"] = "Failed"

        return result

    except requests.RequestException as exc:

        return {
            "success": False,
            "status": "Failed",
            "error": str(exc),
        }

    except Exception as exc:

        return {
            "success": False,
            "status": "Failed",
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
        }