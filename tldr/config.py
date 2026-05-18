from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    yahoo_user: str = "martinguitarplayer2000@yahoo.com"
    yahoo_app_password: str = ""
    yahoo_imap_host: str = "imap.mail.yahoo.com"
    yahoo_imap_port: int = 993

    database_url: str = "postgresql+asyncpg://tldr:tldr@localhost:5433/tldr"

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    claude_embed_model: str = "voyage-3-large"

    ollama_host: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1:8b"
    ollama_embed_model: str = "mxbai-embed-large"

    default_llm_provider: str = "claude"
    embedding_dim: int = 1024

    reports_dir: Path = Field(default=Path("/Users/douglasromano/Documents/Claude/Projects/Branding"))

    web_host: str = "127.0.0.1"
    web_port: int = 8080


settings = Settings()
