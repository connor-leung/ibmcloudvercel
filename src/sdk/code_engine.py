"""Helpers for constructing IBM Cloud Code Engine API payloads."""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Any, Optional, Union

import requests
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator, BearerTokenAuthenticator
from ibm_code_engine_sdk.code_engine_v2 import CodeEngineV2

from core.config import DeploymentConfig, ScalingConfig
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
    poll_request_timeout: int = 10,
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
        poll_request_timeout: Timeout (seconds) for each poll HTTP request

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
                timeout=poll_request_timeout,
            )
        except requests.RequestException as exc:
            # Polling should tolerate intermittent network/API timeouts until the overall
            # poll_timeout deadline is reached.
            print(f"  ⚠️  Poll request failed, retrying: {exc}")
            time.sleep(poll_interval)
            continue

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


def get_ce_client(
    authenticator: Union[IAMAuthenticator, BearerTokenAuthenticator],
    region: str,
    project_id: str,
) -> CodeEngineV2:
    """
    Create and configure a Code Engine SDK client.

    Args:
        authenticator: IBM Cloud IAM or Bearer token authenticator
        region: IBM Cloud region (e.g., "us-south")
        project_id: Code Engine project ID (accepted for caller convenience)

    Returns:
        Configured CodeEngineV2 client instance

    Raises:
        CodeEngineError: If the client cannot be created or configured

    Example:
        client = get_ce_client(authenticator, "us-south", "my-project-id")
    """
    try:
        client = CodeEngineV2(authenticator=authenticator)
        client.set_service_url(f"https://api.{region}.codeengine.cloud.ibm.com/v2")
        return client
    except Exception as exc:
        raise CodeEngineError("Failed to create Code Engine client", details=str(exc)) from exc


def create_build_run(
    client: CodeEngineV2,
    project_id: str,
    build_payload: dict[str, Any],
) -> str:
    """
    Submit a Code Engine build run from a build payload dict.

    Args:
        client: Configured CodeEngineV2 SDK client
        project_id: Code Engine project ID
        build_payload: Dict with keys: name, source_type, source_url,
            strategy_type, strategy_size, output_image, output_secret (optional)

    Returns:
        Auto-assigned build run name (str)

    Raises:
        CodeEngineError: If the API call fails or the response is missing a name

    Example:
        build_run_name = create_build_run(client, "proj-id", build_payload)
    """
    kwargs: dict[str, Any] = {
        "project_id": project_id,
        "build_config_name": build_payload["name"],
        "service_account": "default",
    }

    # Pass inline source spec fields when provided
    for field in ("source_type", "source_url", "strategy_type", "strategy_size", "output_image"):
        if field in build_payload:
            kwargs[field] = build_payload[field]
    if "output_secret" in build_payload:
        kwargs["output_secret"] = build_payload["output_secret"]

    try:
        result = client.create_build_run(**kwargs).get_result()
    except ApiException as exc:
        raise CodeEngineError("Failed to create Code Engine build run", details=str(exc)) from exc

    build_run_name = result.get("name")
    if not build_run_name:
        raise CodeEngineError(
            "Failed to create Code Engine build run",
            details="Response did not include a build run name",
        )

    print(f"  ✓ Build run submitted: {build_run_name}")
    return build_run_name


def wait_for_build_run(
    client: CodeEngineV2,
    project_id: str,
    build_run_name: str,
    timeout: int = 300,
    poll_interval: int = 10,
) -> None:
    """
    Poll a Code Engine build run until it succeeds or fails.

    Args:
        client: Configured CodeEngineV2 SDK client
        project_id: Code Engine project ID
        build_run_name: Name of the build run to monitor
        timeout: Max seconds to wait (default 300)
        poll_interval: Seconds between polls (default 10)

    Returns:
        None on success

    Raises:
        CodeEngineError: If the build run fails or the timeout is exceeded

    Example:
        wait_for_build_run(client, "proj-id", "my-app-build-run-abc")
    """
    deadline = time.monotonic() + timeout
    last_status: Optional[str] = None

    while time.monotonic() < deadline:
        try:
            result = client.get_build_run(
                project_id=project_id, name=build_run_name
            ).get_result()
        except ApiException as exc:
            print(f"  ⚠️  Poll request failed, retrying: {exc}")
            time.sleep(poll_interval)
            continue

        status = result.get("status")
        last_status = status
        print(f"  Build run status: {status}")

        if status == "succeeded":
            print(f"  ✓ Build run completed: {build_run_name}")
            return

        if status == "failed":
            status_details = result.get("status_details") or {}
            raise CodeEngineError("Build run failed", details=str(status_details))

        time.sleep(poll_interval)

    raise CodeEngineError(
        "Timed out waiting for build run",
        details=f"Last status: {last_status}",
    )


def create_or_update_app(
    client: CodeEngineV2,
    project_id: str,
    app_name: str,
    app_payload: dict[str, Any],
) -> Optional[str]:
    """
    Create or update a Code Engine app using the SDK client.

    Args:
        client: Configured CodeEngineV2 SDK client
        project_id: Code Engine project ID
        app_name: App name to create or update
        app_payload: Dict with app configuration fields (image_reference, image_port,
            scale_cpu_limit, scale_memory_limit, scale_min_instances,
            scale_max_instances, scale_concurrency, image_secret optional)

    Returns:
        Public URL of the app if available, otherwise None

    Raises:
        CodeEngineError: If the API call fails

    Example:
        url = create_or_update_app(client, "proj-id", "my-app", app_payload)
    """
    app_fields = {
        k: v
        for k, v in app_payload.items()
        if k
        in {
            "image_reference",
            "image_port",
            "scale_cpu_limit",
            "scale_memory_limit",
            "scale_min_instances",
            "scale_max_instances",
            "scale_concurrency",
            "image_secret",
        }
    }

    try:
        response = client.get_app(project_id=project_id, name=app_name)
        etag = response.get_headers().get("ETag") or "*"
        app_patch = {k: v for k, v in app_fields.items()}
        result = client.update_app(
            project_id=project_id,
            name=app_name,
            if_match=etag,
            app=app_patch,
        ).get_result()
        print(f"  ✓ Updated existing app: {app_name}")
    except ApiException as exc:
        if exc.code == 404:
            try:
                result = client.create_app(
                    project_id=project_id,
                    name=app_name,
                    **app_fields,
                ).get_result()
                print(f"  ✓ Created new app: {app_name}")
            except ApiException as create_exc:
                raise CodeEngineError(
                    "Failed to create Code Engine app", details=str(create_exc)
                ) from create_exc
        else:
            raise CodeEngineError(
                "Failed to query Code Engine app", details=str(exc)
            ) from exc

    return _extract_public_url(result)


def list_apps(
    client: CodeEngineV2,
    project_id: str,
    prefix: str = "",
) -> list[dict[str, Any]]:
    """
    List Code Engine apps in a project, optionally filtered by name prefix.

    Args:
        client: Configured CodeEngineV2 SDK client
        project_id: Code Engine project ID
        prefix: Only return apps whose names start with this string

    Returns:
        List of app dicts from the Code Engine API

    Raises:
        CodeEngineError: If the API call fails
    """
    apps: list[dict[str, Any]] = []
    start: Optional[str] = None

    while True:
        try:
            kwargs: dict[str, Any] = {"project_id": project_id, "limit": 100}
            if start:
                kwargs["start"] = start
            response = client.list_apps(**kwargs).get_result()
        except ApiException as exc:
            raise CodeEngineError("Failed to list Code Engine apps", details=str(exc)) from exc

        for app in response.get("apps", []):
            if not prefix or app.get("name", "").startswith(prefix):
                apps.append(app)

        next_page = response.get("next")
        if not next_page:
            break
        start = next_page.get("start")
        if not start:
            break

    return apps


def delete_app(
    client: CodeEngineV2,
    project_id: str,
    app_name: str,
) -> None:
    """
    Delete a Code Engine app by name.

    Args:
        client: Configured CodeEngineV2 SDK client
        project_id: Code Engine project ID
        app_name: Name of the app to delete

    Raises:
        CodeEngineError: If the API call fails (404 is silently ignored)
    """
    try:
        client.delete_app(project_id=project_id, name=app_name)
        print(f"  ✓ Deleted app: {app_name}")
    except ApiException as exc:
        if exc.code == 404:
            print(f"  ⚠️  App not found (already deleted?): {app_name}")
        else:
            raise CodeEngineError("Failed to delete Code Engine app", details=str(exc)) from exc


def deploy(
    config: "DeploymentConfig",
    authenticator: Union[IAMAuthenticator, BearerTokenAuthenticator],
    cos_uri: str,
) -> Optional[str]:
    """
    High-level orchestrator: build source from COS and deploy to Code Engine.

    Steps:
        1. Resolve image reference from environment
        2. Submit a build run
        3. Wait for the build to succeed
        4. Create or update the Code Engine app
        5. Return the public URL

    Args:
        config: Full deployment configuration (DeploymentConfig)
        authenticator: IBM Cloud IAM or Bearer token authenticator
        cos_uri: COS URI pointing to the source archive (e.g., cos://bucket/src.zip)

    Returns:
        Public URL of the deployed app if available, otherwise None

    Raises:
        CodeEngineError: If image reference is missing, any SDK call fails,
            or the build run times out

    Example:
        url = deploy(config, authenticator, "cos://my-bucket/source.zip")
    """
    image_reference = os.getenv("IBM_CODE_ENGINE_IMAGE_REFERENCE") or os.getenv(
        "IBM_CODE_ENGINE_IMAGE"
    )
    if not image_reference:
        raise CodeEngineError(
            "Failed to resolve Code Engine image reference",
            details=(
                "Set IBM_CODE_ENGINE_IMAGE_REFERENCE (or IBM_CODE_ENGINE_IMAGE) "
                "to the target container image"
            ),
        )

    app_name = config.vercel.get_app_name()
    build_name = f"{app_name}-build"

    client = get_ce_client(authenticator, config.ibm_cloud.region, config.ibm_cloud.project_id)

    build_payload = build_code_engine_build_payload(
        name=build_name,
        cos_uri=cos_uri,
        output_image=image_reference,
        output_secret=config.ibm_cloud.registry_secret,
    )

    build_run_name = create_build_run(client, config.ibm_cloud.project_id, build_payload)
    wait_for_build_run(client, config.ibm_cloud.project_id, build_run_name)

    app_payload = build_code_engine_app_payload(
        name=app_name,
        image_reference=image_reference,
        scaling=config.scaling,
        registry_secret=config.ibm_cloud.registry_secret,
    )

    url = create_or_update_app(client, config.ibm_cloud.project_id, app_name, app_payload)
    return url
