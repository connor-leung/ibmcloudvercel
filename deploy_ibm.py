#!/usr/bin/env python3
"""
IBMCloudVercel - Main deployment script.

This script orchestrates the deployment of Vercel projects to IBM Cloud Code Engine.
It is designed to run in the Vercel build environment as a custom build command.

Exit Codes:
    0   - Success
    1   - Generic/unknown error
    10  - Configuration error
    20  - Authentication error
    30  - COS upload error
    40  - Code Engine error
    50  - Vercel API error
    130 - Cancelled by user (SIGINT)
"""

import sys
from pathlib import Path

# Auto-load .env file for local development
from dotenv import load_dotenv
load_dotenv()

# Add src directory to Python path for local development
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

from core import reporter
from core.config import load_config
from core.exceptions import (
    IBMCloudVercelError,
    ConfigurationError,
    AuthenticationError,
    CodeEngineError,
)
from sdk import auth, code_engine


# Global config reference for error reporting
_config = None


def _report_failure(error: Exception) -> None:
    """Report deployment failure to Vercel Checks API."""
    global _config
    if _config is None:
        return

    error_message = str(error)
    if isinstance(error, IBMCloudVercelError) and error.details:
        error_message = f"{error.message}: {error.details}"

    reporter.complete_deployment_check(
        deployment_id=_config.vercel.deployment_id,
        token=_config.vercel.checks_token,
        status="failed",
        error=error_message,
    )


def main() -> int:
    """
    Main deployment workflow.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    global _config

    print("=" * 70)
    print("IBMCloudVercel - Deploying to IBM Cloud Code Engine")
    print("=" * 70)

    try:
        # Step 1: Load and validate configuration
        print("\n[1/4] Loading configuration...")
        try:
            _config = load_config()
        except FileNotFoundError as e:
            raise ConfigurationError(
                "Configuration file not found",
                details="Create 'ibmcloudvercel.yml' in your project root. "
                        "See ibmcloudvercel.example.yml for a template."
            ) from e
        except ValueError as e:
            raise ConfigurationError("Invalid configuration", details=str(e)) from e

        app_name = _config.vercel.get_app_name()
        print(f"  Region: {_config.ibm_cloud.region}")
        print(f"  Project ID: {_config.ibm_cloud.project_id}")
        print(f"  App Name: {app_name}")
        print(f"  Git Repo: {_config.vercel.git_repo_url}")
        print(f"  Git Ref: {_config.vercel.git_commit_ref}")
        print(f"  Commit SHA: {_config.vercel.git_commit_sha[:8]}")
        print(f"  Build Strategy: {_config.ibm_cloud.build_strategy}")

        # Validate git repo URL is available
        if not _config.vercel.git_repo_url:
            raise ConfigurationError(
                "Git repository URL not available",
                details="Set VERCEL_GIT_REPO_SLUG environment variable or run in Vercel environment."
            )

        # Step 2: Authenticate with IBM Cloud
        print("\n[2/6] Authenticating with IBM Cloud...")
        try:
            authenticator = auth.get_authenticator(
                trusted_profile_id=_config.ibm_cloud.trusted_profile_id
            )
        except ValueError as e:
            raise AuthenticationError("Authentication failed", details=str(e)) from e
        except Exception as e:
            raise AuthenticationError(
                "IBM Cloud authentication failed", details=str(e)
            ) from e
        print("  ✓ Authentication successful")

        # Step 3: Validate Code Engine project access
        print("\n[3/6] Validating Code Engine project...")
        try:
            resolved_project_id = code_engine.validate_project_access(
                authenticator=authenticator,
                region=_config.ibm_cloud.region,
                project_id_or_name=_config.ibm_cloud.project_id,
            )
            # Update config with resolved project ID if it was a name
            if resolved_project_id != _config.ibm_cloud.project_id:
                _config.ibm_cloud.project_id = resolved_project_id
        except ValueError as e:
            # Invalid project name format
            raise ConfigurationError(
                "Invalid Code Engine project name",
                details=str(e)
            ) from e
        except RuntimeError as e:
            raise CodeEngineError(
                "Code Engine project validation failed",
                details=str(e)
            ) from e
        print(f"  ✓ Project validated: {resolved_project_id}")

        # Step 4: Notify Vercel that deployment checks started
        print("\n[4/6] Notifying Vercel Checks API...")
        reporter.start_deployment_check(
            deployment_id=_config.vercel.deployment_id,
            token=_config.vercel.checks_token,
        )

        # Create Code Engine client for build and deploy
        ce_client = code_engine.create_code_engine_client(
            authenticator=authenticator,
            region=_config.ibm_cloud.region,
        )

        # Step 5: Create/update build configuration and run build
        print("\n[5/6] Building container image...")
        build_name = f"{app_name}-build"
        output_image = _config.ibm_cloud.get_output_image(
            app_name=app_name,
            tag=_config.vercel.git_commit_sha[:8],
        )

        # Check if registry_secret is configured
        if not _config.ibm_cloud.registry_secret:
            raise ConfigurationError(
                "Registry secret not configured",
                details="Set 'registry_secret' in ibmcloudvercel.yml to the name of your "
                        "Code Engine secret with ICR credentials. Create one with: "
                        "ibmcloud ce secret create --name icr-secret --format registry "
                        "--server private.us.icr.io --username iamapikey --password <API_KEY>"
            )

        try:
            # Create or update the build configuration
            print(f"  Creating build configuration: {build_name}")
            code_engine.create_build(
                client=ce_client,
                project_id=resolved_project_id,
                name=build_name,
                source_url=_config.vercel.git_repo_url,
                source_revision=_config.vercel.git_commit_sha,
                output_image=output_image,
                output_secret=_config.ibm_cloud.registry_secret,
                strategy_type=_config.ibm_cloud.build_strategy,
                strategy_size=_config.ibm_cloud.build_size,
                source_context_dir=_config.source_dir if _config.source_dir != "." else "",
                strategy_spec_file=_config.ibm_cloud.dockerfile_path or "",
                timeout=_config.ibm_cloud.build_timeout,
            )
            print(f"  ✓ Build configuration ready")

            # Run the build
            print(f"  Starting build...")
            code_engine.run_build(
                client=ce_client,
                project_id=resolved_project_id,
                build_name=build_name,
                timeout=_config.ibm_cloud.build_timeout,
                poll_interval=15,
            )
            print(f"  ✓ Image built: {output_image}")

        except RuntimeError as e:
            raise CodeEngineError("Build failed", details=str(e)) from e

        # Step 6: Deploy the application
        print("\n[6/6] Deploying application to Code Engine...")
        try:
            app = code_engine.deploy_app(
                client=ce_client,
                project_id=resolved_project_id,
                name=app_name,
                image_reference=output_image,
                image_port=_config.scaling.port,
                scale_min_instances=_config.scaling.min_scale,
                scale_max_instances=_config.scaling.max_scale,
                scale_cpu_limit=_config.scaling.cpu,
                scale_memory_limit=_config.scaling.memory,
                scale_concurrency=_config.scaling.concurrency,
            )
            app_url = code_engine.get_app_url(app)
            print(f"  ✓ Application deployed: {app_url}")

        except RuntimeError as e:
            raise CodeEngineError("Application deployment failed", details=str(e)) from e

        # Report success to Vercel
        reporter.complete_deployment_check(
            deployment_id=_config.vercel.deployment_id,
            token=_config.vercel.checks_token,
            status="succeeded",
            url=app_url,
        )

        # Success
        print("\n" + "=" * 70)
        print("✅ Deployment Complete!")
        print(f"   Application URL: {app_url}")
        print("=" * 70)

        return 0

    except ConfigurationError as e:
        print(f"\n❌ Configuration Error (exit code {e.exit_code})", file=sys.stderr)
        print(f"   {e}", file=sys.stderr)
        _report_failure(e)
        return e.exit_code

    except AuthenticationError as e:
        print(f"\n❌ Authentication Error (exit code {e.exit_code})", file=sys.stderr)
        print(f"   {e}", file=sys.stderr)
        _report_failure(e)
        return e.exit_code

    except CodeEngineError as e:
        print(f"\n❌ Code Engine Error (exit code {e.exit_code})", file=sys.stderr)
        print(f"   {e}", file=sys.stderr)
        _report_failure(e)
        return e.exit_code

    except IBMCloudVercelError as e:
        print(f"\n❌ Deployment Error (exit code {e.exit_code})", file=sys.stderr)
        print(f"   {e}", file=sys.stderr)
        _report_failure(e)
        return e.exit_code

    except KeyboardInterrupt:
        print("\n\n⚠️  Deployment cancelled by user.", file=sys.stderr)
        _report_failure(Exception("Deployment cancelled by user"))
        return 130  # Standard exit code for SIGINT

    except Exception as e:
        print(f"\n❌ Unexpected Error (exit code 1)", file=sys.stderr)
        print(f"   {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        _report_failure(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
