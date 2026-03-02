"""Application configuration settings."""

from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # MongoDB Configuration
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database: str = "adk_demo"

    # Redis Configuration
    redis_url: str = "redis://localhost:6379"
    redis_db: int = 0

    # JWT Configuration
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Validate JWT secret key is set and reasonably secure."""
        if not v or len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be set and at least 32 characters long. "
                "Generate a secure key using: "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        return v

    # Google AI Configuration (used by Google ADK)
    google_api_key: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    google_application_credentials: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Application Configuration
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    # Standalone MCP server URL (ADK agent connects here)
    mcp_server_url: str = "http://localhost:8001"

    # MCP Server Configuration
    mcp_server_host: str = "0.0.0.0"
    mcp_server_port: int = 8001

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
