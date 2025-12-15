#!/usr/bin/env python3
"""
IBMCloudVercel - Main deployment script.

This script orchestrates the deployment of Vercel projects to IBM Cloud Code Engine.
It is designed to run in the Vercel build environment as a custom build command.
"""

import sys
from pathlib import Path

# Add src directory to Python path for local development
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

from ibm_cloud_vercel.core.config import load_config
from ibm_cloud_vercel.sdk import auth, cos


def main() -> int:
    """
    Main deployment workflow.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    print("=" * 70)
    print("IBMCloudVercel - Deploying to IBM Cloud Code Engine")
    print("=" * 70)

    try:
        # Step 1: Load and validate configuration
        print("\n[1/4] Loading configuration...")
        config = load_config()

        print(f"  Region: {config.ibm_cloud.region}")
        print(f"  Project ID: {config.ibm_cloud.project_id}")
        print(f"  COS Bucket: {config.ibm_cloud.cos_bucket}")
        print(f"  App Name: {config.vercel.get_app_name()}")
        print(f"  Git Ref: {config.vercel.git_commit_ref}")
        print(f"  Commit SHA: {config.vercel.git_commit_sha[:8]}")

        # Step 2: Authenticate with IBM Cloud
        print("\n[2/4] Authenticating with IBM Cloud...")
        authenticator = auth.get_authenticator(
            trusted_profile_id=config.ibm_cloud.trusted_profile_id
        )
        print("  ✓ Authentication successful")

        # Step 3: Upload source code to COS
        print("\n[3/4] Uploading source code to IBM Cloud Object Storage...")

        cos_uploader = cos.create_cos_uploader(
            authenticator=authenticator,
            region=config.ibm_cloud.region,
            bucket_name=config.ibm_cloud.cos_bucket,
            endpoint=config.ibm_cloud.cos_endpoint,
        )

        cos_uri, zip_path = cos_uploader.upload_source_code(
            source_dir=config.source_dir,
            deployment_id=config.vercel.deployment_id,
        )

        print(f"  Source uploaded: {cos_uri}")

        # Step 4: Deploy to Code Engine (to be implemented in Phase 2)
        print("\n[4/4] Deploying to Code Engine...")
        print("  ⚠️  Code Engine deployment not yet implemented (Phase 2)")
        print(f"  Next step: Use {cos_uri} to create/update Code Engine application")

        # Success
        print("\n" + "=" * 70)
        print("Phase 1 Complete! Source code uploaded to COS.")
        print("=" * 70)

        # Cleanup (optional)
        if config.cleanup_artifacts:
            print(f"\nCleaning up local artifact: {zip_path}")
            Path(zip_path).unlink(missing_ok=True)

        return 0

    except FileNotFoundError as e:
        print(f"\n❌ Configuration Error: {e}", file=sys.stderr)
        print("\nMake sure you have created 'ibmcloudvercel.yml' in your project root.")
        print("See ibmcloudvercel.example.yml for a template.")
        return 1

    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"\n❌ Deployment Failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
