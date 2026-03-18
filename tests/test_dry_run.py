from __future__ import annotations

import deploy_ibm
from core.config import DeploymentConfig, IBMCloudConfig, ScalingConfig, VercelConfig


def test_main_dry_run_skips_cloud_mutations(monkeypatch) -> None:
    config = DeploymentConfig(
        ibm_cloud=IBMCloudConfig(
            region="us-south",
            project_id="project-1",
            trusted_profile_id=None,
        ),
        scaling=ScalingConfig(),
        vercel=VercelConfig(
            git_commit_sha="abc",
            git_commit_ref="main",
            deployment_id="dep_1",
            project_name="app",
            checks_token=None,
        ),
    )

    calls = {"start": 0, "complete": 0}

    def fail_cloud_call(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("cloud call should not happen in dry-run mode")

    def fake_start(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["start"] += 1

    def fake_complete(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["complete"] += 1

    monkeypatch.setenv("IBM_CLOUD_VERCEL_DRY_RUN", "true")
    monkeypatch.setattr(deploy_ibm, "load_config", lambda: config)
    monkeypatch.setattr(deploy_ibm.auth, "get_authenticator", fail_cloud_call)
    monkeypatch.setattr(deploy_ibm.code_engine, "deploy_application", fail_cloud_call)
    monkeypatch.setattr(deploy_ibm.reporter, "start_deployment_check", fake_start)
    monkeypatch.setattr(deploy_ibm.reporter, "complete_deployment_check", fake_complete)

    assert deploy_ibm.main() == 0
    assert calls["start"] == 1
    assert calls["complete"] == 1
