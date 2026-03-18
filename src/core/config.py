"""Configuration parser and validator for IBMCloudVercel."""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


# Pattern to match ${VAR_NAME} or ${VAR_NAME:-default}
ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def expand_env_vars(value: str) -> str:
    """
    Expand environment variables in a string.

    Supports:
        ${VAR_NAME} - replaced with env var value, empty string if not set
        ${VAR_NAME:-default} - replaced with env var value, or 'default' if not set

    Args:
        value: String potentially containing ${VAR_NAME} patterns

    Returns:
        String with environment variables expanded
    """
    def replace_match(match: re.Match) -> str:
        var_name = match.group(1)
        default_value = match.group(2) if match.group(2) is not None else ""
        return os.getenv(var_name, default_value)

    return ENV_VAR_PATTERN.sub(replace_match, value)


def expand_env_vars_in_data(data: Any) -> Any:
    """
    Recursively expand environment variables in a data structure.

    Args:
        data: Any data structure (dict, list, str, etc.)

    Returns:
        Data structure with all string values having env vars expanded
    """
    if isinstance(data, dict):
        return {key: expand_env_vars_in_data(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [expand_env_vars_in_data(item) for item in data]
    elif isinstance(data, str):
        return expand_env_vars(data)
    else:
        return data


@dataclass
class ScalingConfig:
    """Code Engine application scaling configuration."""

    min_scale: int = 0
    max_scale: int = 10
    cpu: str = "0.25"
    memory: str = "0.5G"
    port: int = 8080
    concurrency: int = 100


@dataclass
class IBMCloudConfig:
    """IBM Cloud configuration and credentials."""

    region: str
    project_id: str
    registry_secret: Optional[str] = None
    git_source_secret: Optional[str] = None  # For private GitHub repos
    trusted_profile_id: Optional[str] = None  # For OIDC authentication


@dataclass
class VercelConfig:
    """Vercel-specific configuration and environment variables."""

    git_commit_sha: str
    git_commit_ref: str
    deployment_id: str
    project_name: str
    checks_token: Optional[str] = None
    git_repo_owner: str = ""
    git_repo_slug: str = ""

    @classmethod
    def from_environment(cls) -> "VercelConfig":
        """Load Vercel configuration from environment variables."""
        git_commit_sha = os.getenv("VERCEL_GIT_COMMIT_SHA", "unknown")
        git_commit_ref = os.getenv("VERCEL_GIT_COMMIT_REF", "main")
        deployment_id = os.getenv("VERCEL_DEPLOYMENT_ID", "local")
        project_name = os.getenv("VERCEL_PROJECT_NAME", "app")
        checks_token = os.getenv("VERCEL_CHECKS_TOKEN")
        git_repo_owner = os.getenv("VERCEL_GIT_REPO_OWNER", "")
        git_repo_slug = os.getenv("VERCEL_GIT_REPO_SLUG", "")

        return cls(
            git_commit_sha=git_commit_sha,
            git_commit_ref=git_commit_ref,
            deployment_id=deployment_id,
            project_name=project_name,
            checks_token=checks_token,
            git_repo_owner=git_repo_owner,
            git_repo_slug=git_repo_slug,
        )

    def get_app_name(self) -> str:
        """Generate a Code Engine app name based on the git branch.

        Code Engine app names must be valid RFC 1123 DNS labels: lowercase alphanumeric
        and hyphens only, max 63 chars, must start with a letter. Git branch names like
        "feature/my-branch" or "dependabot/npm_and_yarn/lodash" would be rejected as-is.
        """
        raw_ref = self.git_commit_ref or "main"
        sanitized_ref = raw_ref.lower().replace("/", "-").replace("_", "-")
        sanitized_ref = re.sub(r"[^a-z0-9-]", "-", sanitized_ref)
        sanitized_ref = re.sub(r"-{2,}", "-", sanitized_ref).strip("-")

        if not sanitized_ref:
            sanitized_ref = "app"

        # DNS labels must start with a letter, not a digit or hyphen.
        if not sanitized_ref[0].isalpha():
            sanitized_ref = f"app-{sanitized_ref}"

        return f"{self.project_name}-{sanitized_ref}"[:63]  # RFC 1123 max label length


@dataclass
class DeploymentConfig:
    """Complete deployment configuration combining all settings."""

    ibm_cloud: IBMCloudConfig
    scaling: ScalingConfig
    vercel: VercelConfig
    source_dir: str = "."

    @classmethod
    def from_yaml(cls, config_path: str = "ibmcloudvercel.yml") -> "DeploymentConfig":
        """
        Load and validate configuration from YAML file.

        Args:
            config_path: Path to the configuration YAML file

        Returns:
            DeploymentConfig instance with validated settings

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If required fields are missing or invalid
        """
        config_file = Path(config_path)

        if not config_file.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}\n"
                "Create an ibmcloudvercel.yml file in your project root."
            )

        with open(config_file, "r") as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Configuration file is empty: {config_path}")

        # Expand environment variables in all string values
        data = expand_env_vars_in_data(data)

        # Validate required sections
        if "ibm_cloud" not in data:
            raise ValueError("Missing required 'ibm_cloud' section in configuration")

        # Parse IBM Cloud config
        ibm_config_data = data["ibm_cloud"]
        required_fields = ["region", "project_id"]
        missing_fields = [f for f in required_fields if f not in ibm_config_data]

        if missing_fields:
            raise ValueError(
                f"Missing required fields in 'ibm_cloud' section: {', '.join(missing_fields)}"
            )

        ibm_cloud = IBMCloudConfig(
            region=ibm_config_data["region"],
            project_id=ibm_config_data["project_id"],
            registry_secret=ibm_config_data.get("registry_secret"),
            git_source_secret=ibm_config_data.get("git_source_secret"),
            trusted_profile_id=ibm_config_data.get("trusted_profile_id"),
        )

        # Parse scaling config (optional, uses defaults if not provided)
        scaling_data = data.get("scaling", {})
        scaling = ScalingConfig(
            min_scale=scaling_data.get("min_scale", 0),
            max_scale=scaling_data.get("max_scale", 10),
            cpu=scaling_data.get("cpu", "0.25"),
            memory=scaling_data.get("memory", "0.5G"),
            port=scaling_data.get("port", 8080),
            concurrency=scaling_data.get("concurrency", 100),
        )

        # Load Vercel config from environment
        vercel = VercelConfig.from_environment()

        # Parse deployment options
        source_dir = data.get("source_dir", ".")

        return cls(
            ibm_cloud=ibm_cloud,
            scaling=scaling,
            vercel=vercel,
            source_dir=source_dir,
        )


def load_config(config_path: str = "ibmcloudvercel.yml") -> DeploymentConfig:
    """
    Convenience function to load configuration.

    Args:
        config_path: Path to the configuration YAML file

    Returns:
        DeploymentConfig instance
    """
    return DeploymentConfig.from_yaml(config_path)
