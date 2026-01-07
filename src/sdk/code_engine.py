"""IBM Code Engine SDK wrapper for project and application management.

This module provides functions to interact with IBM Code Engine,
including project lookup by name and application deployment.
"""

import re
import time
from typing import Optional, Union

from ibm_cloud_sdk_core.authenticators import IAMAuthenticator, BearerTokenAuthenticator
from ibm_code_engine_sdk.code_engine_v2 import CodeEngineV2


# Code Engine naming pattern (Kubernetes namespace rules)
# - lowercase letters, numbers, hyphens only
# - must start with letter, end with alphanumeric
# - max 63 characters
CE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$|^[a-z]$")


def validate_project_name(name: str) -> None:
    """
    Validate that a project name is not empty.

    Note: IBM Cloud Console allows more flexible naming (including spaces)
    than the CLI, so we only do minimal validation here and let the API
    handle detailed validation.

    Args:
        name: Project name to validate

    Raises:
        ValueError: If the name is empty
    """
    if not name:
        raise ValueError("Project name cannot be empty")

    if len(name) > 128:
        raise ValueError(
            f"Project name is too long ({len(name)} chars). "
            "Project names must be 128 characters or fewer."
        )


def create_code_engine_client(
    authenticator: Union[IAMAuthenticator, BearerTokenAuthenticator],
    region: str = "us-south",
) -> CodeEngineV2:
    """
    Create an IBM Code Engine client.

    Args:
        authenticator: IAMAuthenticator or BearerTokenAuthenticator instance
        region: IBM Cloud region (default: us-south)

    Returns:
        CodeEngineV2 client instance

    Example:
        >>> from sdk import auth
        >>> authenticator = auth.get_authenticator()
        >>> client = create_code_engine_client(authenticator, "us-south")
    """
    # Create the Code Engine client
    client = CodeEngineV2(authenticator=authenticator)

    # Set the service URL based on region
    service_url = f"https://api.{region}.codeengine.cloud.ibm.com/v2"
    client.set_service_url(service_url)

    return client


def lookup_project_by_name(
    client: CodeEngineV2,
    project_name: str,
) -> Optional[str]:
    """
    Look up a Code Engine project ID by its name.

    Args:
        client: CodeEngineV2 client instance
        project_name: Name of the project to find

    Returns:
        Project ID if found, None otherwise

    Raises:
        RuntimeError: If API call fails

    Example:
        >>> project_id = lookup_project_by_name(client, "my-project")
        >>> if project_id:
        ...     print(f"Found project: {project_id}")
    """
    try:
        # Paginate through all projects to find the one with matching name
        start = None

        while True:
            response = client.list_projects(limit=100, start=start)
            result = response.get_result()

            projects = result.get("projects", [])

            for project in projects:
                if project.get("name") == project_name:
                    return project.get("id")

            # Check for next page
            next_page = result.get("next")
            if next_page and next_page.get("start"):
                start = next_page.get("start")
            else:
                break

        return None

    except Exception as e:
        raise RuntimeError(f"Failed to list Code Engine projects: {str(e)}") from e


def get_project_details(
    client: CodeEngineV2,
    project_id: str,
) -> dict:
    """
    Get details of a Code Engine project.

    Args:
        client: CodeEngineV2 client instance
        project_id: ID of the project

    Returns:
        Dictionary containing project details

    Raises:
        RuntimeError: If project not found or API call fails

    Example:
        >>> details = get_project_details(client, "abc123-def456")
        >>> print(f"Project status: {details['status']}")
    """
    try:
        response = client.get_project(id=project_id)
        return response.get_result()

    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg or "not found" in error_msg.lower():
            raise RuntimeError(f"Code Engine project not found: {project_id}") from e
        raise RuntimeError(f"Failed to get project details: {error_msg}") from e


def resolve_project_id(
    client: CodeEngineV2,
    project_id_or_name: str,
) -> str:
    """
    Resolve a project ID from either a direct ID or a project name.

    This function first tries to use the input as a project ID.
    If that fails (404), it attempts to look up the project by name.

    Args:
        client: CodeEngineV2 client instance
        project_id_or_name: Either a project ID (UUID format) or project name

    Returns:
        The resolved project ID

    Raises:
        ValueError: If the project name is invalid
        RuntimeError: If project cannot be found by ID or name

    Example:
        >>> # Works with both ID and name
        >>> project_id = resolve_project_id(client, "my-project")
        >>> project_id = resolve_project_id(client, "abc123-def456-...")
    """
    # Validate the name/ID format early
    validate_project_name(project_id_or_name)

    # Check if it looks like a UUID (project ID format)
    # IBM project IDs are UUIDs: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    is_uuid_format = (
        len(project_id_or_name) == 36
        and project_id_or_name.count("-") == 4
        and all(
            c.isalnum() or c == "-"
            for c in project_id_or_name
        )
    )

    if is_uuid_format:
        # Try to get the project directly by ID
        try:
            get_project_details(client, project_id_or_name)
            return project_id_or_name
        except RuntimeError as e:
            if "not found" in str(e).lower():
                # Fall through to name lookup
                pass
            else:
                raise

    # Try to look up by name
    project_id = lookup_project_by_name(client, project_id_or_name)

    if project_id:
        print(f"  Resolved project name '{project_id_or_name}' to ID: {project_id}")
        return project_id

    # Neither ID nor name worked
    raise RuntimeError(
        f"Code Engine project not found: '{project_id_or_name}'. "
        "Verify the project exists in your IBM Cloud account and region."
    )


def validate_project_access(
    authenticator: Union[IAMAuthenticator, BearerTokenAuthenticator],
    region: str,
    project_id_or_name: str,
) -> str:
    """
    Validate access to a Code Engine project and resolve its ID.

    This is a convenience function that creates a client, resolves
    the project ID, and validates access in one call.

    Args:
        authenticator: IAMAuthenticator or BearerTokenAuthenticator instance
        region: IBM Cloud region
        project_id_or_name: Either a project ID or project name

    Returns:
        The resolved project ID

    Raises:
        RuntimeError: If project cannot be found or accessed

    Example:
        >>> from sdk import auth
        >>> authenticator = auth.get_authenticator()
        >>> project_id = validate_project_access(
        ...     authenticator,
        ...     "us-south",
        ...     "my-app-project"
        ... )
    """
    client = create_code_engine_client(authenticator, region)
    project_id = resolve_project_id(client, project_id_or_name)

    # Validate we can access the project
    details = get_project_details(client, project_id)
    status = details.get("status", "unknown")

    if status != "active":
        print(f"  Warning: Project status is '{status}' (expected 'active')")

    return project_id


# =============================================================================
# Build Functions
# =============================================================================


def create_build(
    client: CodeEngineV2,
    project_id: str,
    name: str,
    source_url: str,
    source_revision: str,
    output_image: str,
    output_secret: str,
    strategy_type: str = "buildpacks",
    strategy_size: str = "medium",
    source_context_dir: str = "",
    strategy_spec_file: str = "",
    timeout: int = 600,
) -> dict:
    """
    Create a build configuration in Code Engine.

    Args:
        client: CodeEngineV2 client instance
        project_id: Code Engine project ID
        name: Name for the build configuration
        source_url: Git repository URL
        source_revision: Git branch, tag, or commit SHA
        output_image: Container image reference for the built image
        output_secret: Secret name for registry authentication
        strategy_type: Build strategy ("dockerfile" or "buildpacks")
        strategy_size: Build resource size ("small", "medium", "large", "xlarge")
        source_context_dir: Subdirectory containing the source
        strategy_spec_file: Path to Dockerfile (for dockerfile strategy)
        timeout: Build timeout in seconds

    Returns:
        Build configuration details

    Raises:
        RuntimeError: If build creation fails
    """
    try:
        response = client.create_build(
            project_id=project_id,
            name=name,
            source_url=source_url,
            source_revision=source_revision,
            source_type="git",
            output_image=output_image,
            output_secret=output_secret,
            strategy_type=strategy_type,
            strategy_size=strategy_size,
            source_context_dir=source_context_dir if source_context_dir else None,
            strategy_spec_file=strategy_spec_file if strategy_spec_file else None,
            timeout=timeout,
        )
        return response.get_result()
    except Exception as e:
        error_msg = str(e)
        if "409" in error_msg or "already exists" in error_msg.lower():
            # Build already exists, update it instead
            return update_build(
                client=client,
                project_id=project_id,
                name=name,
                source_url=source_url,
                source_revision=source_revision,
                output_image=output_image,
                output_secret=output_secret,
                strategy_type=strategy_type,
                strategy_size=strategy_size,
                source_context_dir=source_context_dir,
                strategy_spec_file=strategy_spec_file,
                timeout=timeout,
            )
        raise RuntimeError(f"Failed to create build configuration: {error_msg}") from e


def update_build(
    client: CodeEngineV2,
    project_id: str,
    name: str,
    source_url: str,
    source_revision: str,
    output_image: str,
    output_secret: str,
    strategy_type: str = "buildpacks",
    strategy_size: str = "medium",
    source_context_dir: str = "",
    strategy_spec_file: str = "",
    timeout: int = 600,
) -> dict:
    """
    Update an existing build configuration.

    Args:
        Same as create_build

    Returns:
        Updated build configuration details
    """
    try:
        # First get the current build to get the etag
        get_response = client.get_build(project_id=project_id, name=name)
        current_build = get_response.get_result()
        etag = get_response.get_headers().get("ETag")

        response = client.update_build(
            project_id=project_id,
            name=name,
            if_match=etag,
            source_url=source_url,
            source_revision=source_revision,
            output_image=output_image,
            output_secret=output_secret,
            strategy_type=strategy_type,
            strategy_size=strategy_size,
            source_context_dir=source_context_dir if source_context_dir else None,
            strategy_spec_file=strategy_spec_file if strategy_spec_file else None,
            timeout=timeout,
        )
        return response.get_result()
    except Exception as e:
        raise RuntimeError(f"Failed to update build configuration: {str(e)}") from e


def run_build(
    client: CodeEngineV2,
    project_id: str,
    build_name: str,
    timeout: int = 600,
    poll_interval: int = 10,
) -> dict:
    """
    Start a build run and wait for completion.

    Args:
        client: CodeEngineV2 client instance
        project_id: Code Engine project ID
        build_name: Name of the build configuration to run
        timeout: Maximum time to wait for build completion (seconds)
        poll_interval: Time between status checks (seconds)

    Returns:
        Build run result with status and output image

    Raises:
        RuntimeError: If build fails or times out
    """
    try:
        # Start the build run
        response = client.create_build_run(
            project_id=project_id,
            build_name=build_name,
        )
        build_run = response.get_result()
        build_run_name = build_run.get("name")
        print(f"    Build run started: {build_run_name}")

        # Poll for completion
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise RuntimeError(
                    f"Build timed out after {timeout} seconds. "
                    f"Build run: {build_run_name}"
                )

            # Check status
            status_response = client.get_build_run(
                project_id=project_id,
                name=build_run_name,
            )
            build_run = status_response.get_result()
            status = build_run.get("status", "unknown")

            if status == "succeeded":
                print(f"    Build completed successfully")
                return build_run
            elif status == "failed":
                reason = build_run.get("status_details", {}).get("reason", "Unknown")
                raise RuntimeError(f"Build failed: {reason}")
            elif status in ("pending", "running"):
                print(f"    Build status: {status} ({int(elapsed)}s elapsed)")
                time.sleep(poll_interval)
            else:
                print(f"    Build status: {status}")
                time.sleep(poll_interval)

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to run build: {str(e)}") from e


# =============================================================================
# Application Functions
# =============================================================================


def get_app(
    client: CodeEngineV2,
    project_id: str,
    name: str,
) -> Optional[dict]:
    """
    Get an application by name.

    Args:
        client: CodeEngineV2 client instance
        project_id: Code Engine project ID
        name: Application name

    Returns:
        Application details if found, None otherwise
    """
    try:
        response = client.get_app(project_id=project_id, name=name)
        return response.get_result()
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            return None
        raise RuntimeError(f"Failed to get application: {str(e)}") from e


def create_app(
    client: CodeEngineV2,
    project_id: str,
    name: str,
    image_reference: str,
    image_port: int = 8080,
    scale_min_instances: int = 0,
    scale_max_instances: int = 10,
    scale_cpu_limit: str = "0.25",
    scale_memory_limit: str = "0.5G",
    scale_concurrency: int = 100,
) -> dict:
    """
    Create a new Code Engine application.

    Args:
        client: CodeEngineV2 client instance
        project_id: Code Engine project ID
        name: Application name
        image_reference: Container image to deploy
        image_port: Port the container listens on
        scale_min_instances: Minimum number of instances
        scale_max_instances: Maximum number of instances
        scale_cpu_limit: CPU limit per instance
        scale_memory_limit: Memory limit per instance
        scale_concurrency: Requests per instance before scaling

    Returns:
        Created application details
    """
    try:
        response = client.create_app(
            project_id=project_id,
            name=name,
            image_reference=image_reference,
            image_port=image_port,
            scale_min_instances=scale_min_instances,
            scale_max_instances=scale_max_instances,
            scale_cpu_limit=scale_cpu_limit,
            scale_memory_limit=scale_memory_limit,
            scale_concurrency=scale_concurrency,
        )
        return response.get_result()
    except Exception as e:
        raise RuntimeError(f"Failed to create application: {str(e)}") from e


def update_app(
    client: CodeEngineV2,
    project_id: str,
    name: str,
    image_reference: str,
    image_port: int = 8080,
    scale_min_instances: int = 0,
    scale_max_instances: int = 10,
    scale_cpu_limit: str = "0.25",
    scale_memory_limit: str = "0.5G",
    scale_concurrency: int = 100,
) -> dict:
    """
    Update an existing Code Engine application.

    Args:
        Same as create_app

    Returns:
        Updated application details
    """
    try:
        # Get current app to get etag
        get_response = client.get_app(project_id=project_id, name=name)
        etag = get_response.get_headers().get("ETag")

        response = client.update_app(
            project_id=project_id,
            name=name,
            if_match=etag,
            image_reference=image_reference,
            image_port=image_port,
            scale_min_instances=scale_min_instances,
            scale_max_instances=scale_max_instances,
            scale_cpu_limit=scale_cpu_limit,
            scale_memory_limit=scale_memory_limit,
            scale_concurrency=scale_concurrency,
        )
        return response.get_result()
    except Exception as e:
        raise RuntimeError(f"Failed to update application: {str(e)}") from e


def deploy_app(
    client: CodeEngineV2,
    project_id: str,
    name: str,
    image_reference: str,
    image_port: int = 8080,
    scale_min_instances: int = 0,
    scale_max_instances: int = 10,
    scale_cpu_limit: str = "0.25",
    scale_memory_limit: str = "0.5G",
    scale_concurrency: int = 100,
) -> dict:
    """
    Deploy an application (create or update).

    This function checks if the app exists and creates or updates accordingly.

    Args:
        Same as create_app

    Returns:
        Application details with URL
    """
    existing_app = get_app(client, project_id, name)

    if existing_app:
        print(f"    Updating existing application: {name}")
        app = update_app(
            client=client,
            project_id=project_id,
            name=name,
            image_reference=image_reference,
            image_port=image_port,
            scale_min_instances=scale_min_instances,
            scale_max_instances=scale_max_instances,
            scale_cpu_limit=scale_cpu_limit,
            scale_memory_limit=scale_memory_limit,
            scale_concurrency=scale_concurrency,
        )
    else:
        print(f"    Creating new application: {name}")
        app = create_app(
            client=client,
            project_id=project_id,
            name=name,
            image_reference=image_reference,
            image_port=image_port,
            scale_min_instances=scale_min_instances,
            scale_max_instances=scale_max_instances,
            scale_cpu_limit=scale_cpu_limit,
            scale_memory_limit=scale_memory_limit,
            scale_concurrency=scale_concurrency,
        )

    return app


def get_app_url(app: dict) -> str:
    """
    Extract the public URL from an application response.

    Args:
        app: Application details dictionary

    Returns:
        The public URL for the application
    """
    # Try to get URL from status_details
    status_details = app.get("status_details", {})
    url = status_details.get("url")
    if url:
        return url

    # Fallback: construct from endpoint
    endpoint = app.get("endpoint")
    if endpoint:
        return f"https://{endpoint}"

    # Another fallback: use name and region
    name = app.get("name", "unknown")
    return f"https://{name}.{app.get('region', 'unknown')}.codeengine.appdomain.cloud"
