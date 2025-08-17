from pydantic import Field
from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    # Env: GITHUB_TOKEN, GITHUB_API (optional)
    github_token: str | None = Field(default=None, validation_alias="GITHUB_TOKEN")
    github_api_base: str = Field(default="https://api.github.com", validation_alias="GITHUB_API")
    request_timeout: float = 30.0
    per_page: int = 100
    max_pages: int = 10
     # NEW: max bytes per file (server-side guard)
    max_file_bytes: int = 1_000_000  # ~1MB
    vcs_provider: str = Field(default="github", validation_alias="VCS_PROVIDER")

    # Bitbucket settings
    bitbucket_username: str | None = Field(default=None, validation_alias="BITBUCKET_USERNAME")
    bitbucket_app_password: str | None = Field(default=None, validation_alias="BITBUCKET_APP_PASSWORD")
    bitbucket_api_base: str = Field(default="https://api.bitbucket.org/2.0", validation_alias="BITBUCKET_API_BASE")


settings = Settings()

def get_settings() -> Settings:
    settings.github_token=os.getenv("GITHUB_TOKEN")
    return settings
