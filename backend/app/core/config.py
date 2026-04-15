from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Doubao Workflow Backend"
    doubao_api_key: str | None = None
    doubao_video_model: str | None = "doubao-seedance-1-5-pro-251215"
    tts_app_id: str | None = None
    tts_access_token: str | None = None
    tts_cluster: str = "volcano_tts"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    request_timeout_seconds: float = 120.0
    max_parallel_tasks: int = 4
    workflow_storage_dir: str = "data/workflow_runs"
    workflow_auto_persist: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        env_prefix="APP_",
        case_sensitive=False,
    )


settings = Settings()

