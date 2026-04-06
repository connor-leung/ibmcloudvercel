from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from integration.store import InstallationStore
from integration.webhook import DeploymentJobWorker, parse_webhook_event, verify_webhook_signature


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha1).hexdigest()
    return f"sha1={digest}"


def test_verify_webhook_signature_valid() -> None:
    secret = "topsecret"
    body = b'{"type":"deployment.ready"}'
    ok, error = verify_webhook_signature(
        raw_body=body,
        signature_header=_signature(secret, body),
        secret=secret,
    )
    assert ok is True
    assert error is None


def test_verify_webhook_signature_invalid() -> None:
    ok, error = verify_webhook_signature(
        raw_body=b"{}",
        signature_header="sha1=bad",
        secret="topsecret",
    )
    assert ok is False
    assert error == "Invalid webhook signature."


def test_parse_webhook_event_extracts_fields() -> None:
    payload = {
        "type": "deployment.created",
        "payload": {
            "installationId": "ins_1",
            "deployment": {
                "id": "dpl_1",
                "projectId": "prj_1",
                "teamId": "team_1",
                "name": "my-project",
                "meta": {
                    "githubCommitRef": "feature/x",
                    "githubCommitSha": "abc123",
                    "githubCommitOrg": "my-org",
                    "githubRepo": "my-repo",
                },
            },
            "project": {"name": "my-project"},
        },
    }
    event = parse_webhook_event(payload)
    assert event.event_type == "deployment.created"
    assert event.installation_id == "ins_1"
    assert event.deployment_id == "dpl_1"
    assert event.project_id == "prj_1"
    assert event.team_id == "team_1"
    assert event.git_commit_ref == "feature/x"
    assert event.git_commit_sha == "abc123"
    assert event.git_repo_owner == "my-org"
    assert event.git_repo_slug == "my-repo"
    assert event.project_name == "my-project"


def test_worker_processes_deployment_created_with_installation_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = InstallationStore(tmp_path / "installations.json")
    store.upsert_installation(installation_id="ins_1", access_token="tok_123")
    worker = DeploymentJobWorker(store=store)

    captured: dict[str, object] = {}

    class DummyResult:
        returncode = 0

    def fake_run(cmd, env, check):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["env"] = env
        captured["check"] = check
        return DummyResult()

    monkeypatch.setenv("INTEGRATION_DEPLOY_COMMAND", "python3 deploy_ibm.py --build")
    monkeypatch.setattr("integration.webhook.subprocess.run", fake_run)

    event = parse_webhook_event(
        {
            "type": "deployment.created",
            "payload": {
                "installationId": "ins_1",
                "deployment": {
                    "id": "dpl_1",
                    "projectId": "prj_1",
                    "teamId": "team_1",
                    "name": "my-project",
                    "meta": {
                        "githubCommitRef": "feature/x",
                        "githubCommitSha": "abc123",
                        "githubCommitOrg": "my-org",
                        "githubRepo": "my-repo",
                    },
                },
                "project": {"name": "my-project"},
            },
        }
    )
    worker._process(event)

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["VERCEL_DEPLOYMENT_ID"] == "dpl_1"
    assert env["VERCEL_INSTALLATION_TOKEN"] == "tok_123"
    assert env["VERCEL_GIT_COMMIT_SHA"] == "abc123"
    assert env["VERCEL_GIT_COMMIT_REF"] == "feature/x"
    assert env["VERCEL_GIT_REPO_OWNER"] == "my-org"
    assert env["VERCEL_GIT_REPO_SLUG"] == "my-repo"
    assert env["VERCEL_PROJECT_NAME"] == "my-project"


def test_worker_injects_ibm_credentials_from_installation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = InstallationStore(tmp_path / "installations.json")
    store.upsert_installation(
        installation_id="ins_1",
        access_token="tok_123",
        ibm_cloud_api_key="my-api-key",
        ibm_code_engine_project_id="proj-abc",
        ibm_registry_secret="icr-secret",
        ibm_cloud_region="eu-gb",
        ibm_icr_namespace="my-ns",
    )
    worker = DeploymentJobWorker(store=store)

    captured: dict[str, object] = {}

    class DummyResult:
        returncode = 0

    def fake_run(cmd, env, check):  # type: ignore[no-untyped-def]
        captured["env"] = env
        return DummyResult()

    monkeypatch.setenv("INTEGRATION_DEPLOY_COMMAND", "python3 deploy_ibm.py --build")
    monkeypatch.setattr("integration.webhook.subprocess.run", fake_run)

    event = parse_webhook_event({
        "type": "deployment.created",
        "payload": {
            "installationId": "ins_1",
            "deployment": {
                "id": "dpl_1", "projectId": "prj_1", "teamId": "team_1",
                "meta": {"githubCommitRef": "main", "githubRepo": "my-repo"},
            },
            "project": {"name": "my-project"},
        },
    })
    worker._process(event)

    env = captured["env"]
    assert env["IBM_CLOUD_API_KEY"] == "my-api-key"
    assert env["IBM_CODE_ENGINE_PROJECT_ID"] == "proj-abc"
    assert env["IBM_REGISTRY_SECRET"] == "icr-secret"
    assert env["IBM_CLOUD_REGION"] == "eu-gb"
    assert env["IBM_ICR_NAMESPACE"] == "my-ns"


def test_worker_derives_image_reference_from_project_and_branch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = InstallationStore(tmp_path / "installations.json")
    store.upsert_installation(installation_id="ins_1", access_token="tok")
    worker = DeploymentJobWorker(store=store)

    captured: dict[str, object] = {}

    class DummyResult:
        returncode = 0

    def fake_run(cmd, env, check):  # type: ignore[no-untyped-def]
        captured["env"] = env
        return DummyResult()

    monkeypatch.setenv("INTEGRATION_DEPLOY_COMMAND", "python3 deploy_ibm.py --build")
    monkeypatch.delenv("IBM_CODE_ENGINE_IMAGE_REFERENCE", raising=False)
    monkeypatch.setattr("integration.webhook.subprocess.run", fake_run)

    event = parse_webhook_event({
        "type": "deployment.created",
        "payload": {
            "installationId": "ins_1",
            "deployment": {
                "id": "dpl_1", "projectId": "prj_1", "teamId": "team_1",
                "meta": {"githubCommitRef": "main", "githubRepo": "test-repo"},
            },
            "project": {"name": "test-repo"},
        },
    })
    worker._process(event)

    assert captured["env"]["IBM_CODE_ENGINE_IMAGE_REFERENCE"] == "us.icr.io/ibmcloudvercel/test-repo:main"


def test_worker_sanitizes_branch_name_in_image_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = InstallationStore(tmp_path / "installations.json")
    store.upsert_installation(installation_id="ins_1", access_token="tok")
    worker = DeploymentJobWorker(store=store)

    captured: dict[str, object] = {}

    class DummyResult:
        returncode = 0

    def fake_run(cmd, env, check):  # type: ignore[no-untyped-def]
        captured["env"] = env
        return DummyResult()

    monkeypatch.setenv("INTEGRATION_DEPLOY_COMMAND", "python3 deploy_ibm.py --build")
    monkeypatch.delenv("IBM_CODE_ENGINE_IMAGE_REFERENCE", raising=False)
    monkeypatch.setattr("integration.webhook.subprocess.run", fake_run)

    event = parse_webhook_event({
        "type": "deployment.created",
        "payload": {
            "installationId": "ins_1",
            "deployment": {
                "id": "dpl_1", "projectId": "prj_1", "teamId": "team_1",
                "meta": {"githubCommitRef": "feature/my_branch", "githubRepo": "my-app"},
            },
            "project": {"name": "my-app"},
        },
    })
    worker._process(event)

    assert captured["env"]["IBM_CODE_ENGINE_IMAGE_REFERENCE"] == "us.icr.io/ibmcloudvercel/my-app:feature-my-branch"


def test_worker_respects_explicit_image_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = InstallationStore(tmp_path / "installations.json")
    store.upsert_installation(installation_id="ins_1", access_token="tok")
    worker = DeploymentJobWorker(store=store)

    captured: dict[str, object] = {}

    class DummyResult:
        returncode = 0

    def fake_run(cmd, env, check):  # type: ignore[no-untyped-def]
        captured["env"] = env
        return DummyResult()

    monkeypatch.setenv("INTEGRATION_DEPLOY_COMMAND", "python3 deploy_ibm.py --build")
    monkeypatch.setenv("IBM_CODE_ENGINE_IMAGE_REFERENCE", "us.icr.io/custom/image:tag")
    monkeypatch.setattr("integration.webhook.subprocess.run", fake_run)

    event = parse_webhook_event({
        "type": "deployment.created",
        "payload": {
            "installationId": "ins_1",
            "deployment": {
                "id": "dpl_1", "projectId": "prj_1", "teamId": "team_1",
                "meta": {"githubCommitRef": "main", "githubRepo": "test-repo"},
            },
            "project": {"name": "test-repo"},
        },
    })
    worker._process(event)

    assert captured["env"]["IBM_CODE_ENGINE_IMAGE_REFERENCE"] == "us.icr.io/custom/image:tag"


def test_parse_webhook_event_git_fields_fallback() -> None:
    payload = {
        "type": "deployment.created",
        "payload": {
            "installationId": "ins_1",
            "deployment": {"id": "dpl_1", "projectId": "prj_1", "teamId": "team_1"},
        },
    }
    event = parse_webhook_event(payload)
    assert event.git_commit_ref is None
    assert event.git_commit_sha is None
    assert event.git_repo_owner is None
    assert event.git_repo_slug is None
    assert event.project_name is None
