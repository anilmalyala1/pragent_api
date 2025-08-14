from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Env: GITHUB_TOKEN, GITHUB_API (optional)
    github_token: str | None = Field(default=None, validation_alias="GITHUB_TOKEN")
    github_api_base: str = Field(default="https://api.github.com", validation_alias="GITHUB_API")
    request_timeout: float = 30.0
    per_page: int = 100
    max_pages: int = 10

settings = Settings()

def get_settings() -> Settings:
    return settings
