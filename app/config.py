from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "local"
    database_url: str = "sqlite:///./consumer_kg.db"
    neo4j_enabled: bool = False
    neo4j_wsl_bridge: Literal["auto", "enabled", "disabled"] = "auto"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change-me"
    llm_enabled: bool = False
    llm_base_url: str = "https://example.invalid/v1"
    llm_api_key: str = ""
    llm_model: str = "your-model"
    agent_thinking: Literal["auto", "disabled", "enabled"] = "auto"
    agent_parallel_tools: bool = True
    agent_max_tool_calls: int = 6
    agent_llm_timeout_seconds: float = 120.0
    api_key: str = ""
    llm_timeout_seconds: float = 50.0
    llm_max_retries: int = 3
    admin_api_key: str = ""
    log_level: str = "INFO"
    cors_origins: list[str] = []

settings = Settings()
