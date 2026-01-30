"""Helpers for constructing IBM Cloud Code Engine API payloads."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from core.config import ScalingConfig


DEFAULT_SOURCE_TYPE = "cos"
DEFAULT_STRATEGY_TYPE = "dockerfile"
DEFAULT_STRATEGY_SIZE = "medium"


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
