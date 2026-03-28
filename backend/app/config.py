from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Malenkie Legendy Backend'
    public_base_url: str = 'http://31.129.108.93:8010'

    db_host: str = '127.0.0.1'
    db_port: int = 5433
    db_name: str = 'legend_db'
    db_user: str = 'legend_user'
    db_password: str = Field(default='')

    text_provider: str = 'openrouter'
    openrouter_api_key: str = ''
    # SAFETY: this field is validated against allowlist at application startup.
    # Never change this to an expensive model (claude-opus, gpt-4o, o1, etc.).
    openrouter_model: str = 'openai/gpt-4o-mini'
    backup_text_provider: str = 'template'

    openai_api_key: str = ''
    together_api_key: str = ''

    image_provider: str = 'together'
    stability_api_key: str = ''
    backup_image_provider: str = 'openai'

    stories_dir: str = str(BASE_DIR / 'backend' / 'storage' / 'stories')
    images_dir: str = str(BASE_DIR / 'backend' / 'storage' / 'images')

    keep_uploaded_photo: bool = False

    # TESTING: set to True to always generate episode 1 (disables series continuation).
    # Switch to False when ready for production.
    force_episode_one: bool = True

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
