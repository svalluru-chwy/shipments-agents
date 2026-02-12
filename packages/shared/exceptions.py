"""
Custom exceptions for the Shipments Agency Platform.

All platform-specific errors inherit from :class:`CATAgencyError` so callers
can catch a single base type when needed.
"""


class CATAgencyError(Exception):
    """Base exception for all Shipments Agency Platform errors."""

    def __init__(self, message: str, error_code: str | None = None, details: dict | None = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class ConnectionError(CATAgencyError):
    """Raised when a database or external-service connection fails."""

    def __init__(self, message: str, service: str | None = None, **kwargs):
        self.service = service
        super().__init__(message, error_code="CONNECTION_ERROR", **kwargs)


class ExtractionError(CATAgencyError):
    """Raised when Snowflake data extraction fails."""

    def __init__(self, message: str, customer_id: str | None = None, query_name: str | None = None, **kwargs):
        self.customer_id = customer_id
        self.query_name = query_name
        super().__init__(message, error_code="EXTRACTION_ERROR", **kwargs)


class AgentError(CATAgencyError):
    """Raised when an agent run fails."""

    def __init__(self, message: str, agent_name: str | None = None, customer_id: str | None = None, **kwargs):
        self.agent_name = agent_name
        self.customer_id = customer_id
        super().__init__(message, error_code="AGENT_ERROR", **kwargs)


class SkillError(CATAgencyError):
    """Raised when a skill execution fails."""

    def __init__(self, message: str, skill_name: str | None = None, customer_id: str | None = None, **kwargs):
        self.skill_name = skill_name
        self.customer_id = customer_id
        super().__init__(message, error_code="SKILL_ERROR", **kwargs)


class ConfigurationError(CATAgencyError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str, config_key: str | None = None, **kwargs):
        self.config_key = config_key
        super().__init__(message, error_code="CONFIGURATION_ERROR", **kwargs)


class S3Error(CATAgencyError):
    """Raised when an S3 operation fails."""

    def __init__(self, message: str, s3_path: str | None = None, **kwargs):
        self.s3_path = s3_path
        super().__init__(message, error_code="S3_ERROR", **kwargs)


class ValidationError(CATAgencyError):
    """Raised when validation of agent/skill output fails after all retries."""

    def __init__(self, message: str, agent_name: str | None = None, accuracy: float | None = None, **kwargs):
        self.agent_name = agent_name
        self.accuracy = accuracy
        super().__init__(message, error_code="VALIDATION_ERROR", **kwargs)
