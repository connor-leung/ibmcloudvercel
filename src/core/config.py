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
    cos_bucket: Optional[str] = None
    cos_endpoint: Optional[str] = None
    registry_secret: Optional[str] = None
    trusted_profile_id: Optional[str] = None  # For OIDC authentication
    # Build configuration
    registry_namespace: Optional[str] = None  # ICR namespace for built images
    build_strategy: str = "buildpacks"  # "dockerfile" or "buildpacks"
    build_size: str = "medium"  # "small", "medium", "large", "xlarge"
    build_timeout: int = 600  # seconds
    dockerfile_path: Optional[str] = None  # Path to Dockerfile if using dockerfile strategy

    def __post_init__(self) -> None:
        """Auto-detect endpoints and validate configuration."""
        # Auto-detect COS endpoint if not provided
        if not self.cos_endpoint:
            self.cos_endpoint = f"s3.{self.region}.cloud-object-storage.appdomain.cloud"

    def get_output_image(self, app_name: str, tag: str) -> str:
        """Generate the output image reference for a build."""
        # Use IBM Container Registry (ICR)
        icr_region = self.region if self.region != "us-south" else "us"
        namespace = self.registry_namespace or "code-engine"
        return f"private.{icr_region}.icr.io/{namespace}/{app_name}:{tag}"


@dataclass
class VercelConfig:
    """Vercel-specific configuration and environment variables."""

    git_commit_sha: str
    git_commit_ref: str
    git_repo_url: str
    git_provider: str
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

        # Git provider and repo info
        git_provider = os.getenv("VERCEL_GIT_PROVIDER", "github")
        git_repo_slug = os.getenv("VERCEL_GIT_REPO_SLUG", "")

        # Construct full git URL based on provider
        if git_repo_slug:
            provider_urls = {
                "github": f"https://github.com/{git_repo_slug}",
                "gitlab": f"https://gitlab.com/{git_repo_slug}",
                "bitbucket": f"https://bitbucket.org/{git_repo_slug}",
            }
            git_repo_url = provider_urls.get(git_provider, f"https://github.com/{git_repo_slug}")
        else:
            git_repo_url = ""

        return cls(
            git_commit_sha=git_commit_sha,
            git_commit_ref=git_commit_ref,
            git_repo_url=git_repo_url,
            git_provider=git_provider,
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
            cos_bucket=ibm_config_data.get("cos_bucket"),
            cos_endpoint=ibm_config_data.get("cos_endpoint"),
            registry_secret=ibm_config_data.get("registry_secret"),
            trusted_profile_id=ibm_config_data.get("trusted_profile_id"),
            registry_namespace=ibm_config_data.get("registry_namespace"),
            build_strategy=ibm_config_data.get("build_strategy", "buildpacks"),
            build_size=ibm_config_data.get("build_size", "medium"),
            build_timeout=ibm_config_data.get("build_timeout", 600),
            dockerfile_path=ibm_config_data.get("dockerfile_path"),
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
