import base64
import asyncio
from collections.abc import Awaitable, Callable
import json
import math
import uuid
from typing import Any

import httpx

from app.models.schemas import DoubaoConnectionConfig, TtsConfig
from app.services.helpers import extract_json_payload


class DoubaoClientError(RuntimeError):
    pass


VideoPollProgressCallback = Callable[[str, int, str | None], Awaitable[None] | None]


class DoubaoClient:
    def __init__(self, config: DoubaoConnectionConfig):
        self.config = config
        self._client = httpx.AsyncClient(timeout=config.timeout_seconds)
        self._max_attempts = 3
        self._retryable_status_codes = {408, 429, 500, 502, 503, 504}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.8,
        model: str | None = None,
    ) -> Any:
        payload = {
            "model": model or self.config.chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        response = await self._post_json_with_retry(
            url=f"{self.config.base_url}/chat/completions",
            headers=self._ark_headers(),
            payload=payload,
            action="chat completion",
        )
        content = self._extract_message_content(response.json())
        return extract_json_payload(content)

    async def generate_image(self, *, prompt: str) -> str:
        if not self.config.image_model:
            raise DoubaoClientError("Image model is not configured.")

        payload = {
            "model": self.config.image_model,
            "prompt": prompt,
            "size": self.config.image_size,
            "response_format": "url",
            "watermark": True,
        }
        response = await self._post_json_with_retry(
            url=f"{self.config.base_url}/images/generations",
            headers=self._ark_headers(),
            payload=payload,
            action="image generation",
        )
        body = response.json()
        top_level_error = body.get("error")
        if isinstance(top_level_error, dict):
            raise DoubaoClientError(_format_image_error(top_level_error))

        data = body.get("data") or []
        if not data:
            raise DoubaoClientError("Image generation returned no data.")

        first_item = data[0]
        nested_error = first_item.get("error") if isinstance(first_item, dict) else None
        if isinstance(nested_error, dict):
            raise DoubaoClientError(_format_image_error(nested_error))

        image_url = first_item.get("url")
        if image_url:
            return image_url

        b64_json = first_item.get("b64_json")
        if b64_json:
            return f"data:image/png;base64,{b64_json}"

        raise DoubaoClientError("Image generation response did not contain url or b64_json.")

    async def generate_video_from_image(
        self,
        *,
        prompt: str,
        image_url: str,
        audio_url: str | None = None,
        duration_seconds: int | None = None,
        frame_count: int | None = None,
        on_poll_progress: VideoPollProgressCallback | None = None,
    ) -> str:
        if not self.config.video_model:
            raise DoubaoClientError("Video model is not configured.")

        duration = duration_seconds or self.config.video_duration_seconds
        payload = {
            "model": self.config.video_model,
            "content": _build_video_content(
                prompt=prompt,
                image_url=image_url,
                audio_url=audio_url,
                duration_seconds=duration,
                frame_count=frame_count,
            ),
        }
        try:
            response = await self._post_json_with_retry(
                url=f"{self.config.base_url}/contents/generations/tasks",
                headers=self._ark_headers(),
                payload=payload,
                action="video generation",
            )
        except DoubaoClientError as exc:
            if audio_url and _is_video_content_mixing_error(str(exc)):
                fallback_payload = {
                    "model": self.config.video_model,
                    "content": _build_video_content(
                        prompt=prompt,
                        image_url=image_url,
                        audio_url=None,
                        duration_seconds=duration,
                        frame_count=frame_count,
                    ),
                }
                response = await self._post_json_with_retry(
                    url=f"{self.config.base_url}/contents/generations/tasks",
                    headers=self._ark_headers(),
                    payload=fallback_payload,
                    action="video generation",
                )
            else:
                raise
        body = response.json()
        top_level_error = body.get("error")
        if isinstance(top_level_error, dict):
            raise DoubaoClientError(_format_video_error(top_level_error))

        url = _extract_video_url(body)
        if url:
            return url

        task_id = _extract_video_task_id(body)
        if not task_id:
            raise DoubaoClientError("Video generation response did not contain url or task id.")

        return await self._poll_video_task(task_id, on_poll_progress=on_poll_progress)

    async def synthesize_speech(self, *, text: str, tts_config: TtsConfig) -> str:
        if _is_tts_sse_endpoint(tts_config.endpoint):
            return await self._synthesize_speech_via_sse(text=text, tts_config=tts_config)

        is_seed_tts_v2 = _is_seed_tts_v2_endpoint(tts_config.endpoint)
        request_payload: dict[str, Any] = {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "operation": "query",
        }
        if not is_seed_tts_v2:
            request_payload["text_type"] = "plain"

        payload = {
            "app": {
                "appid": tts_config.app_id,
                # For Seed TTS 2.0, this field only needs to be non-empty.
                "token": "seed_tts_v2" if is_seed_tts_v2 else tts_config.access_token,
                "cluster": tts_config.cluster,
            },
            "user": {"uid": tts_config.uid},
            "audio": {
                "voice_type": tts_config.voice_type,
                "encoding": "mp3",
                "speed_ratio": tts_config.speed,
            },
            "request": request_payload,
        }
        headers = {
            "Authorization": f"Bearer;{tts_config.access_token}",
            "Content-Type": "application/json",
        }
        if is_seed_tts_v2:
            headers["X-Api-Resource-Id"] = "seed-tts-2.0"

        response = await self._post_json_with_retry(
            url=tts_config.endpoint,
            headers=headers,
            payload=payload,
            action="speech synthesis",
        )
        data = response.json()

        audio_url = data.get("audio_url") or data.get("url")
        if isinstance(audio_url, str) and audio_url:
            return audio_url

        raw_data = data.get("data")
        if isinstance(raw_data, str):
            return _audio_data_url(raw_data)
        if isinstance(raw_data, dict):
            nested_url = raw_data.get("audio_url") or raw_data.get("url")
            if isinstance(nested_url, str) and nested_url:
                return nested_url
            for key in ("audio", "data", "audio_data"):
                value = raw_data.get(key)
                if isinstance(value, str) and value:
                    return _audio_data_url(value)

        raise DoubaoClientError("Speech synthesis response did not contain audio data.")

    async def _synthesize_speech_via_sse(self, *, text: str, tts_config: TtsConfig) -> str:
        headers = {
            "X-Api-App-Id": str(tts_config.app_id or ""),
            "X-Api-Access-Key": str(tts_config.access_token or ""),
            "X-Api-Resource-Id": "seed-tts-2.0",
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }
        payload = {
            "user": {"uid": tts_config.uid},
            "req_params": {
                "text": text,
                "speaker": tts_config.voice_type,
                "audio_params": {
                    "format": "mp3",
                },
            },
        }

        last_request_error: httpx.RequestError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                async with self._client.stream(
                    "POST",
                    tts_config.endpoint,
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code in self._retryable_status_codes and attempt < self._max_attempts:
                        await asyncio.sleep(self._retry_delay_seconds(attempt))
                        continue

                    self._raise_for_status(response, "speech synthesis")

                    audio_buffer = bytearray()
                    event_data_parts: list[str] = []
                    done = False

                    async for raw_line in response.aiter_lines():
                        line = (raw_line or "").strip()
                        if not line:
                            if event_data_parts:
                                event_data = "\n".join(event_data_parts)
                                event_data_parts = []
                                parsed = json.loads(event_data)
                                if isinstance(parsed, dict):
                                    code = parsed.get("code", 0)
                                    if code == 0:
                                        audio_url = parsed.get("audio_url") or parsed.get("url")
                                        if isinstance(audio_url, str) and audio_url:
                                            return audio_url
                                        chunk = parsed.get("data")
                                        if isinstance(chunk, str) and chunk:
                                            try:
                                                audio_buffer.extend(base64.b64decode(chunk))
                                            except Exception as exc:  # pragma: no cover - upstream format issues
                                                raise DoubaoClientError(
                                                    f"Invalid base64 audio chunk in SSE response: {exc}"
                                                ) from exc
                                    elif code == 20_000_000:
                                        done = True
                                        break
                                    elif isinstance(code, int) and code > 0:
                                        raise DoubaoClientError(f"Speech synthesis failed: {parsed}")
                            continue
                        if line.startswith(":"):
                            continue
                        if line.startswith("data:"):
                            event_data_parts.append(line[5:].lstrip())

                    if not done and event_data_parts:
                        parsed = json.loads("\n".join(event_data_parts))
                        if isinstance(parsed, dict):
                            code = parsed.get("code", 0)
                            if isinstance(code, int) and code > 0 and code != 20_000_000:
                                raise DoubaoClientError(f"Speech synthesis failed: {parsed}")
                            chunk = parsed.get("data")
                            if code == 0 and isinstance(chunk, str) and chunk:
                                audio_buffer.extend(base64.b64decode(chunk))

                    if audio_buffer:
                        return _audio_bytes_data_url(bytes(audio_buffer))
                    raise DoubaoClientError("Speech synthesis SSE response did not contain audio data.")
            except httpx.RequestError as exc:
                last_request_error = exc
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._retry_delay_seconds(attempt))
                    continue
                raise DoubaoClientError(_format_request_error("speech synthesis", exc, attempt)) from exc
            except json.JSONDecodeError as exc:
                raise DoubaoClientError(f"Speech synthesis SSE response is not valid JSON: {exc}") from exc

        if last_request_error is not None:  # pragma: no cover
            raise DoubaoClientError(
                _format_request_error("speech synthesis", last_request_error, self._max_attempts)
            ) from last_request_error
        raise DoubaoClientError("Speech synthesis request did not complete.")  # pragma: no cover

    def _ark_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_json_with_retry(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        action: str,
    ) -> httpx.Response:
        last_request_error: httpx.RequestError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.post(
                    url,
                    headers=headers,
                    json=payload,
                )
            except httpx.RequestError as exc:
                last_request_error = exc
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._retry_delay_seconds(attempt))
                    continue
                raise DoubaoClientError(_format_request_error(action, exc, attempt)) from exc

            if response.status_code in self._retryable_status_codes and attempt < self._max_attempts:
                await asyncio.sleep(self._retry_delay_seconds(attempt))
                continue

            self._raise_for_status(response, action)
            return response

        if last_request_error is not None:  # pragma: no cover
            raise DoubaoClientError(
                _format_request_error(action, last_request_error, self._max_attempts)
            ) from last_request_error
        raise DoubaoClientError(f"Failed during {action}: request did not complete.")  # pragma: no cover

    async def _get_json_with_retry(
        self,
        *,
        url: str,
        headers: dict[str, str],
        action: str,
    ) -> httpx.Response:
        last_request_error: httpx.RequestError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.get(url, headers=headers)
            except httpx.RequestError as exc:
                last_request_error = exc
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._retry_delay_seconds(attempt))
                    continue
                raise DoubaoClientError(_format_request_error(action, exc, attempt)) from exc

            if response.status_code in self._retryable_status_codes and attempt < self._max_attempts:
                await asyncio.sleep(self._retry_delay_seconds(attempt))
                continue

            self._raise_for_status(response, action)
            return response

        if last_request_error is not None:  # pragma: no cover
            raise DoubaoClientError(
                _format_request_error(action, last_request_error, self._max_attempts)
            ) from last_request_error
        raise DoubaoClientError(f"Failed during {action}: request did not complete.")  # pragma: no cover

    async def _poll_video_task(
        self,
        task_id: str,
        *,
        on_poll_progress: VideoPollProgressCallback | None = None,
    ) -> str:
        poll_interval = max(1, int(getattr(self.config, "video_poll_interval_seconds", 2) or 2))
        poll_timeout = max(0, int(getattr(self.config, "video_poll_timeout_seconds", 0) or 0))
        max_rounds = None if poll_timeout == 0 else max(1, math.ceil(poll_timeout / poll_interval))
        heartbeat_round_interval = max(1, math.ceil(30 / poll_interval))
        last_status: str | None = None
        last_reported_status: str | None = None
        round_index = 0
        while True:
            round_index += 1
            response = await self._get_json_with_retry(
                url=f"{self.config.base_url}/contents/generations/tasks/{task_id}",
                headers=self._ark_headers(),
                action="video generation polling",
            )
            payload = response.json()
            top_level_error = payload.get("error")
            if isinstance(top_level_error, dict):
                raise DoubaoClientError(_format_video_error(top_level_error))

            status = _extract_video_status(payload)
            if status:
                last_status = status

            url = _extract_video_url(payload)
            if url:
                return url

            if on_poll_progress is not None:
                status_for_log = status or last_status
                should_report = (
                    round_index == 1
                    or status_for_log != last_reported_status
                    or (round_index % heartbeat_round_interval == 0)
                )
                if should_report:
                    try:
                        maybe_awaitable = on_poll_progress(task_id, round_index, status_for_log)
                        if maybe_awaitable is not None:
                            await maybe_awaitable
                    except Exception:
                        pass
                    last_reported_status = status_for_log

            if status in {"failed", "error", "cancelled", "canceled"}:
                raise DoubaoClientError(
                    f"Video generation task failed (task_id={task_id}, status={status}): {payload}"
                )
            if max_rounds is not None and round_index >= max_rounds:
                break
            await asyncio.sleep(float(poll_interval))

        if max_rounds is None:  # pragma: no cover
            raise DoubaoClientError(
                f"Video generation task stopped unexpectedly (task_id={task_id}, last_status={last_status or 'unknown'})."
            )
        raise DoubaoClientError(
            "Video generation task timed out after polling "
            f"(task_id={task_id}, timeout_seconds={poll_timeout}, last_status={last_status or 'unknown'})."
        )

    @staticmethod
    def _retry_delay_seconds(attempt: int) -> float:
        return min(0.5 * (2 ** (attempt - 1)), 2.0)

    @staticmethod
    def _extract_message_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise DoubaoClientError("Chat completion returned no choices.")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            return "".join(text_parts)

        raise DoubaoClientError("Chat completion returned an unsupported content structure.")

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DoubaoClientError(
                f"Failed during {action}: {exc.response.status_code} {exc.response.text}"
            ) from exc


def _audio_data_url(audio_payload: str) -> str:
    try:
        base64.b64decode(audio_payload, validate=True)
        encoded = audio_payload
    except Exception:
        encoded = base64.b64encode(audio_payload.encode("utf-8")).decode("utf-8")
    return f"data:audio/mpeg;base64,{encoded}"


def _audio_bytes_data_url(audio_payload: bytes) -> str:
    encoded = base64.b64encode(audio_payload).decode("utf-8")
    return f"data:audio/mpeg;base64,{encoded}"


def _is_seed_tts_v2_endpoint(endpoint: str) -> bool:
    normalized = (endpoint or "").strip().lower()
    return "/api/v3/tts/unidirectional" in normalized


def _is_tts_sse_endpoint(endpoint: str) -> bool:
    normalized = (endpoint or "").strip().lower()
    return normalized.endswith("/sse")


def _format_image_error(payload: dict[str, Any]) -> str:
    code = payload.get("code")
    message = payload.get("message")
    if code and message:
        return f"{code}: {message}"
    if message:
        return str(message)
    return "Image generation failed with an unknown error."


def _format_video_error(payload: dict[str, Any]) -> str:
    code = payload.get("code")
    message = payload.get("message")
    if code and message:
        return f"{code}: {message}"
    if message:
        return str(message)
    return "Video generation failed with an unknown error."


def _extract_video_url(payload: dict[str, Any]) -> str | None:
    candidate = _find_first_string_value(payload, {"video_url", "videoUrl", "play_url", "playUrl", "url"})
    if not candidate:
        return None
    if candidate.startswith("http://") or candidate.startswith("https://") or candidate.startswith("data:video/"):
        return candidate
    return None


def _extract_video_task_id(payload: dict[str, Any]) -> str | None:
    return _find_first_string_value(payload, {"task_id", "taskId", "id"})


def _extract_video_status(payload: dict[str, Any]) -> str | None:
    value = _find_first_string_value(payload, {"status", "state", "task_status", "taskStatus", "phase"})
    return value.lower() if value else None


def _find_first_string_value(node: Any, keys: set[str]) -> str | None:
    if isinstance(node, dict):
        for key in keys:
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in node.values():
            found = _find_first_string_value(value, keys)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_first_string_value(item, keys)
            if found:
                return found
    return None


def _compose_video_prompt(*, prompt: str, duration_seconds: int, frame_count: int | None = None) -> str:
    base = (prompt or "").strip()
    duration = int(duration_seconds)
    auto_duration = duration == -1
    if not auto_duration:
        duration = max(2, duration)
        beat_1 = max(1, round(duration * 0.3, 1))
        beat_2 = max(beat_1 + 0.5, round(duration * 0.75, 1))

    motion_directive = (
        "Image-to-video hard motion constraints (must follow):\n"
        "1) The input frame is only for identity/style reference; do NOT lock the whole video to the first-frame pose.\n"
        "2) Show clear, visible body movement; micro-motion only (blink, breathing, tiny hair shake) is forbidden.\n"
        "3) Enforce a full motion arc: wind-up -> peak action -> settle.\n"
        "4) Enforce an expression arc: initial emotion -> transition -> final emotion.\n"
        "5) Include at least TWO body actions from: head turn, arm/hand action, torso shift, step, turn-around.\n"
        "6) Include at least ONE secondary motion: cloth, hair, smoke, rain, dust, or light/shadow response.\n"
        "7) Use at least TWO camera moves combined: push-in, pull-out, pan, tilt, dolly, arc. No fixed camera.\n"
        "8) No static hold longer than 0.5 seconds.\n"
        "9) End pose must be visually different from the first frame while keeping the same character identity.\n"
        "10) If source prompt lacks action, auto-add a minimal fallback movement sequence that stays semantically consistent with the shot story; never change story intent.\n\n"
    )
    if auto_duration:
        motion_directive += (
            "Time-coded motion plan:\n"
            "- 0%-30%: clear action initiation + first expression change.\n"
            "- 30%-75%: peak body motion + strongest camera motion + secondary motion response.\n"
            "- 75%-100%: decisive settle + clear final pose + final emotion landing.\n"
        )
    else:
        motion_directive += (
            "Time-coded motion plan:\n"
            f"- 0s-{beat_1}s: clear action initiation + first expression change.\n"
            f"- {beat_1}s-{beat_2}s: peak body motion + strongest camera motion + secondary motion response.\n"
            f"- {beat_2}s-{duration}s: decisive settle + clear final pose + final emotion landing.\n"
        )
    if frame_count is not None:
        suffix = f"--resolution 1080p --frames {int(frame_count)} --camerafixed false --watermark true"
    else:
        suffix = f"--resolution 1080p --duration {duration} --camerafixed false --watermark true"
    if base:
        return f"{base}\n\n{motion_directive}\n{suffix}"
    return f"{motion_directive}\n{suffix}"


def _build_video_content(
    *,
    prompt: str,
    image_url: str,
    audio_url: str | None,
    duration_seconds: int,
    frame_count: int | None = None,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": _compose_video_prompt(
                prompt=prompt,
                duration_seconds=duration_seconds,
                frame_count=frame_count,
            ),
        },
        {
            "type": "image_url",
            "image_url": {
                "url": image_url,
            },
        },
    ]
    if audio_url:
        content.append(
            {
                "type": "audio_url",
                "audio_url": {
                    "url": audio_url,
                },
            }
        )
    return content


def _is_video_content_mixing_error(message: str) -> bool:
    text = (message or "").lower()
    return (
        "invalidparameter" in text
        and "content" in text
        and "cannot be mixed with reference media content" in text
    )


def _format_request_error(action: str, exc: httpx.RequestError, attempt: int) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    if attempt > 1:
        return f"Failed during {action}: request error after {attempt} attempts: {detail}"
    return f"Failed during {action}: {detail}"


