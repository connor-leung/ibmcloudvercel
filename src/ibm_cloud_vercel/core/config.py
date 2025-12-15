"""Configuration parser and validator for IBMCloudVercel."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


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
    cos_bucket: str
    cos_endpoint: Optional[str] = None
    registry_secret: Optional[str] = None
    trusted_profile_id: Optional[str] = None  # For OIDC authentication

    def __post_init__(self) -> None:
        """Auto-detect COS endpoint if not provided."""
        # Auto-detect COS endpoint if not provided
        if not self.cos_endpoint:
            self.cos_endpoint = f"s3.{self.region}.cloud-object-storage.appdomain.cloud"


@dataclass
class VercelConfig:
    """Vercel-specific configuration and environment variables."""

    git_commit_sha: str
    git_commit_ref: str
    deployment_id: str
    project_name: str
    checks_token: Optional[str] = None

    @classmethod
    def from_environment(cls) -> "VercelConfig":
        """Load Vercel configuration from environment variables."""
        git_commit_sha = os.getenv("VERCEL_GIT_COMMIT_SHA", "unknown")
        git_commit_ref = os.getenv("VERCEL_GIT_COMMIT_REF", "main")
        deployment_id = os.getenv("VERCEL_DEPLOYMENT_ID", "local")
        project_name = os.getenv("VERCEL_PROJECT_NAME", "app")
        checks_token = os.getenv("VERCEL_CHECKS_TOKEN")

        return cls(
            git_commit_sha=git_commit_sha,
            git_commit_ref=git_commit_ref,
            deployment_id=deployment_id,
            project_name=project_name,
            checks_token=checks_token,
        )

    def get_app_name(self) -> str:
        """Generate a Code Engine app name based on the git branch."""
        # Sanitize branch name for Code Engine (lowercase, alphanumeric + hyphens)
        sanitized_ref = self.git_commit_ref.lower().replace("/", "-").replace("_", "-")
        # Remove any non-alphanumeric characters except hyphens
        sanitized_ref = "".join(c for c in sanitized_ref if c.isalnum() or c == "-")
        # Ensure it starts with a letter
        if not sanitized_ref[0].isalpha():
            sanitized_ref = "app-" + sanitized_ref

        return f"{self.project_name}-{sanitized_ref}"[:63]  # Code Engine name limit


@dataclass
class DeploymentConfig:
    """Complete deployment configuration combining all settings."""

    ibm_cloud: IBMCloudConfig
    scaling: ScalingConfig
    vercel: VercelConfig
    source_dir: str = "."
    cleanup_artifacts: bool = True

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

        # Validate required sections
        if "ibm_cloud" not in data:
            raise ValueError("Missing required 'ibm_cloud' section in configuration")

        # Parse IBM Cloud config
        ibm_config_data = data["ibm_cloud"]
        required_fields = ["region", "project_id", "cos_bucket"]
        missing_fields = [f for f in required_fields if f not in ibm_config_data]

        if missing_fields:
            raise ValueError(
                f"Missing required fields in 'ibm_cloud' section: {', '.join(missing_fields)}"
            )

        ibm_cloud = IBMCloudConfig(
            region=ibm_config_data["region"],
            project_id=ibm_config_data["project_id"],
            cos_bucket=ibm_config_data["cos_bucket"],
            cos_endpoint=ibm_config_data.get("cos_endpoint"),
            registry_secret=ibm_config_data.get("registry_secret"),
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
        cleanup_artifacts = data.get("cleanup_artifacts", True)

        return cls(
            ibm_cloud=ibm_cloud,
            scaling=scaling,
            vercel=vercel,
            source_dir=source_dir,
            cleanup_artifacts=cleanup_artifacts,
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
