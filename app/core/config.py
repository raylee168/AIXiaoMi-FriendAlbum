from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "aixiaomi-friend-album"
    database_url: str = "mysql+pymysql://root@127.0.0.1:3306/core_album_db?charset=utf8mb4"
    account_server_base_url: str = ""
    llm_proxy_base_url: str = ""
    cowagent_channel_base_url: str = ""
    agent_base_url: str = ""
    storage_root: str = "/data/smart-album"
    mock_account: bool = True
    mock_llm: bool = True
    mock_push: bool = True
    trigger_window_minutes: int = 10
    trigger_photo_threshold: int = 6
    default_album_count: int = 2
    single_task_freeze_limit: int = 300_000
    platform_service_fee_tokens: int = 50_000
    result_expire_hours: int = 3
    scheduler_worker_id: str = "friend-album-local"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
