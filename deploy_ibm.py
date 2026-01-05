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
    COSUploadError,
)
from sdk import auth, cos


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

        # Step 2: Authenticate with IBM Cloud
        print("\n[2/4] Authenticating with IBM Cloud...")
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

        # Step 3: Notify Vercel that deployment checks started
        print("\n[3/4] Notifying Vercel Checks API...")
        reporter.start_deployment_check(
            deployment_id=_config.vercel.deployment_id,
            token=_config.vercel.checks_token,
        )

        # Step 4: Upload source code to COS
        print("\n[4/4] Uploading source code to IBM Cloud Object Storage...")
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
            else:
                raise COSUploadError("Failed to upload to COS", details=error_msg) from e
        except Exception as e:
            raise COSUploadError("COS upload failed", details=str(e)) from e

        print(f"  ✓ Source uploaded: {cos_uri}")

        # Code Engine deployment placeholder (Phase 2)
        print("\n" + "-" * 70)
        print("Deployment artifact ready for Code Engine (Phase 2 pending).")
        print("  ⚠️  Code Engine deployment not yet implemented")
        print(f"  Next step: Use {cos_uri} to create/update Code Engine application")
        print("-" * 70)

        # Report success to Vercel
        reporter.complete_deployment_check(
            deployment_id=_config.vercel.deployment_id,
            token=_config.vercel.checks_token,
            status="succeeded",
            url=None,  # Will be Code Engine URL in Phase 2
        )

        # Success
        print("\n" + "=" * 70)
        print("✅ Phase 1 Complete! Source code uploaded to COS.")
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
