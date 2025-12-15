"""IBM Cloud authentication handler.

This module provides centralized authentication for all IBM Cloud SDK clients.
Supports both API key authentication and OIDC token exchange via IBM Trusted Profiles.
"""

import os
from typing import Optional, Union

from ibm_cloud_sdk_core.authenticators import IAMAuthenticator, BearerTokenAuthenticator
import requests


def create_iam_authenticator(api_key: Optional[str] = None) -> IAMAuthenticator:
    """
    Create an IAM authenticator for IBM Cloud services.

    Args:
        api_key: IBM Cloud API key. If not provided, reads from IBM_CLOUD_API_KEY
                 environment variable.

    Returns:
        IAMAuthenticator instance configured with the API key

    Raises:
        ValueError: If API key is not provided and not found in environment

    Example:
        >>> auth = create_iam_authenticator()
        >>> # Use with any IBM SDK client
        >>> cos_client = ibm_boto3.client('s3', ibm_authenticator=auth, ...)
    """
    # Use provided API key or fall back to environment variable
    if api_key is None:
        api_key = os.getenv("IBM_CLOUD_API_KEY")

    if not api_key:
        raise ValueError(
            "IBM Cloud API key is required. "
            "Provide it as an argument or set the IBM_CLOUD_API_KEY environment variable."
        )

    # Create and return the authenticator
    authenticator = IAMAuthenticator(apikey=api_key)

    return authenticator


def get_api_key_from_env() -> str:
    """
    Retrieve the IBM Cloud API key from environment variables.

    Returns:
        The API key string

    Raises:
        ValueError: If IBM_CLOUD_API_KEY is not set
    """
    api_key = os.getenv("IBM_CLOUD_API_KEY")

    if not api_key:
        raise ValueError(
            "IBM_CLOUD_API_KEY environment variable is required. "
            "Set it in Vercel project settings or your local environment."
        )

    return api_key


def validate_api_key(api_key: str) -> bool:
    """
    Validate that an API key has the expected format.

    Args:
        api_key: The API key to validate

    Returns:
        True if the API key appears valid, False otherwise

    Note:
        This only checks basic format, not whether the key is actually valid
        with IBM Cloud. Actual validation happens when making API calls.
    """
    if not api_key:
        return False

    # IBM Cloud API keys are typically 44 characters
    # They contain alphanumeric characters and some special chars
    if len(api_key) < 20:
        return False

    return True


def create_iam_authenticator_oidc(
    oidc_token: str,
    trusted_profile_id: str,
    iam_endpoint: str = "https://iam.cloud.ibm.com",
) -> BearerTokenAuthenticator:
    """
    Create an IAM authenticator using OIDC token exchange with IBM Trusted Profile.

    This method exchanges a Vercel OIDC token for an IBM Cloud IAM access token
    using IBM's Trusted Profile feature. This is more secure than API keys because:
    - No long-lived credentials are stored
    - Tokens are short-lived (1 hour)
    - Identity is verified via OIDC claims

    Args:
        oidc_token: OIDC token from Vercel (VERCEL_OIDC_TOKEN env var)
        trusted_profile_id: IBM Cloud Trusted Profile ID configured to trust Vercel OIDC
        iam_endpoint: IBM IAM endpoint (default: https://iam.cloud.ibm.com)

    Returns:
        BearerTokenAuthenticator with IBM IAM access token

    Raises:
        ValueError: If OIDC token or Trusted Profile ID is missing
        RuntimeError: If token exchange fails

    Example:
        >>> oidc_token = os.getenv("VERCEL_OIDC_TOKEN")
        >>> profile_id = "Profile-xxxxx-xxxx-xxxx"
        >>> auth = create_iam_authenticator_oidc(oidc_token, profile_id)
    """
    if not oidc_token:
        raise ValueError("OIDC token is required for OIDC authentication")

    if not trusted_profile_id:
        raise ValueError(
            "IBM Cloud Trusted Profile ID is required for OIDC authentication. "
            "Set it in your ibmcloudvercel.yml configuration."
        )

    # Exchange OIDC token for IBM IAM access token
    try:
        # IBM Cloud IAM token exchange endpoint
        token_url = f"{iam_endpoint}/identity/token"

        # Prepare the token exchange request
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        data = {
            "grant_type": "urn:ibm:params:oauth:grant-type:cr-token",
            "cr_token": oidc_token,
            "profile_id": trusted_profile_id,
        }

        # Make the token exchange request
        response = requests.post(token_url, headers=headers, data=data, timeout=10)
        response.raise_for_status()

        # Extract the access token
        token_data = response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise RuntimeError("Failed to obtain access token from IBM IAM")

        print(f"  ✓ OIDC token exchanged for IBM IAM access token")
        print(f"    Token expires in: {token_data.get('expires_in', 'unknown')} seconds")

        # Create and return a BearerTokenAuthenticator
        return BearerTokenAuthenticator(bearer_token=access_token)

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to exchange OIDC token with IBM IAM: {str(e)}") from e
    except KeyError as e:
        raise RuntimeError(f"Invalid response from IBM IAM token endpoint: {str(e)}") from e


def get_authenticator(
    trusted_profile_id: Optional[str] = None,
    api_key: Optional[str] = None,
    oidc_token: Optional[str] = None,
) -> Union[BearerTokenAuthenticator, IAMAuthenticator]:
    """
    Get an authenticator using the best available method.

    Priority:
    1. OIDC token exchange (most secure) - if VERCEL_OIDC_TOKEN is available
    2. API key authentication (fallback) - if IBM_CLOUD_API_KEY is available

    Args:
        trusted_profile_id: IBM Trusted Profile ID (required for OIDC)
        api_key: IBM Cloud API key (optional, reads from env if not provided)
        oidc_token: OIDC token (optional, reads from VERCEL_OIDC_TOKEN if not provided)

    Returns:
        Authenticator instance (BearerTokenAuthenticator or IAMAuthenticator)

    Raises:
        ValueError: If no valid authentication method is available

    Example:
        >>> # Automatic detection
        >>> auth = get_authenticator(trusted_profile_id="Profile-xxxx")
        >>> # Explicit OIDC
        >>> auth = get_authenticator(
        ...     trusted_profile_id="Profile-xxxx",
        ...     oidc_token=os.getenv("VERCEL_OIDC_TOKEN")
        ... )
    """
    # Try OIDC authentication first (if token is available)
    if oidc_token is None:
        oidc_token = os.getenv("VERCEL_OIDC_TOKEN")

    if oidc_token and trusted_profile_id:
        print("  Using OIDC authentication (Vercel → IBM Trusted Profile)")
        return create_iam_authenticator_oidc(oidc_token, trusted_profile_id)

    # Fallback to API key authentication
    if api_key is None:
        api_key = os.getenv("IBM_CLOUD_API_KEY")

    if api_key:
        print("  Using API key authentication")
        return create_iam_authenticator(api_key)

    # No valid authentication method found
    raise ValueError(
        "No valid authentication method available. "
        "Either set VERCEL_OIDC_TOKEN with a Trusted Profile ID, "
        "or set IBM_CLOUD_API_KEY environment variable."
    )
