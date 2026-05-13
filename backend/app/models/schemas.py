from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator, model_validator

VIDEO_MODEL_ALIASES: dict[str, str] = {
    "doubao-seedance-1-0-pro-fast-251015": "doubao-seedance-1-5-pro-251215",
}

STORY_SHOT_COUNT_MIN = 1
STORY_SHOT_COUNT_MAX = 20


def _normalize_video_model_key(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", "-")


def resolve_video_duration_rule(video_model: str | None) -> tuple[int, int, bool]:
    key = _normalize_video_model_key(video_model)
    if "seedance-2-0" in key or "seedance-2.0" in key:
        return 4, 15, True
    if "seedance-1-5" in key or "seedance-1.5" in key:
        return 4, 12, True
    if "seedance-1-0" in key or "seedance-1.0" in key:
        return 2, 12, False
    return 2, 30, False


class WorkflowTextModels(BaseModel):
    default_model: str | None = None
    story_model: str | None = None
    role_model: str | None = None
    shot_role_model: str | None = None
    camera_model: str | None = None
    shot_image_prompt_model: str | None = None

    @field_validator(
        "default_model",
        "story_model",
        "role_model",
        "shot_role_model",
        "camera_model",
        "shot_image_prompt_model",
    )
    @classmethod
    def normalize_model_name(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    def resolve_for_stage(self, stage: str, fallback: str | None = None) -> str | None:
        if stage == "story":
            return self.story_model or self.default_model or fallback
        if stage == "roles":
            return self.role_model or self.default_model or fallback
        if stage == "shot_roles":
            return self.shot_role_model or self.default_model or fallback
        if stage == "camera":
            return self.camera_model or self.default_model or fallback
        if stage == "shot_image_prompt":
            return self.shot_image_prompt_model or self.default_model or fallback
        return self.default_model or fallback


class DoubaoConnectionConfig(BaseModel):
    base_url: str = Field(default="https://ark.cn-beijing.volces.com/api/v3")
    api_key: str | None = None
    chat_model: str | None = None
    image_model: str | None = None
    video_model: str | None = None
    story_shot_count: int = Field(default=8, ge=STORY_SHOT_COUNT_MIN, le=STORY_SHOT_COUNT_MAX)
    video_duration_seconds: int = Field(default=5)
    video_max_shots: int = Field(default=8, ge=0, le=STORY_SHOT_COUNT_MAX)
    video_poll_timeout_seconds: int = Field(default=0, ge=0, le=86400)
    video_poll_interval_seconds: int = Field(default=2, ge=1, le=30)
    timeout_seconds: float = Field(default=120.0, gt=0)
    image_size: str = Field(default="2048x2048")

    @field_validator("base_url")
    @classmethod
    def strip_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("chat_model")
    @classmethod
    def normalize_chat_model(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    @field_validator("image_model")
    @classmethod
    def normalize_image_model(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    @field_validator("video_model")
    @classmethod
    def normalize_video_model(cls, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip()
        return VIDEO_MODEL_ALIASES.get(normalized, normalized)

    @model_validator(mode="after")
    def validate_video_duration_for_model(self) -> "DoubaoConnectionConfig":
        min_seconds, max_seconds, allow_auto = resolve_video_duration_rule(self.video_model)
        duration = self.video_duration_seconds
        if allow_auto and duration == -1:
            return self
        if duration < min_seconds or duration > max_seconds:
            auto_hint = " or -1 (auto)" if allow_auto else ""
            model_hint = self.video_model or "default video model"
            raise ValueError(
                f"video_duration_seconds for '{model_hint}' must be within [{min_seconds}, {max_seconds}]{auto_hint}."
            )
        if self.video_max_shots > self.story_shot_count:
            raise ValueError("video_max_shots must be less than or equal to story_shot_count.")
        return self

    @field_validator("image_size")
    @classmethod
    def validate_image_size(cls, value: str) -> str:
        normalized = value.strip().lower().replace("×", "x")
        if normalized in {"1k", "2k", "4k"}:
            return normalized.upper()

        match = re.fullmatch(r"(\d+)x(\d+)", normalized)
        if match is None:
            raise ValueError("图片尺寸格式无效。请使用 1K/2K/4K，或类似 2048x2048 的宽高像素值。")

        width = int(match.group(1))
        height = int(match.group(2))
        total_pixels = width * height
        aspect_ratio = width / height if height else 0
        if total_pixels < 921_600 or total_pixels > 16_777_216:
            raise ValueError("图片尺寸总像素不符合要求，需位于 [921600, 16777216]。")
        if aspect_ratio < (1 / 16) or aspect_ratio > 16:
            raise ValueError("图片尺寸宽高比不符合要求，需位于 [1/16, 16]。")

        return f"{width}x{height}"

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class TtsConfig(BaseModel):
    enabled: bool = False
    endpoint: str = Field(default="https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse")
    app_id: str | None = None
    access_token: str | None = None
    cluster: str = "volcano_tts"
    voice_type: str = "BV700_streaming"
    remove_role_names: bool = True
    speed: float = Field(default=1.0, ge=0.2, le=3.0)
    uid: str = "doubao-workflow-web"

    @field_validator("endpoint")
    @classmethod
    def strip_endpoint(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.app_id and self.access_token and self.voice_type)

    @field_validator("app_id", "access_token")
    @classmethod
    def normalize_sensitive_fields(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class WorkflowRunRequest(BaseModel):
    story_text: str = Field(min_length=1, max_length=12000)
    connection: DoubaoConnectionConfig
    text_models: WorkflowTextModels = Field(default_factory=WorkflowTextModels)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    subtitle_enabled: bool = False
    max_images: int = Field(default=3, ge=1, le=6)

    @field_validator("story_text")
    @classmethod
    def strip_story_text(cls, value: str) -> str:
        return value.strip()


class TtsVoiceTestRequest(BaseModel):
    tts: TtsConfig
    text: str = Field(default="这是一条音色可用性测试语音。", min_length=1, max_length=200)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class TtsVoiceTestResponse(BaseModel):
    ok: bool
    message: str
    voice_type: str
    audio_url: str | None = None


class RoleDescription(BaseModel):
    name: str
    gender: str
    age: str
    appearance: str
    outfit: str
    mood: str
    atmosphere: str
    full_prompt: str


class RoleImageResult(BaseModel):
    role_name: str
    prompt: str
    image_url: str | None = None
    warning: str | None = None


class ShotRoleMap(BaseModel):
    roles_in_shot: list[str]
    scene_note: str


class ShotResult(BaseModel):
    index: int
    highlight: str
    narration_text: str
    narration_audio_url: str | None = None
    roles_in_shot: list[str]
    scene_note: str
    continuity_start_state: str | None = None
    continuity_end_state: str | None = None
    continuity_transition_to_next: str | None = None
    ref_urls: list[str] = Field(default_factory=list)
    camera_prompt: str
    shot_video_prompt: str | None = None
    first_frame_prompt: str | None = None
    first_frame_url: str | None = None
    shot_video_url: str | None = None
    subtitle_srt: str | None = None


class WorkflowRunResponse(BaseModel):
    title: str
    key_highlights: list[str]
    roles: list[str]
    description_list: list[RoleDescription]
    role_images: list[RoleImageResult]
    shot_role_map: list[ShotRoleMap]
    shots: list[ShotResult]
    warnings: list[str] = Field(default_factory=list)


class WorkflowLogEntry(BaseModel):
    timestamp: datetime
    stage: str
    message: str
    level: str = "info"


class WorkflowJobStatus(BaseModel):
    job_id: str
    status: str
    progress_percent: int = 0
    current_stage: str | None = None
    current_message: str | None = None
    logs: list[WorkflowLogEntry] = Field(default_factory=list)
    result: WorkflowRunResponse | None = None
    error_message: str | None = None
    saved_artifacts: bool = False
    saved_result_path: str | None = None
    saved_assets_zip_path: str | None = None
    saved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowSavedRunSummary(BaseModel):
    job_id: str
    title: str
    created_at: datetime | None = None
    saved_at: datetime
    saved_result_path: str
    saved_assets_zip_path: str
    role_image_count: int = 0
    shot_first_frame_count: int = 0
    shot_audio_count: int = 0
    shot_subtitle_count: int = 0

