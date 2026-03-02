"""MCP Server configuration."""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """MCP Server settings."""
    
    # Server settings
    MCP_SERVER_PORT: int = 8001
    MCP_SERVER_HOST: str = "0.0.0.0"
    
    # Backend API settings
    BACKEND_URL: str = "http://app:8000"
    
    # MCP Protocol version
    PROTOCOL_VERSION: str = "2024-11-05"
    
    # Server info
    SERVER_NAME: str = "AI-Experiments MCP Server"
    SERVER_VERSION: str = "1.0.0"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"


settings = Settings()
