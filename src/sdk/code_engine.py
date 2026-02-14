"""Helpers for constructing IBM Cloud Code Engine API payloads."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Optional, Union

import requests
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator, BearerTokenAuthenticator

from core.config import ScalingConfig
from core.exceptions import CodeEngineError


DEFAULT_SOURCE_TYPE = "cos"
DEFAULT_STRATEGY_TYPE = "dockerfile"
DEFAULT_STRATEGY_SIZE = "medium"
DEFAULT_CODE_ENGINE_VERSION = "2024-05-13"


def _get_bearer_token(
    authenticator: Union[IAMAuthenticator, BearerTokenAuthenticator],
) -> str:
    if isinstance(authenticator, IAMAuthenticator):
        token = authenticator.token_manager.get_token()
    else:
        token = authenticator.bearer_token

    if not token:
        raise CodeEngineError("Failed to obtain IBM Cloud IAM access token")

    if token.startswith("Bearer "):
        return token

    return f"Bearer {token}"


def _build_base_url(region: str, project_id: str) -> str:
    return f"https://api.{region}.codeengine.cloud.ibm.com/v2/projects/{project_id}"


def _extract_public_url(app_data: dict[str, Any]) -> Optional[str]:
    endpoint = app_data.get("endpoint")
    if endpoint:
        return endpoint

    env_vars = app_data.get("run_env_variables", [])
    if not isinstance(env_vars, list):
        return None

    env_map = {
        item.get("name"): item.get("value")
        for item in env_vars
        if isinstance(item, dict)
    }

    app_name = env_map.get("CE_APP")
    subdomain = env_map.get("CE_SUBDOMAIN")
    domain = env_map.get("CE_DOMAIN")

    if app_name and subdomain and domain:
        return f"https://{app_name}.{subdomain}.{domain}"

    return None


def build_code_engine_build_payload(
    *,
    name: str,
    cos_uri: str,
    output_image: str,
    output_secret: Optional[str] = None,
    source_type: str = DEFAULT_SOURCE_TYPE,
    strategy_type: str = DEFAULT_STRATEGY_TYPE,
    strategy_size: str = DEFAULT_STRATEGY_SIZE,
) -> dict[str, Any]:
    """
    Build the Code Engine build payload for a COS source archive.

    Args:
        name: Build name in Code Engine
        cos_uri: COS URI (e.g., cos://bucket/path/to/source.zip)
        output_image: Target image reference (e.g., private.us.icr.io/ns/app:tag)
        output_secret: Optional registry secret name
        source_type: Source type for Code Engine (defaults to COS)
        strategy_type: Build strategy (defaults to dockerfile)
        strategy_size: Build size (defaults to medium)

    Returns:
        Build payload dict suitable for the Code Engine builds API.
    """
    payload: dict[str, Any] = {
        "name": name,
        "source_type": source_type,
        "source_url": cos_uri,
        "strategy_type": strategy_type,
        "strategy_size": strategy_size,
        "output_image": output_image,
    }

    if output_secret:
        payload["output_secret"] = output_secret

    return payload


def build_code_engine_app_payload(
    *,
    name: str,
    image_reference: str,
    scaling: ScalingConfig,
    registry_secret: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build the Code Engine app payload for create/update operations.

    Args:
        name: App name in Code Engine
        image_reference: Container image reference
        scaling: Scaling configuration (cpu, memory, port, min/max, concurrency)
        registry_secret: Optional registry secret for image pull

    Returns:
        App payload dict suitable for the Code Engine apps API.
    """
    scaling_data = asdict(scaling)

    payload: dict[str, Any] = {
        "name": name,
        "image_reference": image_reference,
        "image_port": scaling_data["port"],
        "scale_cpu_limit": scaling_data["cpu"],
        "scale_memory_limit": scaling_data["memory"],
        "scale_min_instances": scaling_data["min_scale"],
        "scale_max_instances": scaling_data["max_scale"],
        "scale_concurrency": scaling_data["concurrency"],
    }

    if registry_secret:
        payload["registry_secret"] = registry_secret

    return payload


def build_code_engine_payloads(
    *,
    app_name: str,
    build_name: str,
    cos_uri: str,
    image_reference: str,
    scaling: ScalingConfig,
    output_secret: Optional[str] = None,
    registry_secret: Optional[str] = None,
    source_type: str = DEFAULT_SOURCE_TYPE,
    strategy_type: str = DEFAULT_STRATEGY_TYPE,
    strategy_size: str = DEFAULT_STRATEGY_SIZE,
) -> dict[str, dict[str, Any]]:
    """
    Compose both build and app payloads for the Code Engine API.

    Returns:
        Dict with "build" and "app" payloads.
    """
    build_payload = build_code_engine_build_payload(
        name=build_name,
        cos_uri=cos_uri,
        output_image=image_reference,
        output_secret=output_secret,
        source_type=source_type,
        strategy_type=strategy_type,
        strategy_size=strategy_size,
    )

    app_payload = build_code_engine_app_payload(
        name=app_name,
        image_reference=image_reference,
        scaling=scaling,
        registry_secret=registry_secret,
    )

    return {"build": build_payload, "app": app_payload}


def deploy_application(
    *,
    authenticator: Union[IAMAuthenticator, BearerTokenAuthenticator],
    region: str,
    project_id: str,
    app_name: str,
    payload: dict[str, Any],
    version: str = DEFAULT_CODE_ENGINE_VERSION,
    poll_interval: int = 5,
    poll_timeout: int = 600,
) -> tuple[dict[str, Any], Optional[str]]:
    """
    Create or update a Code Engine app, poll until ready, and return the public URL.

    Args:
        authenticator: IBM Cloud IAM or Bearer token authenticator
        region: IBM Cloud region for the Code Engine project
        project_id: Code Engine project ID
        app_name: App name to create/update
        payload: App payload for create/update
        version: Code Engine API version date (YYYY-MM-DD)
        poll_interval: Seconds between status checks
        poll_timeout: Max seconds to wait for ready status

    Returns:
        Tuple of (app data dict, public URL if available)
    """
    token = _get_bearer_token(authenticator)
    base_url = _build_base_url(region, project_id)
    app_url = f"{base_url}/apps/{app_name}"
    apps_url = f"{base_url}/apps"

    headers = {
        "Authorization": token,
        "Accept": "application/json",
    }

    params = {"version": version}

    try:
        existing = requests.get(app_url, headers=headers, params=params, timeout=10)
    except requests.RequestException as exc:
        raise CodeEngineError("Failed to query Code Engine app", details=str(exc)) from exc

    if existing.status_code == 200:
        etag = existing.headers.get("ETag") or existing.headers.get("Etag")
        patch_headers = {
            **headers,
            "Content-Type": "application/merge-patch+json",
            "If-Match": etag or "*",
        }
        try:
            response = requests.patch(
                app_url,
                headers=patch_headers,
                params=params,
                json=payload,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise CodeEngineError("Failed to update Code Engine app", details=str(exc)) from exc
    elif existing.status_code == 404:
        try:
            response = requests.post(
                apps_url,
                headers={**headers, "Content-Type": "application/json"},
                params=params,
                json=payload,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise CodeEngineError("Failed to create Code Engine app", details=str(exc)) from exc
    else:
        raise CodeEngineError(
            "Unexpected response while checking Code Engine app",
            details=f"Status {existing.status_code}: {existing.text}",
        )

    if response.status_code not in (200, 201, 202):
        raise CodeEngineError(
            "Code Engine app create/update failed",
            details=f"Status {response.status_code}: {response.text}",
        )

    deadline = time.monotonic() + poll_timeout
    last_status = None

    while time.monotonic() < deadline:
        try:
            poll_response = requests.get(
                app_url,
                headers=headers,
                params=params,
                timeout=10,
            )
        except requests.RequestException as exc:
            raise CodeEngineError("Failed to poll Code Engine app", details=str(exc)) from exc

        if poll_response.status_code != 200:
            raise CodeEngineError(
                "Failed to poll Code Engine app status",
                details=f"Status {poll_response.status_code}: {poll_response.text}",
            )

        app_data = poll_response.json()
        status = app_data.get("status")
        last_status = status

        if status == "ready":
            return app_data, _extract_public_url(app_data)

        if status in {"failed", "error"}:
            details = app_data.get("status_details") or {}
            raise CodeEngineError(
                "Code Engine app failed to become ready",
                details=str(details),
            )

        time.sleep(poll_interval)

    raise CodeEngineError(
        "Timed out waiting for Code Engine app to become ready",
        details=f"Last status: {last_status}",
    )
