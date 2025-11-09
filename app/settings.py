from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    HMAC_SECRET: str = "change-me"
    ALLOW_ORIGINS: str = "*"
    # Development-friendly bearer token; if None, bearer is accepted but not checked.
    BEARER_TOKEN: Optional[str] = None
    # When True, requests without Bearer or HMAC will be accepted (for local dev/tests)
    AUTH_OPTIONAL: bool = True

settings = Settings()
