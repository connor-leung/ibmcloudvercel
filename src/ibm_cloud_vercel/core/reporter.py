"""Helpers for reporting deployment status back to Vercel."""

from __future__ import annotations

import os
from typing import Optional

import requests

VERCEL_API_BASE = "https://api.vercel.com"
CHECK_NAME = "ibm-cloud-vercel"


def _get_checks_token(token: Optional[str] = None) -> Optional[str]:
    """Resolve the Vercel checks token from the caller or environment."""
    return token or os.getenv("VERCEL_CHECKS_TOKEN")


def _post_check_update(
    deployment_id: str,
    payload: dict,
    token: str,
) -> None:
    """Send a check update to the Vercel API."""
    url = f"{VERCEL_API_BASE}/v1/deployments/{deployment_id}/checks"
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
    summary: str | None = None,
) -> None:
    """Create an in-progress deployment check in Vercel."""
    if not deployment_id:
        print("  ⚠️  Missing Vercel deployment ID; skipping check start.")
        return

    resolved_token = _get_checks_token(token)
    if not resolved_token:
        print("  ⚠️  Vercel checks token not provided; skipping check start.")
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

    _post_check_update(deployment_id, payload, resolved_token)


def complete_deployment_check(
    deployment_id: Optional[str],
    token: Optional[str] = None,
    *,
    status: str,
    url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Complete the deployment check with a final status."""
    if not deployment_id:
        print("  ⚠️  Missing Vercel deployment ID; skipping check completion.")
        return

    resolved_token = _get_checks_token(token)
    if not resolved_token:
        print("  ⚠️  Vercel checks token not provided; skipping check completion.")
        return

    summary = (
        f"Deployment succeeded. URL: {url}"
        if status == "succeeded"
        else f"Deployment failed: {error or 'Unknown error'}"
    )

    payload = {
        "checks": [
            {
                "name": CHECK_NAME,
                "status": status,
                "detailsUrl": url,
                "externalId": deployment_id,
                "output": {
                    "title": "Deployment Result",
                    "summary": summary,
                },
            }
        ]
    }

    _post_check_update(deployment_id, payload, resolved_token)
