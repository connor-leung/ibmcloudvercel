"""IBM Cloud Object Storage (COS) SDK wrapper for source code upload."""

import os
import zipfile
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

import ibm_boto3
from ibm_botocore.client import Config
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator


DEFAULT_EXCLUDE_PATTERNS = [
    ".git",
    ".gitmodules",
    ".github",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "venv",
    ".env",
    ".env.local",
    "node_modules",
    ".next",
    ".vercel",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.log",
    "*.tmp",
    "*.swp",
    ".DS_Store",
    "dist",
    "build",
    "coverage",
]


class COSUploader:
    """Handles zipping and uploading source code to IBM Cloud Object Storage."""

    def __init__(
        self,
        authenticator: IAMAuthenticator,
        service_instance_id: str,
        endpoint: str,
        bucket_name: str,
    ) -> None:
        """
        Initialize the COS uploader.

        Args:
            authenticator: IBM Cloud IAM authenticator
            service_instance_id: COS service instance ID (CRN)
            endpoint: COS endpoint URL
            bucket_name: Target bucket name
        """
        self.bucket_name = bucket_name
        self.endpoint = endpoint

        # Initialize IBM COS client using the authenticator
        self.client = ibm_boto3.client(
            "s3",
            ibm_api_key_id=authenticator.token_manager.apikey,
            ibm_service_instance_id=service_instance_id,
            config=Config(signature_version="oauth"),
            endpoint_url=f"https://{endpoint}",
        )

    def create_source_archive(
        self,
        source_dir: str,
        output_path: Optional[str] = None,
        exclude_patterns: Optional[list[str]] = None,
    ) -> str:
        """
        Create a zip archive of the source directory.

        Args:
            source_dir: Directory to zip
            output_path: Optional custom output path for the zip file
            exclude_patterns: List of patterns to exclude (e.g., ['.git', 'node_modules'])

        Returns:
            Path to the created zip file
        """
        if exclude_patterns is None:
            exclude_patterns = DEFAULT_EXCLUDE_PATTERNS.copy()

        source_path = Path(source_dir).resolve()

        if not source_path.exists():
            raise FileNotFoundError(f"Source directory not found: {source_dir}")

        # Generate output path if not provided
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = f"/tmp/source_{timestamp}.zip"

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        def should_exclude(file_path: Path) -> bool:
            """Check if file should be excluded based on glob/base-name rules."""
            relative_path = file_path.relative_to(source_path)
            relative_str = relative_path.as_posix()
            parts = relative_path.parts

            for pattern in exclude_patterns:
                # Base-name pattern: treat as directory/file name exclusion if no globbing tokens
                has_glob = any(token in pattern for token in ("*", "?", "[", "]"))
                if not has_glob:
                    if pattern in parts:
                        return True
                    continue

                # Glob-aware checks (match both the filename and relative path)
                if fnmatch(file_path.name, pattern) or fnmatch(relative_str, pattern):
                    return True

            return False

        # Create the zip archive
        with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zipf:
            for item in source_path.rglob("*"):
                if item.is_file() and not should_exclude(item):
                    arcname = item.relative_to(source_path)
                    zipf.write(item, arcname)

        file_size = output_file.stat().st_size
        print(f"Created source archive: {output_file} ({file_size / 1024 / 1024:.2f} MB)")

        return str(output_file)

    def upload_file(
        self,
        file_path: str,
        object_name: Optional[str] = None,
    ) -> str:
        """
        Upload a file to COS.

        Args:
            file_path: Local file path to upload
            object_name: Optional custom object name in COS (defaults to filename)

        Returns:
            COS URI in format: cos://bucket/object_name
        """
        file_to_upload = Path(file_path)

        if not file_to_upload.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Use filename as object name if not provided
        if object_name is None:
            object_name = file_to_upload.name

        print(f"Uploading {file_path} to COS bucket '{self.bucket_name}' as '{object_name}'...")

        try:
            # Upload the file
            with open(file_to_upload, "rb") as f:
                self.client.upload_fileobj(
                    Fileobj=f,
                    Bucket=self.bucket_name,
                    Key=object_name,
                )

            print(f"Upload successful: {object_name}")

            # Return COS URI
            cos_uri = f"cos://{self.bucket_name}/{object_name}"
            return cos_uri

        except Exception as e:
            raise RuntimeError(f"Failed to upload file to COS: {str(e)}") from e

    def delete_file(self, object_name: str) -> None:
        """
        Delete a file from COS.

        Args:
            object_name: Object name to delete
        """
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=object_name)
            print(f"Deleted object from COS: {object_name}")
        except Exception as e:
            print(f"Warning: Failed to delete object from COS: {str(e)}")

    def upload_source_code(
        self,
        source_dir: str,
        deployment_id: str,
        exclude_patterns: Optional[list[str]] = None,
    ) -> tuple[str, str]:
        """
        Complete workflow: zip source code and upload to COS.

        Args:
            source_dir: Directory containing source code
            deployment_id: Unique deployment identifier (used in filename)
            exclude_patterns: Optional list of patterns to exclude from zip

        Returns:
            Tuple of (COS URI, local zip file path)
        """
        # Create unique object name
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        object_name = f"deployments/{deployment_id}/{timestamp}_source.zip"

        # Create archive
        print(f"Creating source archive from {source_dir}...")
        zip_path = self.create_source_archive(
            source_dir=source_dir,
            exclude_patterns=exclude_patterns,
        )

        # Upload to COS
        cos_uri = self.upload_file(
            file_path=zip_path,
            object_name=object_name,
        )

        return cos_uri, zip_path


def create_cos_uploader(
    authenticator: IAMAuthenticator,
    region: str,
    bucket_name: str,
    endpoint: Optional[str] = None,
) -> COSUploader:
    """
    Factory function to create a COSUploader instance.

    Args:
        authenticator: IBM Cloud IAM authenticator
        region: IBM Cloud region (e.g., 'us-south')
        bucket_name: COS bucket name
        endpoint: Optional custom endpoint (auto-detected if not provided)

    Returns:
        COSUploader instance
    """
    # Auto-detect endpoint if not provided
    if endpoint is None:
        endpoint = f"s3.{region}.cloud-object-storage.appdomain.cloud"

    # Get COS service instance ID from environment or derive from region
    # In production, this should be the COS service CRN
    service_instance_id = os.getenv(
        "IBM_COS_SERVICE_INSTANCE_ID",
        f"crn:v1:bluemix:public:cloud-object-storage:global:a/:::",
    )

    return COSUploader(
        authenticator=authenticator,
        service_instance_id=service_instance_id,
        endpoint=endpoint,
        bucket_name=bucket_name,
    )


def upload_source(
    authenticator: IAMAuthenticator,
    source_path: str,
    bucket_name: str,
    region: str = "us-south",
    endpoint: Optional[str] = None,
    deployment_id: Optional[str] = None,
) -> str:
    """
    High-level function to upload source code to COS.

    This is the primary function to use from the CODING_PLAN workflow.

    Args:
        authenticator: IBM Cloud IAM authenticator
        source_path: Directory containing source code to upload
        bucket_name: COS bucket name
        region: IBM Cloud region (default: 'us-south')
        endpoint: Optional custom COS endpoint
        deployment_id: Optional deployment ID for organizing uploads

    Returns:
        COS URI string in format: cos://bucket/path/to/source.zip

    Example:
        >>> from ibm_cloud_vercel.sdk import auth, cos
        >>> authenticator = auth.create_iam_authenticator()
        >>> cos_uri = cos.upload_source(authenticator, ".", "my-bucket")
    """
    if deployment_id is None:
        deployment_id = os.getenv("VERCEL_DEPLOYMENT_ID", "local")

    uploader = create_cos_uploader(
        authenticator=authenticator,
        region=region,
        bucket_name=bucket_name,
        endpoint=endpoint,
    )

    cos_uri, _ = uploader.upload_source_code(
        source_dir=source_path,
        deployment_id=deployment_id,
    )

    return cos_uri
