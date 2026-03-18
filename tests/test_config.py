from __future__ import annotations

from pathlib import Path

from core.config import DeploymentConfig, VercelConfig, expand_env_vars


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


def test_branch_name_is_sanitized_for_code_engine() -> None:
    vercel = VercelConfig(
        git_commit_sha="abc123",
        git_commit_ref="feature/ABC_123.fix",
        deployment_id="dep_1",
        project_name="myproj",
        checks_token=None,
    )

    assert vercel.get_app_name() == "myproj-feature-abc-123-fix"
