from app.core.config import settings
from app.models.schemas import WorkflowRunRequest


class RequestConfigResolverError(RuntimeError):
    pass


def resolve_request_config(request: WorkflowRunRequest) -> WorkflowRunRequest:
    default_text_model = request.text_models.default_model or request.connection.chat_model
    resolved_connection = request.connection.model_copy(
        update={
            "api_key": request.connection.api_key or settings.doubao_api_key,
            "chat_model": default_text_model,
            "video_model": request.connection.video_model or settings.doubao_video_model,
        }
    )
    if not resolved_connection.api_key:
        raise RequestConfigResolverError(
            "未配置豆包 API Key。请在 backend/.env 中设置 APP_DOUBAO_API_KEY。"
        )
    if not resolved_connection.chat_model:
        raise RequestConfigResolverError(
            "未配置主文本模型。请在前端选择主文本模型，或在请求里传入 connection.chat_model / text_models.default_model。"
        )

    resolved_text_models = request.text_models.model_copy(
        update={
            "default_model": resolved_connection.chat_model,
        }
    )

    resolved_tts = request.tts.model_copy(
        update={
            "app_id": request.tts.app_id or settings.tts_app_id,
            "access_token": request.tts.access_token or settings.tts_access_token,
            "cluster": request.tts.cluster or settings.tts_cluster,
        }
    )
    if resolved_tts.enabled and not (resolved_tts.app_id and resolved_tts.access_token):
        raise RequestConfigResolverError(
            "已启用语音合成，但 backend/.env 中缺少 APP_TTS_APP_ID 或 APP_TTS_ACCESS_TOKEN。"
        )

    return request.model_copy(
        update={
            "connection": resolved_connection,
            "text_models": resolved_text_models,
            "tts": resolved_tts,
        }
    )
