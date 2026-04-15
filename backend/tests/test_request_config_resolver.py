from app.core.config import settings
from app.models.schemas import (
    DoubaoConnectionConfig,
    TtsConfig,
    WorkflowRunRequest,
    WorkflowTextModels,
)
from app.services.request_config_resolver import (
    RequestConfigResolverError,
    resolve_request_config,
)


def test_resolve_request_config_uses_env_defaults() -> None:
    original_api_key = settings.doubao_api_key
    original_video_model = settings.doubao_video_model
    original_tts_app_id = settings.tts_app_id
    original_tts_access_token = settings.tts_access_token

    settings.doubao_api_key = "env-api-key"
    settings.doubao_video_model = "env-video-model"
    settings.tts_app_id = "env-app-id"
    settings.tts_access_token = "env-access-token"
    try:
        request = WorkflowRunRequest(
            story_text="测试剧情",
            connection=DoubaoConnectionConfig(
                chat_model="doubao-seed-1.6-flash",
                image_model="doubao-seedream-4.0",
            ),
            tts=TtsConfig(enabled=True),
        )

        resolved = resolve_request_config(request)

        assert resolved.connection.api_key == "env-api-key"
        assert resolved.connection.chat_model == "doubao-seed-1.6-flash"
        assert resolved.connection.video_model == "env-video-model"
        assert resolved.text_models.default_model == "doubao-seed-1.6-flash"
        assert resolved.tts.app_id == "env-app-id"
        assert resolved.tts.access_token == "env-access-token"
    finally:
        settings.doubao_api_key = original_api_key
        settings.doubao_video_model = original_video_model
        settings.tts_app_id = original_tts_app_id
        settings.tts_access_token = original_tts_access_token


def test_resolve_request_config_raises_without_api_key() -> None:
    original_api_key = settings.doubao_api_key
    settings.doubao_api_key = None
    try:
        request = WorkflowRunRequest(
            story_text="测试剧情",
            connection=DoubaoConnectionConfig(chat_model="doubao-seed-1.6-flash"),
        )

        try:
            resolve_request_config(request)
        except RequestConfigResolverError as exc:
            assert "APP_DOUBAO_API_KEY" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("Expected RequestConfigResolverError to be raised.")
    finally:
        settings.doubao_api_key = original_api_key


def test_resolve_request_config_accepts_default_text_model_from_text_models() -> None:
    original_api_key = settings.doubao_api_key
    settings.doubao_api_key = "env-api-key"
    try:
        request = WorkflowRunRequest(
            story_text="测试剧情",
            connection=DoubaoConnectionConfig(chat_model=None),
            text_models=WorkflowTextModels(
                default_model="doubao-seed-2-0-lite",
                camera_model="doubao-seed-1-6-flash",
                shot_image_prompt_model="doubao-seed-1-6-thinking",
            ),
        )

        resolved = resolve_request_config(request)

        assert resolved.connection.chat_model == "doubao-seed-2-0-lite"
        assert resolved.text_models.default_model == "doubao-seed-2-0-lite"
        assert resolved.text_models.camera_model == "doubao-seed-1-6-flash"
        assert resolved.text_models.shot_image_prompt_model == "doubao-seed-1-6-thinking"
    finally:
        settings.doubao_api_key = original_api_key


def test_text_model_stage_resolver_supports_shot_image_prompt() -> None:
    models = WorkflowTextModels(
        default_model="default-text-model",
        shot_image_prompt_model="shot-image-prompt-model",
    )

    assert models.resolve_for_stage("shot_image_prompt") == "shot-image-prompt-model"
