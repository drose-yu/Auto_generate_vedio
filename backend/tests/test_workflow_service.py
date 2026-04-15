import pytest

from app.models.schemas import RoleDescription, RoleImageResult, ShotRoleMap, TtsConfig, WorkflowTextModels
from app.services.doubao_client import DoubaoClientError
from app.services.workflow_service import (
    WorkflowService,
    _compose_shot_video_prompt,
    _normalize_shot_continuity_plan,
    _summarize_tts_runtime,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class DummyImageClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"image_model": "ep-image"})()
        self.prompts: list[str] = []

    async def generate_image(self, *, prompt: str) -> str:
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            raise DoubaoClientError(
                'Failed during image generation: 400 {"error":{"code":"OutputImageSensitiveContentDetected","message":"blocked"}}'
            )
        return "https://example.com/retry-success.jpg"


class DummyTtsPermissionClient:
    def __init__(self) -> None:
        self.tts_attempts = 0
        self.config = type("Config", (), {"image_model": None})()
        self._chat_calls = 0

    async def chat_json(self, **kwargs):
        self._chat_calls += 1
        if self._chat_calls % 2 == 1:
            return {"camera_prompt": "camera ok"}
        return {"image_prompt": "first frame prompt"}

    async def synthesize_speech(self, *, text: str, tts_config: TtsConfig) -> str:
        self.tts_attempts += 1
        raise DoubaoClientError(
            'Failed during speech synthesis: 403 {"reqid":"x","code":3001,"message":"[resource_id=volc.tts.default] requested resource not granted"}'
        )


class DummyFirstFrameClient:
    def __init__(
        self,
        *,
        invalid_first_frame_prompt: bool = False,
        image_model: str | None = "ep-image",
        video_model: str | None = None,
        video_max_shots: int = 1,
    ) -> None:
        self.config = type(
            "Config",
            (),
            {
                "image_model": image_model,
                "video_model": video_model,
                "video_duration_seconds": 5,
                "video_max_shots": video_max_shots,
            },
        )()
        self.invalid_first_frame_prompt = invalid_first_frame_prompt
        self.image_prompts: list[str] = []
        self.video_calls: list[tuple[str, str, int | None]] = []
        self.chat_user_prompts: list[str] = []
        self._chat_calls = 0

    async def chat_json(self, **kwargs):
        user_prompt = kwargs.get("user_prompt")
        if isinstance(user_prompt, str):
            self.chat_user_prompts.append(user_prompt)
        self._chat_calls += 1
        if self._chat_calls % 2 == 1:
            return {"camera_prompt": "camera prompt for shot"}
        if self.invalid_first_frame_prompt:
            return {"unexpected_key": "bad payload"}
        return {"image_prompt": "first frame prompt"}

    async def generate_image(self, *, prompt: str) -> str:
        self.image_prompts.append(prompt)
        return "https://example.com/first-frame.jpg"

    async def generate_video_from_image(
        self,
        *,
        prompt: str,
        image_url: str,
        audio_url: str | None = None,
        duration_seconds: int | None = None,
    ) -> str:
        self.video_calls.append((prompt, image_url, duration_seconds))
        return "https://example.com/shot-video.mp4"


@pytest.mark.anyio
async def test_generate_role_images_retries_with_softened_prompt_on_sensitive_output() -> None:
    service = WorkflowService()
    client = DummyImageClient()
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="old monk",
            gender="male",
            age="80+",
            appearance="aged monk",
            outfit="patched gray robe",
            mood="calm",
            atmosphere="old temple",
            full_prompt="old monk in ruined temple",
        )
    ]

    result = await service._generate_role_images(
        client=client,
        descriptions=descriptions,
        max_images=1,
        warnings=warnings,
        reporter=None,
        style_lock_clause="STYLE_LOCK",
    )

    assert len(client.prompts) == 2
    assert client.prompts[0] != client.prompts[1]
    assert "STYLE_LOCK" in client.prompts[0]
    assert "STYLE_LOCK" in client.prompts[1]
    assert result[0].image_url == "https://example.com/retry-success.jpg"
    assert result[0].warning is not None


@pytest.mark.anyio
async def test_build_shots_stops_remaining_tts_after_permission_error() -> None:
    service = WorkflowService()
    client = DummyTtsPermissionClient()
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="Lead",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="calm",
            atmosphere="temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [
        ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 1"),
        ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 2"),
    ]
    role_images = [RoleImageResult(role_name="Lead", prompt="lead role", image_url="https://example.com/lead.jpg")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["first scene", "second scene"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=True,
        tts_config=TtsConfig(enabled=True, app_id="app-id", access_token="token"),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 2
    assert client.tts_attempts == 1
    assert len(warnings) == 1
    assert "TTS resource is not granted" in warnings[0]
    assert f"voice_type={TtsConfig().voice_type}" in warnings[0]


@pytest.mark.anyio
async def test_build_shots_generates_first_frame_prompt_and_image() -> None:
    service = WorkflowService()
    client = DummyFirstFrameClient()
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="Lead",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="calm",
            atmosphere="temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 1")]
    role_images = [RoleImageResult(role_name="Lead", prompt="lead role", image_url="https://example.com/lead.jpg")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["first scene"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 1
    assert shots[0].camera_prompt == "camera prompt for shot"
    assert "first frame prompt" in (shots[0].first_frame_prompt or "")
    assert "STYLE_LOCK" in (shots[0].first_frame_prompt or "")
    assert shots[0].first_frame_url == "https://example.com/first-frame.jpg"
    assert len(client.image_prompts) == 1
    assert "first frame prompt" in client.image_prompts[0]
    assert "STYLE_LOCK" in client.image_prompts[0]
    assert warnings == []


@pytest.mark.anyio
async def test_build_shots_includes_only_shot_role_reference_urls_in_first_frame_prompt() -> None:
    service = WorkflowService()
    client = DummyFirstFrameClient()
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="Lead",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="calm",
            atmosphere="temple",
            full_prompt="lead role",
        ),
        RoleDescription(
            name="Other",
            gender="male",
            age="30",
            appearance="older",
            outfit="robe",
            mood="calm",
            atmosphere="temple",
            full_prompt="other role",
        ),
    ]
    shot_role_map = [ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 1")]
    role_images = [
        RoleImageResult(role_name="Lead", prompt="lead role", image_url="https://example.com/lead.jpg"),
        RoleImageResult(role_name="Other", prompt="other role", image_url="https://example.com/other.jpg"),
    ]

    shots = await service._build_shots(
        client=client,
        key_highlights=["first scene"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 1
    assert len(client.chat_user_prompts) == 2
    first_frame_user_prompt = client.chat_user_prompts[1]
    assert "Reference role image URLs (shot-only): ['https://example.com/lead.jpg']" in first_frame_user_prompt
    assert "https://example.com/other.jpg" not in first_frame_user_prompt
    assert "Global style lock clause: STYLE_LOCK" in first_frame_user_prompt


@pytest.mark.anyio
async def test_build_shots_includes_continuity_context_in_prompts() -> None:
    service = WorkflowService()
    client = DummyFirstFrameClient(video_model="ep-video")
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="Lead",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="calm",
            atmosphere="temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 1")]
    role_images = [RoleImageResult(role_name="Lead", prompt="lead role", image_url="https://example.com/lead.jpg")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["first scene"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
        continuity_plan=[
            {
                "start_state": "Lead stands before the hall gate.",
                "end_state": "Lead steps into the hall.",
                "transition_to_next": "continue with interior close-up.",
            }
        ],
    )

    assert len(shots) == 1
    assert len(client.chat_user_prompts) >= 2
    assert "Continuity start state: Lead stands before the hall gate." in client.chat_user_prompts[0]
    assert "Target end state for this shot: Lead steps into the hall." in client.chat_user_prompts[0]
    assert len(client.video_calls) == 1
    assert "Continuity constraints:" in client.video_calls[0][0]
    assert "Lead steps into the hall." in client.video_calls[0][0]
    assert shots[0].continuity_start_state == "Lead stands before the hall gate."
    assert shots[0].continuity_end_state == "Lead steps into the hall."
    assert shots[0].continuity_transition_to_next == "continue with interior close-up."
    assert "Continuity constraints:" in (shots[0].shot_video_prompt or "")


@pytest.mark.anyio
async def test_build_shots_generates_video_when_video_model_enabled() -> None:
    service = WorkflowService()
    client = DummyFirstFrameClient(video_model="ep-video")
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="Lead",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="calm",
            atmosphere="temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 1")]
    role_images = [RoleImageResult(role_name="Lead", prompt="lead role", image_url="https://example.com/lead.jpg")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["first scene"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 1
    assert shots[0].shot_video_url == "https://example.com/shot-video.mp4"
    assert len(client.video_calls) == 1
    assert "Shot story constraints (highest priority):" in client.video_calls[0][0]
    assert "- Story beat: first scene" in client.video_calls[0][0]
    assert "camera prompt for shot" in client.video_calls[0][0]
    assert client.video_calls[0][1] == "https://example.com/first-frame.jpg"
    assert client.video_calls[0][2] == 5


@pytest.mark.anyio
async def test_build_shots_respects_video_max_shots_limit() -> None:
    service = WorkflowService()
    client = DummyFirstFrameClient(video_model="ep-video", video_max_shots=1)
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="Lead",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="calm",
            atmosphere="temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [
        ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 1"),
        ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 2"),
    ]
    role_images = [RoleImageResult(role_name="Lead", prompt="lead role", image_url="https://example.com/lead.jpg")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["first scene", "second scene"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=role_images,
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False),
        video_max_shots=1,
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 2
    assert shots[0].shot_video_url == "https://example.com/shot-video.mp4"
    assert shots[1].shot_video_url is None
    assert len(client.video_calls) == 1


@pytest.mark.anyio
async def test_build_shots_falls_back_to_camera_prompt_when_first_frame_payload_invalid() -> None:
    service = WorkflowService()
    client = DummyFirstFrameClient(invalid_first_frame_prompt=True, image_model=None)
    warnings: list[str] = []
    descriptions = [
        RoleDescription(
            name="Lead",
            gender="male",
            age="20",
            appearance="young",
            outfit="robe",
            mood="calm",
            atmosphere="temple",
            full_prompt="lead role",
        )
    ]
    shot_role_map = [ShotRoleMap(roles_in_shot=["Lead"], scene_note="scene 1")]

    shots = await service._build_shots(
        client=client,
        key_highlights=["first scene"],
        descriptions=descriptions,
        shot_role_map=shot_role_map,
        role_images=[],
        tts_enabled=False,
        tts_config=TtsConfig(enabled=False),
        warnings=warnings,
        reporter=None,
        text_models=WorkflowTextModels(default_model="ep-text"),
        default_text_model="ep-text",
        style_lock_clause="STYLE_LOCK",
    )

    assert len(shots) == 1
    assert shots[0].camera_prompt == "camera prompt for shot"
    assert shots[0].first_frame_prompt == "camera prompt for shot"
    assert shots[0].first_frame_url is None
    assert any("Falling back to camera prompt" in warning for warning in warnings)


def test_summarize_tts_runtime_masks_sensitive_fields() -> None:
    summary = _summarize_tts_runtime(
        TtsConfig(
            enabled=True,
            app_id="8529436273",
            access_token="secret-token",
            voice_type="zh_female_xiaohe_uranus_bigtts",
        )
    )

    assert "voice_type=zh_female_xiaohe_uranus_bigtts" in summary
    assert "app_id=******6273" in summary
    assert "access_token_present=yes" in summary
    assert "secret-token" not in summary


def test_compose_shot_video_prompt_keeps_story_alignment_constraints() -> None:
    prompt = _compose_shot_video_prompt(
        highlight="Lu Chen bows to the hidden immortal and requests guidance.",
        scene_note="Temple hall, incense smoke, respectful tension.",
        narration_text="陆尘恭敬行礼，恳求仙尊指点。",
        roles_in_shot=["Lu Chen", "Hidden Immortal"],
        camera_prompt="Medium shot, push-in to clasped hands, then pan to elder face.",
    )
    assert "Shot story constraints (highest priority):" in prompt
    assert "Lu Chen bows to the hidden immortal" in prompt
    assert "Medium shot, push-in to clasped hands" in prompt
    assert "Do not invent unrelated actions" in prompt


def test_compose_shot_video_prompt_includes_continuity_constraints_when_provided() -> None:
    prompt = _compose_shot_video_prompt(
        highlight="Hero steps out of the gate.",
        scene_note="Courtyard at dusk.",
        narration_text="主角迈出院门。",
        roles_in_shot=["Hero"],
        camera_prompt="Tracking shot following Hero.",
        previous_shot_end_state="Hero reaches the gate.",
        continuity_start_state="Hero stands at the gate.",
        continuity_end_state="Hero is outside the courtyard.",
        transition_to_next="Cut to street reaction shot.",
    )

    assert "Continuity constraints:" in prompt
    assert "Hero reaches the gate." in prompt
    assert "Hero is outside the courtyard." in prompt
    assert "Cut to street reaction shot." in prompt


def test_normalize_shot_continuity_plan_supports_shots_wrapper() -> None:
    normalized = _normalize_shot_continuity_plan(
        payload={
            "shots": [
                {
                    "start_state": " A at door ",
                    "end_state": "A opens door",
                    "next_transition": "follow hand movement",
                }
            ]
        },
        expected_len=1,
    )
    assert normalized == [
        {
            "start_state": "A at door",
            "end_state": "A opens door",
            "transition_to_next": "follow hand movement",
        }
    ]
