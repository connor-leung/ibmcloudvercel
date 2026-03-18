"""Unit tests for SDK-based Code Engine functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.exceptions import CodeEngineError
from sdk.code_engine import (
    create_build_run,
    create_or_update_app,
    get_ce_client,
    wait_for_build_run,
    deploy,
)


# ---------------------------------------------------------------------------
# get_ce_client
# ---------------------------------------------------------------------------

def test_get_ce_client_configures_service_url():
    authenticator = MagicMock()
    with patch("sdk.code_engine.CodeEngineV2") as MockCE:
        mock_client = MagicMock()
        MockCE.return_value = mock_client

        client = get_ce_client(authenticator, "us-south", "proj-123")

        MockCE.assert_called_once_with(authenticator=authenticator)
        mock_client.set_service_url.assert_called_once_with(
            "https://api.us-south.codeengine.cloud.ibm.com/v2"
        )
        assert client is mock_client


def test_get_ce_client_raises_on_failure():
    authenticator = MagicMock()
    with patch("sdk.code_engine.CodeEngineV2", side_effect=RuntimeError("boom")):
        with pytest.raises(CodeEngineError, match="Failed to create Code Engine client"):
            get_ce_client(authenticator, "us-south", "proj-123")


# ---------------------------------------------------------------------------
# create_build_run
# ---------------------------------------------------------------------------

def _make_client_with_build_run(build_run_name: str) -> MagicMock:
    client = MagicMock()
    client.create_build_run.return_value.get_result.return_value = {"name": build_run_name}
    return client


def test_create_build_run_returns_name():
    client = _make_client_with_build_run("my-app-build-run-abc")
    payload = {
        "name": "my-build",
        "source_type": "git",
        "source_url": "https://github.com/owner/repo",
        "source_revision": "abc123",
        "strategy_type": "dockerfile",
        "strategy_size": "medium",
        "output_image": "private.icr.io/ns/app:tag",
        "output_secret": "reg-secret",
    }

    result = create_build_run(client, "proj-123", payload)

    assert result == "my-app-build-run-abc"
    client.create_build_run.assert_called_once()


def test_create_build_run_raises_on_missing_name():
    client = MagicMock()
    client.create_build_run.return_value.get_result.return_value = {}  # no name

    with pytest.raises(CodeEngineError, match="Failed to create Code Engine build run"):
        create_build_run(client, "proj-123", {"name": "my-build"})


def test_create_build_run_raises_on_api_exception():
    from ibm_cloud_sdk_core import ApiException

    client = MagicMock()
    client.create_build_run.side_effect = ApiException(400, message="bad request")

    with pytest.raises(CodeEngineError, match="Failed to create Code Engine build run"):
        create_build_run(client, "proj-123", {"name": "my-build"})


# ---------------------------------------------------------------------------
# wait_for_build_run
# ---------------------------------------------------------------------------

def test_wait_for_build_run_succeeds():
    client = MagicMock()
    client.get_build_run.return_value.get_result.return_value = {"status": "succeeded"}

    # Should return without raising
    wait_for_build_run(client, "proj-123", "run-abc", timeout=30, poll_interval=0)


def test_wait_for_build_run_raises_on_failed():
    client = MagicMock()
    client.get_build_run.return_value.get_result.return_value = {
        "status": "failed",
        "status_details": {"reason": "dockerfile not found"},
    }

    with pytest.raises(CodeEngineError, match="Build run failed"):
        wait_for_build_run(client, "proj-123", "run-abc", timeout=30, poll_interval=0)


def test_wait_for_build_run_times_out():
    client = MagicMock()
    client.get_build_run.return_value.get_result.return_value = {"status": "running"}

    with pytest.raises(CodeEngineError, match="Timed out waiting for build run"):
        wait_for_build_run(client, "proj-123", "run-abc", timeout=0, poll_interval=0)


def test_wait_for_build_run_tolerates_api_exception():
    from ibm_cloud_sdk_core import ApiException

    client = MagicMock()
    # First call raises ApiException, second call succeeds
    client.get_build_run.return_value.get_result.side_effect = [
        ApiException(503, message="service unavailable"),
        {"status": "succeeded"},
    ]

    # Should not raise — tolerates the transient error
    wait_for_build_run(client, "proj-123", "run-abc", timeout=60, poll_interval=0)


# ---------------------------------------------------------------------------
# create_or_update_app
# ---------------------------------------------------------------------------

def test_create_or_update_app_updates_existing():
    from ibm_cloud_sdk_core import ApiException

    client = MagicMock()
    client.get_app.return_value.get_headers.return_value = {"ETag": '"v1"'}
    client.update_app.return_value.get_result.return_value = {
        "endpoint": "https://my-app.example.com"
    }

    payload = {
        "image_reference": "private.icr.io/ns/app:tag",
        "image_port": 3000,
        "scale_min_instances": 1,
        "scale_max_instances": 3,
        "scale_cpu_limit": "1",
        "scale_memory_limit": "2G",
        "scale_concurrency": 50,
    }

    url = create_or_update_app(client, "proj-123", "my-app", payload)

    client.update_app.assert_called_once()
    assert url == "https://my-app.example.com"


def test_create_or_update_app_creates_when_not_found():
    from ibm_cloud_sdk_core import ApiException

    client = MagicMock()
    client.get_app.side_effect = ApiException(404, message="not found")
    client.create_app.return_value.get_result.return_value = {
        "endpoint": "https://new-app.example.com"
    }

    payload = {
        "image_reference": "private.icr.io/ns/app:tag",
        "image_port": 3000,
        "scale_min_instances": 0,
        "scale_max_instances": 5,
        "scale_cpu_limit": "0.5",
        "scale_memory_limit": "1G",
        "scale_concurrency": 100,
    }

    url = create_or_update_app(client, "proj-123", "my-app", payload)

    client.create_app.assert_called_once()
    assert url == "https://new-app.example.com"


def test_create_or_update_app_raises_on_unexpected_error():
    from ibm_cloud_sdk_core import ApiException

    client = MagicMock()
    client.get_app.side_effect = ApiException(500, message="internal error")

    with pytest.raises(CodeEngineError, match="Failed to query Code Engine app"):
        create_or_update_app(client, "proj-123", "my-app", {})


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------

def test_deploy_raises_without_image_reference(monkeypatch):
    monkeypatch.delenv("IBM_CODE_ENGINE_IMAGE_REFERENCE", raising=False)
    monkeypatch.delenv("IBM_CODE_ENGINE_IMAGE", raising=False)

    from core.config import DeploymentConfig, IBMCloudConfig, ScalingConfig, VercelConfig

    config = DeploymentConfig(
        ibm_cloud=IBMCloudConfig(
            region="us-south",
            project_id="proj-123",
        ),
        scaling=ScalingConfig(),
        vercel=VercelConfig(
            git_commit_sha="abc123",
            git_commit_ref="main",
            deployment_id="dep-1",
            project_name="my-app",
            git_repo_owner="owner",
            git_repo_slug="repo",
        ),
    )

    with pytest.raises(CodeEngineError, match="Failed to resolve Code Engine image reference"):
        deploy(config, MagicMock())


def test_deploy_orchestrates_full_flow(monkeypatch):
    monkeypatch.setenv("IBM_CODE_ENGINE_IMAGE_REFERENCE", "private.icr.io/ns/app:latest")

    from core.config import DeploymentConfig, IBMCloudConfig, ScalingConfig, VercelConfig

    config = DeploymentConfig(
        ibm_cloud=IBMCloudConfig(
            region="us-south",
            project_id="proj-123",
        ),
        scaling=ScalingConfig(),
        vercel=VercelConfig(
            git_commit_sha="abc123",
            git_commit_ref="main",
            deployment_id="dep-1",
            project_name="my-app",
            git_repo_owner="owner",
            git_repo_slug="repo",
        ),
    )

    with (
        patch("sdk.code_engine.get_ce_client") as mock_get_client,
        patch("sdk.code_engine.create_build_run", return_value="run-xyz") as mock_build,
        patch("sdk.code_engine.wait_for_build_run") as mock_wait,
        patch(
            "sdk.code_engine.create_or_update_app",
            return_value="https://my-app.example.com",
        ) as mock_app,
    ):
        url = deploy(config, MagicMock())

    mock_get_client.assert_called_once()
    mock_build.assert_called_once()
    mock_wait.assert_called_once_with(mock_get_client.return_value, "proj-123", "run-xyz")
    mock_app.assert_called_once()
    assert url == "https://my-app.example.com"
