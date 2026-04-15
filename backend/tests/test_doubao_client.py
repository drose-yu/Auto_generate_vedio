import pytest
import httpx

from app.models.schemas import DoubaoConnectionConfig, TtsConfig
from app.services.doubao_client import DoubaoClient, DoubaoClientError, _compose_video_prompt


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_chat_json_retries_after_remote_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DoubaoClient(
        DoubaoConnectionConfig(
            api_key="test-key",
            chat_model="ep-test-chat",
        )
    )
    attempts = 0

    async def fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", url, headers=headers, json=json)
        if attempts == 1:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.",
                request=request,
            )
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": '{"camera_prompt":"ok"}'}}]},
        )

    monkeypatch.setattr(client._client, "post", fake_post)

    result = await client.chat_json(
        system_prompt="system",
        user_prompt="user",
    )

    await client.aclose()

    assert attempts == 2
    assert result == {"camera_prompt": "ok"}


@pytest.mark.anyio
async def test_chat_json_wraps_request_error_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DoubaoClient(
        DoubaoConnectionConfig(
            api_key="test-key",
            chat_model="ep-test-chat",
        )
    )
    attempts = 0

    async def fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", url, headers=headers, json=json)
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.",
            request=request,
        )

    monkeypatch.setattr(client._client, "post", fake_post)

    with pytest.raises(
        DoubaoClientError,
        match="request error after 3 attempts: Server disconnected without sending a response.",
    ):
        await client.chat_json(
            system_prompt="system",
            user_prompt="user",
        )

    await client.aclose()

    assert attempts == 3


@pytest.mark.anyio
async def test_synthesize_speech_retries_retryable_http_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DoubaoClient(
        DoubaoConnectionConfig(
            api_key="test-key",
            chat_model="ep-test-chat",
        )
    )
    attempts = 0
    tts_config = TtsConfig(
        enabled=True,
        endpoint="https://openspeech.bytedance.com/api/v1/tts",
        app_id="app-id",
        access_token="tts-token",
    )

    async def fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", url, headers=headers, json=json)
        if attempts == 1:
            return httpx.Response(
                503,
                request=request,
                text='{"error":{"message":"temporary unavailable"}}',
            )
        return httpx.Response(
            200,
            request=request,
            json={"audio_url": "https://example.com/audio.mp3"},
        )

    monkeypatch.setattr(client._client, "post", fake_post)

    result = await client.synthesize_speech(
        text="hello",
        tts_config=tts_config,
    )

    await client.aclose()

    assert attempts == 2
    assert result == "https://example.com/audio.mp3"


@pytest.mark.anyio
async def test_generate_video_from_image_returns_direct_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DoubaoClient(
        DoubaoConnectionConfig(
            api_key="test-key",
            chat_model="ep-test-chat",
            video_model="ep-test-video",
        )
    )

    async def fake_post_json_with_retry(**kwargs) -> httpx.Response:
        request = httpx.Request("POST", kwargs["url"], headers=kwargs.get("headers"))
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"url": "https://example.com/shot01.mp4"}]},
        )

    monkeypatch.setattr(client, "_post_json_with_retry", fake_post_json_with_retry)

    result = await client.generate_video_from_image(
        prompt="camera prompt",
        image_url="https://example.com/first-frame.jpg",
    )

    await client.aclose()

    assert result == "https://example.com/shot01.mp4"


@pytest.mark.anyio
async def test_generate_video_from_image_polls_task_until_video_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DoubaoClient(
        DoubaoConnectionConfig(
            api_key="test-key",
            chat_model="ep-test-chat",
            video_model="ep-test-video",
            video_poll_timeout_seconds=60,
            video_poll_interval_seconds=1,
        )
    )
    poll_calls = 0

    async def fake_post_json_with_retry(**kwargs) -> httpx.Response:
        request = httpx.Request("POST", kwargs["url"], headers=kwargs.get("headers"))
        return httpx.Response(
            200,
            request=request,
            json={"data": {"task_id": "cgt-task-001", "status": "queued"}},
        )

    async def fake_get_json_with_retry(**kwargs) -> httpx.Response:
        nonlocal poll_calls
        poll_calls += 1
        request = httpx.Request("GET", kwargs["url"], headers=kwargs.get("headers"))
        if poll_calls == 1:
            return httpx.Response(
                200,
                request=request,
                json={"data": {"status": "processing"}},
            )
        return httpx.Response(
            200,
            request=request,
            json={"data": {"status": "succeeded", "result": {"video_url": "https://example.com/shot01.mp4"}}},
        )

    monkeypatch.setattr(client, "_post_json_with_retry", fake_post_json_with_retry)
    monkeypatch.setattr(client, "_get_json_with_retry", fake_get_json_with_retry)

    result = await client.generate_video_from_image(
        prompt="camera prompt",
        image_url="https://example.com/first-frame.jpg",
    )

    await client.aclose()

    assert result == "https://example.com/shot01.mp4"
    assert poll_calls == 2


@pytest.mark.anyio
async def test_generate_video_from_image_retries_without_audio_when_content_mixing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DoubaoClient(
        DoubaoConnectionConfig(
            api_key="test-key",
            chat_model="ep-test-chat",
            video_model="ep-test-video",
        )
    )
    call_has_audio: list[bool] = []

    async def fake_post_json_with_retry(**kwargs) -> httpx.Response:
        payload = kwargs["payload"]
        content = payload.get("content") or []
        has_audio = any(
            isinstance(item, dict) and item.get("type") == "audio_url"
            for item in content
        )
        call_has_audio.append(has_audio)

        if has_audio:
            raise DoubaoClientError(
                'Failed during video generation: 400 {"error":{"code":"InvalidParameter","message":"The parameter `content` specified in the request is not valid: first/last frame content cannot be mixed with reference media content.","param":"content","type":"BadRequest"}}'
            )

        request = httpx.Request("POST", kwargs["url"], headers=kwargs.get("headers"))
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"url": "https://example.com/shot01.mp4"}]},
        )

    monkeypatch.setattr(client, "_post_json_with_retry", fake_post_json_with_retry)

    result = await client.generate_video_from_image(
        prompt="camera prompt",
        image_url="https://example.com/first-frame.jpg",
        audio_url="https://example.com/shot01.mp3",
    )

    await client.aclose()

    assert result == "https://example.com/shot01.mp4"
    assert call_has_audio == [True, False]


def test_compose_video_prompt_contains_motion_timeline_and_suffix() -> None:
    prompt = _compose_video_prompt(
        prompt="A swordsman turns and draws a blade in rain",
        duration_seconds=5,
    )
    assert "Time-coded motion plan" in prompt
    assert "wind-up -> peak action -> settle" in prompt
    assert "End pose must be visually different from the first frame" in prompt
    assert "--duration 5" in prompt
    assert "--camerafixed false" in prompt


def test_compose_video_prompt_keeps_auto_duration_minus_one() -> None:
    prompt = _compose_video_prompt(
        prompt="A swordsman turns and draws a blade in rain",
        duration_seconds=-1,
    )
    assert "Time-coded motion plan" in prompt
    assert "0%-30%" in prompt
    assert "--duration -1" in prompt
