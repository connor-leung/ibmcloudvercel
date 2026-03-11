"""Helpers for reporting deployment status back to Vercel."""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlencode

import requests

VERCEL_API_BASE = "https://api.vercel.com"
CHECK_NAME = "ibm-cloud-vercel"


def _should_skip_checks_for_deployment(deployment_id: str) -> bool:
    """Return True for local placeholder deployment IDs used in local runs."""
    normalized = deployment_id.strip().lower()
    if not normalized:
        return True

    return normalized in {"local", "test-local", "test", "dev-local"}


def _resolve_checks_token(
    token: Optional[str] = None,
    installation_token: Optional[str] = None,
) -> Optional[str]:
    """Resolve a token usable for checks API calls."""
    return (
        token
        or installation_token
        or os.getenv("VERCEL_CHECKS_TOKEN")
        or os.getenv("VERCEL_INSTALLATION_TOKEN")
        or os.getenv("VERCEL_INTEGRATION_ACCESS_TOKEN")
    )


def _resolve_team_id(team_id: Optional[str] = None) -> Optional[str]:
    """Resolve Vercel team scope for installation-token requests."""
    return team_id or os.getenv("VERCEL_TEAM_ID")


def _post_check_update(
    deployment_id: str,
    payload: dict,
    token: str,
    *,
    team_id: Optional[str] = None,
) -> None:
    """Send a check update to the Vercel API."""
    if _should_skip_checks_for_deployment(deployment_id):
        print(f"  i  Skipping Vercel checks for local deployment ID '{deployment_id}'.")
        return

    url = f"{VERCEL_API_BASE}/v1/deployments/{deployment_id}/checks"
    resolved_team_id = _resolve_team_id(team_id)
    if resolved_team_id:
        url = f"{url}?{urlencode({'teamId': resolved_team_id})}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        print(f"  ⚠️  Failed to update Vercel check: {exc}")


def start_deployment_check(
    deployment_id: Optional[str],
    token: Optional[str] = None,
    installation_token: Optional[str] = None,
    team_id: Optional[str] = None,
    summary: str | None = None,
) -> None:
    """Create an in-progress deployment check in Vercel."""
    if not deployment_id:
        print("  ⚠️  Missing Vercel deployment ID; skipping check start.")
        return

    if _should_skip_checks_for_deployment(deployment_id):
        print(f"  i  Skipping Vercel checks for local deployment ID '{deployment_id}'.")
        return

    resolved_token = _resolve_checks_token(token, installation_token)
    if not resolved_token:
        print("  ⚠️  Vercel checks/installation token not provided; skipping check start.")
        return

    payload = {
        "checks": [
            {
                "name": CHECK_NAME,
                "status": "in-progress",
                "detailsUrl": None,
                "externalId": deployment_id,
                "output": {
                    "title": "Deploying to IBM Cloud",
                    "summary": summary
                    or "Uploading build artifacts to IBM Cloud Object Storage.",
                },
            }
        ]
    }

    _post_check_update(
        deployment_id,
        payload,
        resolved_token,
        team_id=team_id,
    )


def complete_deployment_check(
    deployment_id: Optional[str],
    token: Optional[str] = None,
    installation_token: Optional[str] = None,
    team_id: Optional[str] = None,
    *,
    status: str,
    url: Optional[str] = None,
    error: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """Complete the deployment check with a final status."""
    if not deployment_id:
        print("  ⚠️  Missing Vercel deployment ID; skipping check completion.")
        return

    if _should_skip_checks_for_deployment(deployment_id):
        print(f"  i  Skipping Vercel checks for local deployment ID '{deployment_id}'.")
        return

    resolved_token = _resolve_checks_token(token, installation_token)
    if not resolved_token:
        print("  ⚠️  Vercel checks/installation token not provided; skipping check completion.")
        return

    normalized_status = status if status in {"in-progress", "succeeded", "failed"} else "failed"
    if normalized_status == "succeeded":
        summary = "Deployment succeeded."
        if url:
            summary = f"{summary} URL: {url}"
        if details:
            summary = f"{summary} {details}"
        title = "Deployment Succeeded"
    elif normalized_status == "in-progress":
        summary = details or "Deployment is in progress."
        title = "Deployment In Progress"
    else:
        summary = f"Deployment failed: {error or 'Unknown error'}"
        if details:
            summary = f"{summary} {details}"
        title = "Deployment Failed"

    payload = {
        "checks": [
            {
                "name": CHECK_NAME,
                "status": normalized_status,
                "detailsUrl": url,
                "externalId": deployment_id,
                "output": {
                    "title": title,
                    "summary": summary,
                },
            }
        ]
    }

    _post_check_update(
        deployment_id,
        payload,
        resolved_token,
        team_id=team_id,
    )
