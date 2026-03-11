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
        "type": "deployment.ready",
        "payload": {
            "installationId": "ins_1",
            "deployment": {"id": "dpl_1", "projectId": "prj_1", "teamId": "team_1"},
        },
    }
    event = parse_webhook_event(payload)
    assert event.event_type == "deployment.ready"
    assert event.installation_id == "ins_1"
    assert event.deployment_id == "dpl_1"
    assert event.project_id == "prj_1"
    assert event.team_id == "team_1"


def test_worker_processes_deployment_ready_with_installation_token(
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

    monkeypatch.setenv("INTEGRATION_DEPLOY_COMMAND", "python deploy_ibm.py")
    monkeypatch.setattr("integration.webhook.subprocess.run", fake_run)

    event = parse_webhook_event(
        {
            "type": "deployment.ready",
            "payload": {
                "installationId": "ins_1",
                "deployment": {"id": "dpl_1", "projectId": "prj_1", "teamId": "team_1"},
            },
        }
    )
    worker._process(event)

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["VERCEL_DEPLOYMENT_ID"] == "dpl_1"
    assert env["VERCEL_INSTALLATION_TOKEN"] == "tok_123"
