import os
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    COCKROACH_URL: Optional[str] = os.environ.get("COCKROACH_URL")
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: str = "crawler-files"
    R2_PUBLIC_URL: Optional[str] = None
    MAX_CONCURRENT_CRAWLS: int = 15
    REQUEST_TIMEOUT: int = 15
    JWT_SECRET: str = "changeme-very-secret-key-32chars!!"

    @property
    def USE_R2(self) -> bool:
        return bool(self.R2_ACCOUNT_ID and self.R2_ACCESS_KEY_ID and self.R2_SECRET_ACCESS_KEY)

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
