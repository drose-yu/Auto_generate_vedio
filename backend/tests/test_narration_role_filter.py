import pytest

from app.models.schemas import RoleDescription, RoleImageResult, ShotRoleMap, TtsConfig, WorkflowTextModels
from app.services.workflow_service import WorkflowService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class DummyNarrationFilterClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"image_model": None, "video_model": None})()
        self.rewrite_calls = 0

    async def chat_json(self, **kwargs):
        user_prompt = kwargs.get("user_prompt", "")
        if "Generate one camera prompt for this shot." in user_prompt:
            return {"camera_prompt": "camera prompt for shot"}
        if "Reference role image URLs (shot-only):" in user_prompt:
            return {"image_prompt": "first frame prompt"}
        if "Original narration text:" in user_prompt:
            self.rewrite_calls += 1
            return {"narration_text": "他在雨夜翻开旧书，心里又怕又期待。"}
        raise AssertionError(f"Unexpected chat_json user_prompt: {user_prompt}")


@pytest.mark.anyio
async def test_build_shots_filters_role_name_from_narration_when_enabled() -> None:
    service = WorkflowService()
    client = DummyNarrationFilterClient()
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="书生",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="nervous",
            atmosphere="rainy temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [ShotRoleMap(roles_in_shot=["书生"], scene_note="scene 1")]
    role_images = [RoleImageResult(role_name="书生", prompt="lead role", image_url="https://example.com/lead.jpg")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["书生在雨夜翻开旧书，心里又怕又期待。"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False, remove_role_names=True),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 1
    assert client.rewrite_calls == 0
    assert "书生" in shots[0].narration_text


@pytest.mark.anyio
async def test_build_shots_keeps_role_name_when_filter_disabled() -> None:
    service = WorkflowService()
    client = DummyNarrationFilterClient()
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="书生",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="nervous",
            atmosphere="rainy temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [ShotRoleMap(roles_in_shot=["书生"], scene_note="scene 1")]
    role_images = [RoleImageResult(role_name="书生", prompt="lead role", image_url="https://example.com/lead.jpg")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["书生在雨夜翻开旧书，心里又怕又期待。"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False, remove_role_names=False),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 1
    assert client.rewrite_calls == 0
    assert "书生" in shots[0].narration_text


@pytest.mark.anyio
async def test_build_shots_keeps_first_appearance_name_and_filters_later_mentions() -> None:
    service = WorkflowService()
    client = DummyNarrationFilterClient()
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="书生",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="nervous",
            atmosphere="rainy temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [
        ShotRoleMap(roles_in_shot=["书生"], scene_note="scene 1"),
        ShotRoleMap(roles_in_shot=["书生"], scene_note="scene 2"),
    ]
    role_images = [RoleImageResult(role_name="书生", prompt="lead role", image_url="https://example.com/lead.jpg")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["书生在雨夜翻开旧书。", "书生一路奔向考场。"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False, remove_role_names=True),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 2
    assert "书生" in shots[0].narration_text
    assert "书生" not in shots[1].narration_text
    assert client.rewrite_calls == 1
