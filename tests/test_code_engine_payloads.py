from __future__ import annotations

from core.config import ScalingConfig
from sdk.code_engine import build_code_engine_app_payload, build_code_engine_build_payload


def test_build_payload_for_app() -> None:
    payload = build_code_engine_app_payload(
        name="my-app",
        image_reference="private.icr.io/ns/app:1",
        scaling=ScalingConfig(
            min_scale=1,
            max_scale=3,
            cpu="1",
            memory="2G",
            port=3000,
            concurrency=50,
        ),
        registry_secret="reg-secret",
    )

    assert payload["name"] == "my-app"
    assert payload["image_reference"] == "private.icr.io/ns/app:1"
    assert payload["image_port"] == 3000
    assert payload["scale_min_instances"] == 1
    assert payload["scale_max_instances"] == 3
    assert payload["registry_secret"] == "reg-secret"


def test_build_payload_for_git_build() -> None:
    payload = build_code_engine_build_payload(
        name="my-build",
        source_url="https://github.com/owner/repo",
        output_image="docker.io/user/app:1",
        output_secret="push-secret",
        source_revision="abc123",
        source_context_dir="welcome-image",
    )

    assert payload["name"] == "my-build"
    assert payload["source_type"] == "git"
    assert payload["source_url"] == "https://github.com/owner/repo"
    assert payload["output_image"] == "docker.io/user/app:1"
    assert payload["output_secret"] == "push-secret"
    assert payload["source_revision"] == "abc123"
    assert payload["source_context_dir"] == "welcome-image"
