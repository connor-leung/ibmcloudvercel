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
import os
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
    COSUploadError,
    CodeEngineError,
)
from sdk import auth, cos, code_engine


# Global config reference for error reporting
_config = None


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_dry_run_enabled() -> bool:
    return _is_truthy(os.getenv("IBM_CLOUD_VERCEL_DRY_RUN"))


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"  ⚠️  Invalid {name}='{raw}', using default {default}.")
        return default
    if value <= 0:
        print(f"  ⚠️  Invalid {name}='{raw}', using default {default}.")
        return default
    return value


def _validate_runtime_requirements(*, dry_run: bool = False) -> None:
    """Validate required config and environment values before cloud operations."""
    global _config
    if _config is None:
        raise ConfigurationError("Configuration is not loaded")

    missing_config: list[str] = []
    if not _config.ibm_cloud.project_id:
        missing_config.append("ibm_cloud.project_id")
    if not _config.ibm_cloud.cos_bucket:
        missing_config.append("ibm_cloud.cos_bucket")

    if missing_config:
        raise ConfigurationError(
            "Missing required IBM Cloud configuration values",
            details=", ".join(missing_config),
        )

    if dry_run:
        return

    has_oidc = bool(_config.ibm_cloud.trusted_profile_id and os.getenv("VERCEL_OIDC_TOKEN"))
    has_api_key = bool(os.getenv("IBM_CLOUD_API_KEY"))
    if not has_oidc and not has_api_key:
        raise ConfigurationError(
            "No valid IBM authentication source found",
            details=(
                "Set VERCEL_OIDC_TOKEN and ibm_cloud.trusted_profile_id for OIDC, "
                "or set IBM_CLOUD_API_KEY as fallback."
            ),
        )

    if not os.getenv("IBM_COS_SERVICE_INSTANCE_ID"):
        raise ConfigurationError(
            "Missing IBM Cloud Object Storage service instance ID",
            details=(
                "Set IBM_COS_SERVICE_INSTANCE_ID (COS CRN). "
                "This is required for COS upload operations."
            ),
        )


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
    zip_path = None  # Track for cleanup on failure

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

        print(f"  Region: {_config.ibm_cloud.region}")
        print(f"  Project ID: {_config.ibm_cloud.project_id}")
        print(f"  COS Bucket: {_config.ibm_cloud.cos_bucket}")
        print(f"  App Name: {_config.vercel.get_app_name()}")
        print(f"  Git Ref: {_config.vercel.git_commit_ref}")
        print(f"  Commit SHA: {_config.vercel.git_commit_sha[:8]}")
        dry_run = _is_dry_run_enabled()
        if dry_run:
            print("  ⚙️  Dry-run mode enabled (IBM_CLOUD_VERCEL_DRY_RUN=true)")
        _validate_runtime_requirements(dry_run=dry_run)

        if dry_run:
            print("\n[dry-run] Validating deployment plan without mutating cloud resources...")
            app_name = _config.vercel.get_app_name()
            image_reference = (
                os.getenv("IBM_CODE_ENGINE_IMAGE_REFERENCE")
                or os.getenv("IBM_CODE_ENGINE_IMAGE")
                or "dry-run/local-image:latest"
            )
            app_payload = code_engine.build_code_engine_app_payload(
                name=app_name,
                image_reference=image_reference,
                scaling=_config.scaling,
                registry_secret=_config.ibm_cloud.registry_secret,
            )
            print(f"  ✓ Generated Code Engine app payload for: {app_payload['name']}")
            print(
                "  ✓ Planned COS upload target: "
                f"cos://{_config.ibm_cloud.cos_bucket}/deployments/{_config.vercel.deployment_id}/..."
            )
            reporter.start_deployment_check(
                deployment_id=_config.vercel.deployment_id,
                token=_config.vercel.checks_token,
                summary="Dry-run: validating deployment plan without cloud mutations.",
            )
            reporter.complete_deployment_check(
                deployment_id=_config.vercel.deployment_id,
                token=_config.vercel.checks_token,
                status="succeeded",
                url=None,
                details="Dry-run mode completed. No IBM Cloud resources were created or updated.",
            )
            print("\n" + "=" * 70)
            print("✅ Dry-run complete. Configuration and payload generation succeeded.")
            print("=" * 70)
            return 0

        # Step 2: Authenticate with IBM Cloud
        print("\n[2/4] Authenticating with IBM Cloud...")
        try:
            authenticator = auth.get_authenticator(
                trusted_profile_id=_config.ibm_cloud.trusted_profile_id
            )
        except ValueError as e:
            raise AuthenticationError("Authentication failed", details=str(e)) from e
        except RuntimeError as e:
            raise AuthenticationError(
                "IBM IAM token exchange failed",
                details=str(e),
            ) from e
        except Exception as e:
            raise AuthenticationError(
                "IBM Cloud authentication failed", details=str(e)
            ) from e
        print("  ✓ Authentication successful")

        # Step 3: Notify Vercel that deployment checks started
        print("\n[3/4] Notifying Vercel Checks API...")
        reporter.start_deployment_check(
            deployment_id=_config.vercel.deployment_id,
            token=_config.vercel.checks_token,
        )

        # Step 4: Upload source code to COS
        print("\n[4/5] Uploading source code to IBM Cloud Object Storage...")
        try:
            cos_uploader = cos.create_cos_uploader(
                authenticator=authenticator,
                region=_config.ibm_cloud.region,
                bucket_name=_config.ibm_cloud.cos_bucket,
                endpoint=_config.ibm_cloud.cos_endpoint,
            )

            cos_uri, zip_path = cos_uploader.upload_source_code(
                source_dir=_config.source_dir,
                deployment_id=_config.vercel.deployment_id,
            )
        except RuntimeError as e:
            error_msg = str(e)
            if "NoSuchBucket" in error_msg:
                raise COSUploadError(
                    "COS bucket not found",
                    details=f"Bucket '{_config.ibm_cloud.cos_bucket}' does not exist. "
                            "Create it in IBM Cloud Object Storage first."
                ) from e
            elif "AccessDenied" in error_msg:
                raise COSUploadError(
                    "COS access denied",
                    details="Check that your API key has write permissions to the bucket."
                ) from e
            elif "IBM_COS_SERVICE_INSTANCE_ID is required" in error_msg:
                raise COSUploadError(
                    "COS configuration missing required service instance ID",
                    details=error_msg,
                ) from e
            else:
                raise COSUploadError("Failed to upload to COS", details=error_msg) from e
        except ValueError as e:
            raise COSUploadError("Invalid COS configuration", details=str(e)) from e
        except Exception as e:
            raise COSUploadError("COS upload failed", details=str(e)) from e

        print(f"  ✓ Source uploaded: {cos_uri}")

        # Step 5: Deploy app to Code Engine and wait for ready status
        print("\n[5/5] Deploying application to IBM Cloud Code Engine...")
        app_name = _config.vercel.get_app_name()
        image_reference = (
            os.getenv("IBM_CODE_ENGINE_IMAGE_REFERENCE")
            or os.getenv("IBM_CODE_ENGINE_IMAGE")
        )
        if not image_reference:
            raise CodeEngineError(
                "Code Engine image reference is not configured",
                details=(
                    "Set IBM_CODE_ENGINE_IMAGE_REFERENCE (or IBM_CODE_ENGINE_IMAGE) "
                    "to the container image to deploy."
                ),
            )

        try:
            app_payload = code_engine.build_code_engine_app_payload(
                name=app_name,
                image_reference=image_reference,
                scaling=_config.scaling,
                registry_secret=_config.ibm_cloud.registry_secret,
            )

            app_data, public_url = code_engine.deploy_application(
                authenticator=authenticator,
                region=_config.ibm_cloud.region,
                project_id=_config.ibm_cloud.project_id,
                app_name=app_name,
                payload=app_payload,
                poll_interval=_get_int_env("IBM_CODE_ENGINE_POLL_INTERVAL", 5),
                poll_timeout=_get_int_env("IBM_CODE_ENGINE_POLL_TIMEOUT", 600),
                poll_request_timeout=_get_int_env("IBM_CODE_ENGINE_POLL_REQUEST_TIMEOUT", 10),
            )
        except CodeEngineError:
            raise
        except Exception as e:
            raise CodeEngineError(
                "Code Engine deployment failed",
                details=(
                    "Unexpected error while calling Code Engine API. "
                    f"{str(e)}"
                ),
            ) from e

        print(f"  ✓ Code Engine app ready: {app_data.get('name', app_name)}")
        if public_url:
            print(f"  ✓ Public URL: {public_url}")
        else:
            print("  ⚠️  App is ready, but no public endpoint was returned by Code Engine.")

        # Report success to Vercel
        reporter.complete_deployment_check(
            deployment_id=_config.vercel.deployment_id,
            token=_config.vercel.checks_token,
            status="succeeded",
            url=public_url,
        )

        # Success
        print("\n" + "=" * 70)
        print("✅ Deployment complete! Application is running on Code Engine.")
        if public_url:
            print(f"   URL: {public_url}")
        print("=" * 70)

        # Cleanup (optional)
        if _config.cleanup_artifacts and zip_path:
            print(f"\nCleaning up local artifact: {zip_path}")
            Path(zip_path).unlink(missing_ok=True)

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

    except COSUploadError as e:
        print(f"\n❌ COS Upload Error (exit code {e.exit_code})", file=sys.stderr)
        print(f"   {e}", file=sys.stderr)
        _report_failure(e)
        if zip_path:
            Path(zip_path).unlink(missing_ok=True)
        return e.exit_code

    except IBMCloudVercelError as e:
        print(f"\n❌ Deployment Error (exit code {e.exit_code})", file=sys.stderr)
        print(f"   {e}", file=sys.stderr)
        _report_failure(e)
        if zip_path:
            Path(zip_path).unlink(missing_ok=True)
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
        if zip_path:
            Path(zip_path).unlink(missing_ok=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
