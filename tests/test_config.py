from __future__ import annotations

from pathlib import Path

from core.config import DeploymentConfig, VercelConfig, expand_env_vars, load_config


def test_expand_env_vars_supports_default(monkeypatch) -> None:
    monkeypatch.delenv("MISSING", raising=False)
    monkeypatch.setenv("SET_VALUE", "hello")

    value = "a=${SET_VALUE};b=${MISSING:-fallback};c=${MISSING}"
    assert expand_env_vars(value) == "a=hello;b=fallback;c="


def test_from_yaml_expands_env_and_loads_fields(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "ibmcloudvercel.yml"
    monkeypatch.setenv("REGION", "us-south")
    monkeypatch.setenv("PROJECT_ID", "project-123")
    config_file.write_text(
        "\n".join(
            [
                "ibm_cloud:",
                "  region: \"${REGION}\"",
                "  project_id: \"${PROJECT_ID}\"",
                "scaling:",
                "  min_scale: 1",
            ]
        ),
        encoding="utf-8",
    )

    config = DeploymentConfig.from_yaml(str(config_file))
    assert config.ibm_cloud.region == "us-south"
    assert config.ibm_cloud.project_id == "project-123"
    assert config.scaling.min_scale == 1


def test_from_environment_builds_config(monkeypatch) -> None:
    monkeypatch.setenv("IBM_CLOUD_REGION", "eu-de")
    monkeypatch.setenv("IBM_CODE_ENGINE_PROJECT_ID", "proj-env-123")
    monkeypatch.setenv("IBM_REGISTRY_SECRET", "dockerhub-push")
    monkeypatch.setenv("IBM_CODE_ENGINE_SOURCE_DIR", "welcome-image")

    config = DeploymentConfig.from_environment()
    assert config.ibm_cloud.region == "eu-de"
    assert config.ibm_cloud.project_id == "proj-env-123"
    assert config.ibm_cloud.registry_secret == "dockerhub-push"
    assert config.source_dir == "welcome-image"


def test_load_config_falls_back_to_environment_when_no_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IBM_CODE_ENGINE_PROJECT_ID", "proj-fallback")
    config = load_config(str(tmp_path / "nonexistent.yml"))
    assert config.ibm_cloud.project_id == "proj-fallback"


def test_branch_name_is_sanitized_for_code_engine() -> None:
    vercel = VercelConfig(
        git_commit_sha="abc123",
        git_commit_ref="feature/ABC_123.fix",
        deployment_id="dep_1",
        project_name="myproj",
        checks_token=None,
    )

    assert vercel.get_app_name() == "myproj-feature-abc-123-fix"
