"""Custom exceptions for IBMCloudVercel with specific exit codes."""


class IBMCloudVercelError(Exception):
    """Base exception for all IBMCloudVercel errors."""

    exit_code: int = 1
    error_type: str = "unknown"

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class ConfigurationError(IBMCloudVercelError):
    """Raised when configuration is invalid or missing."""

    exit_code = 10
    error_type = "configuration"


class AuthenticationError(IBMCloudVercelError):
    """Raised when IBM Cloud authentication fails."""

    exit_code = 20
    error_type = "authentication"


class COSUploadError(IBMCloudVercelError):
    """Raised when Cloud Object Storage upload fails."""

    exit_code = 30
    error_type = "cos_upload"


class CodeEngineError(IBMCloudVercelError):
    """Raised when Code Engine deployment fails."""

    exit_code = 40
    error_type = "code_engine"


class VercelAPIError(IBMCloudVercelError):
    """Raised when Vercel API calls fail."""

    exit_code = 50
    error_type = "vercel_api"


# Exit code reference:
# 0   - Success
# 1   - Generic/unknown error
# 10  - Configuration error (missing config, invalid values)
# 20  - Authentication error (invalid API key, OIDC failure)
# 30  - COS upload error (bucket not found, permission denied)
# 40  - Code Engine error (deployment failed)
# 50  - Vercel API error (checks API failed)
