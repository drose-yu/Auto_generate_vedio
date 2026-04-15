import asyncio
import base64
import binascii
from collections.abc import Awaitable, Iterable
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Protocol, TypedDict
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.models.schemas import (
    RoleDescription,
    RoleImageResult,
    ShotResult,
    ShotRoleMap,
    TtsConfig,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowTextModels,
)
from app.services.doubao_client import DoubaoClient, DoubaoClientError
from app.services.helpers import (
    clean_narration_text,
    is_sensitive_image_error,
    is_tts_permission_error,
    soften_image_prompt,
)
from app.services.prompts import (
    CAMERA_SYSTEM_PROMPT,
    IMAGE_NEGATIVE_CLAUSE,
    IMAGE_STYLE_LOCK_CLAUSE,
    NARRATION_ROLE_FILTER_SYSTEM_PROMPT,
    ROLE_SYSTEM_PROMPT,
    SHOT_CONTINUITY_PLAN_SYSTEM_PROMPT,
    SHOT_FIRST_FRAME_PROMPT_SYSTEM_PROMPT,
    SHOT_ROLE_SYSTEM_PROMPT,
    STYLE_BIBLE_SYSTEM_PROMPT,
    STORY_SYSTEM_PROMPT,
)
from app.services.request_config_resolver import RequestConfigResolverError, resolve_request_config


class WorkflowServiceError(RuntimeError):
    pass


class WorkflowReporter(Protocol):
    async def stage(self, stage: str, message: str, progress_percent: int) -> None: ...

    async def log(
        self,
        stage: str,
        message: str,
        *,
        progress_percent: int | None = None,
        level: str = "info",
    ) -> None: ...


class ShotContinuityHint(TypedDict):
    start_state: str
    end_state: str
    transition_to_next: str


class WorkflowService:
    async def run(
        self,
        request: WorkflowRunRequest,
        reporter: WorkflowReporter | None = None,
    ) -> WorkflowRunResponse:
        resolved_request = resolve_request_config(request)
        client = DoubaoClient(resolved_request.connection)
        text_models = resolved_request.text_models
        warnings: list[str] = []
        target_shot_count = resolved_request.connection.story_shot_count

        try:
            if resolved_request.tts.enabled:
                await _log(
                    reporter,
                    "audio",
                    _summarize_tts_runtime(resolved_request.tts),
                    progress_percent=1,
                )

            await _stage(reporter, "story", "Generating title and key highlights.", 5)
            story_result = await client.chat_json(
                system_prompt=STORY_SYSTEM_PROMPT,
                user_prompt=(
                    f"Target shot/story-beat count: {target_shot_count}\n"
                    "Generate title and exactly that many key story highlights from the following content:\n"
                    f"{resolved_request.story_text}"
                ),
                temperature=0.9,
                model=text_models.resolve_for_stage("story", resolved_request.connection.chat_model),
            )
            title = story_result["title"]
            key_highlights = story_result["key_highlights"]
            if not isinstance(key_highlights, list) or len(key_highlights) != target_shot_count:
                raise WorkflowServiceError(
                    "Story generation failed: model did not return expected key_highlights length. "
                    f"expected={target_shot_count}, actual={len(key_highlights) if isinstance(key_highlights, list) else 'N/A'}."
                )
            await _log(
                reporter,
                "story",
                f"Generated title '{title}' and {target_shot_count} highlights.",
                progress_percent=20,
            )

            await _stage(reporter, "roles", "Extracting roles and visual descriptions.", 28)
            role_result = await client.chat_json(
                system_prompt=ROLE_SYSTEM_PROMPT,
                user_prompt=(
                    "Generate core roles and role image descriptions from:\n"
                    f"Title: {title}\n"
                    f"Highlights: {key_highlights}"
                ),
                temperature=0.8,
                model=text_models.resolve_for_stage("roles", resolved_request.connection.chat_model),
            )
            roles = role_result["roles"]
            raw_descriptions = role_result["description_list"]
            description_list = [RoleDescription.model_validate(item) for item in raw_descriptions]

            if len(roles) != len(description_list):
                raise WorkflowServiceError("Role list length and description list length do not match.")
            await _log(reporter, "roles", f"Detected {len(roles)} core roles.", progress_percent=40)

            style_lock_clause = IMAGE_STYLE_LOCK_CLAUSE
            try:
                style_bible_payload = await client.chat_json(
                    system_prompt=STYLE_BIBLE_SYSTEM_PROMPT,
                    user_prompt=(
                        f"标题：{title}\n"
                        f"剧情节点：{key_highlights}\n"
                        f"角色设定：{[item.model_dump() for item in description_list]}\n"
                        "请生成可复用的全片统一风格基线。"
                    ),
                    temperature=0.2,
                    model=text_models.resolve_for_stage("roles", resolved_request.connection.chat_model),
                )
                style_lock_clause = _compose_style_lock_clause(
                    base_clause=IMAGE_STYLE_LOCK_CLAUSE,
                    payload=style_bible_payload,
                )
                await _log(reporter, "roles", "Unified style baseline locked for this run.")
            except (DoubaoClientError, KeyError, TypeError, ValueError) as exc:
                warning = (
                    "Style baseline generation failed; fallback to default style lock. "
                    f"Error: {exc}"
                )
                warnings.append(warning)
                await _log(reporter, "roles", warning, level="warning")

            await _stage(reporter, "shot_roles", "Mapping roles to each story beat.", 46)
            shot_role_payload = await client.chat_json(
                system_prompt=SHOT_ROLE_SYSTEM_PROMPT,
                user_prompt=(
                    f"Below is the ordered story beat list (exactly {target_shot_count} items):\n"
                    f"{key_highlights}\n\n"
                    "Allowed role names must come from this list only:\n"
                    f"{roles}"
                ),
                temperature=0.4,
                model=text_models.resolve_for_stage("shot_roles", resolved_request.connection.chat_model),
            )
            shot_role_map = [ShotRoleMap.model_validate(item) for item in shot_role_payload]
            if len(shot_role_map) != len(key_highlights):
                raise WorkflowServiceError(
                    "Shot-role map length does not match key highlight length."
                )
            await _log(reporter, "shot_roles", "Completed role mapping for all shots.", progress_percent=54)
            continuity_plan = await self._plan_shot_continuity(
                client=client,
                key_highlights=key_highlights,
                shot_role_map=shot_role_map,
                warnings=warnings,
                reporter=reporter,
                text_models=text_models,
                default_text_model=resolved_request.connection.chat_model,
            )

            await _stage(reporter, "images", "Generating role prototype images.", 58)
            role_images = await self._generate_role_images(
                client=client,
                descriptions=description_list,
                max_images=resolved_request.max_images,
                warnings=warnings,
                reporter=reporter,
                style_lock_clause=style_lock_clause,
            )

            await _stage(reporter, "shots", "Generating shot prompts and narration assets.", 70)
            shots = await self._build_shots(
                client=client,
                key_highlights=key_highlights,
                descriptions=description_list,
                shot_role_map=shot_role_map,
                role_images=role_images,
                tts_enabled=resolved_request.tts.ready,
                tts_config=resolved_request.tts,
                video_max_shots=resolved_request.connection.video_max_shots,
                warnings=warnings,
                reporter=reporter,
                text_models=text_models,
                default_text_model=resolved_request.connection.chat_model,
                style_lock_clause=style_lock_clause,
                continuity_plan=continuity_plan,
            )

            response = WorkflowRunResponse(
                title=title,
                key_highlights=key_highlights,
                roles=roles,
                description_list=description_list,
                role_images=role_images,
                shot_role_map=shot_role_map,
                shots=shots,
                warnings=warnings,
            )
            await _stage(reporter, "complete", "Workflow completed.", 100)
            return response
        except (KeyError, TypeError, ValueError, DoubaoClientError, RequestConfigResolverError) as exc:
            raise WorkflowServiceError(str(exc)) from exc
        finally:
            await client.aclose()

    async def _generate_role_images(
        self,
        *,
        client: DoubaoClient,
        descriptions: list[RoleDescription],
        max_images: int,
        warnings: list[str],
        reporter: WorkflowReporter | None,
        style_lock_clause: str,
    ) -> list[RoleImageResult]:
        if not client.config.image_model:
            warnings.append("image_model is empty; role image generation skipped.")
            await _log(
                reporter,
                "images",
                "image_model is empty, skipping role image generation.",
                progress_percent=66,
            )
            return [
                RoleImageResult(
                    role_name=description.name,
                    prompt=description.full_prompt,
                    warning="Image generation skipped because image_model is empty.",
                )
                for description in descriptions
            ]

        async def task(index: int, description: RoleDescription) -> RoleImageResult:
            if index >= max_images:
                warning = (
                    f"Only generating first {max_images} role images in this run; "
                    f"skipped role '{description.name}'."
                )
                return RoleImageResult(
                    role_name=description.name,
                    prompt=description.full_prompt,
                    warning=warning,
                )
            try:
                locked_prompt = _lock_image_prompt(description.full_prompt, style_lock_clause)
                image_url = await client.generate_image(prompt=locked_prompt)
                await _log(reporter, "images", f"Role image generated: {description.name}")
                return RoleImageResult(
                    role_name=description.name,
                    prompt=locked_prompt,
                    image_url=image_url,
                )
            except DoubaoClientError as exc:
                if is_sensitive_image_error(str(exc)):
                    safe_prompt = soften_image_prompt(description.full_prompt, description.name)
                    locked_safe_prompt = _lock_image_prompt(safe_prompt, style_lock_clause)
                    await _log(
                        reporter,
                        "images",
                        f"Sensitive image blocked, retrying with softened prompt: {description.name}",
                        level="warning",
                    )
                    try:
                        image_url = await client.generate_image(prompt=locked_safe_prompt)
                        warning = (
                            f"Role image retried with softened prompt after policy block: {description.name}"
                        )
                        warnings.append(warning)
                        await _log(reporter, "images", warning)
                        return RoleImageResult(
                            role_name=description.name,
                            prompt=locked_safe_prompt,
                            image_url=image_url,
                            warning=warning,
                        )
                    except DoubaoClientError as retry_exc:
                        warnings.append(
                            f"Role image failed after softened retry: {description.name}; error: {retry_exc}"
                        )
                        await _log(
                            reporter,
                            "images",
                            f"Role image softened retry failed: {description.name}; error: {retry_exc}",
                            level="warning",
                        )
                        return RoleImageResult(
                            role_name=description.name,
                            prompt=locked_safe_prompt,
                            warning=str(retry_exc),
                        )

                warnings.append(f"Role image generation failed: {description.name}; error: {exc}")
                await _log(
                    reporter,
                    "images",
                    f"Role image generation failed: {description.name}; error: {exc}",
                    level="warning",
                )
                return RoleImageResult(
                    role_name=description.name,
                    prompt=_lock_image_prompt(description.full_prompt, style_lock_clause),
                    warning=str(exc),
                )

        tasks = [task(index, description) for index, description in enumerate(descriptions)]
        results = await gather_limited(tasks, min(settings.max_parallel_tasks, max_images))
        await _log(reporter, "images", "Role image generation stage completed.", progress_percent=68)
        return results

    async def _plan_shot_continuity(
        self,
        *,
        client: DoubaoClient,
        key_highlights: list[str],
        shot_role_map: list[ShotRoleMap],
        warnings: list[str],
        reporter: WorkflowReporter | None,
        text_models: WorkflowTextModels,
        default_text_model: str | None,
    ) -> list[ShotContinuityHint]:
        fallback_plan = _build_default_shot_continuity_plan(len(key_highlights))
        try:
            continuity_payload = await client.chat_json(
                system_prompt=SHOT_CONTINUITY_PLAN_SYSTEM_PROMPT,
                user_prompt=(
                    "Ordered story beats:\n"
                    f"{key_highlights}\n\n"
                    "Role mapping for each shot:\n"
                    f"{[item.model_dump() for item in shot_role_map]}"
                ),
                temperature=0.2,
                model=text_models.resolve_for_stage("camera", default_text_model),
            )
            continuity_plan = _normalize_shot_continuity_plan(
                payload=continuity_payload,
                expected_len=len(key_highlights),
            )
            await _log(reporter, "shots", "Shot continuity plan generated.")
            return continuity_plan
        except (DoubaoClientError, KeyError, TypeError, ValueError) as exc:
            warning = (
                "Shot continuity planning failed; fallback to basic per-shot generation. "
                f"Error: {exc}"
            )
            warnings.append(warning)
            await _log(reporter, "shots", warning, level="warning")
            return fallback_plan

    async def _build_shots(
        self,
        *,
        client: DoubaoClient,
        key_highlights: list[str],
        descriptions: list[RoleDescription],
        shot_role_map: list[ShotRoleMap],
        role_images: list[RoleImageResult],
        tts_enabled: bool,
        tts_config: TtsConfig,
        video_max_shots: int = 8,
        warnings: list[str],
        reporter: WorkflowReporter | None,
        text_models: WorkflowTextModels,
        default_text_model: str | None,
        style_lock_clause: str,
        continuity_plan: list[ShotContinuityHint] | None = None,
    ) -> list[ShotResult]:
        role_description_map = {item.name: item for item in descriptions}
        role_image_map = {item.role_name: item.image_url for item in role_images if item.image_url}
        first_appearance_by_role = _build_first_appearance_index(shot_role_map)
        effective_video_max_shots = max(0, int(video_max_shots))
        continuity_hints = continuity_plan or _build_default_shot_continuity_plan(len(key_highlights))
        if len(continuity_hints) != len(key_highlights):
            warning = (
                "Shot continuity plan length mismatch; fallback to basic per-shot continuity."
            )
            warnings.append(warning)
            await _log(reporter, "shots", warning, level="warning")
            continuity_hints = _build_default_shot_continuity_plan(len(key_highlights))
        tts_guard = {"disabled": False}
        tts_lock = asyncio.Lock()
        results: list[ShotResult] = []
        previous_end_state = ""

        for index, highlight in enumerate(key_highlights):
            mapping = shot_role_map[index]
            continuity_hint = continuity_hints[index]
            continuity_start_state = (continuity_hint.get("start_state") or "").strip()
            continuity_end_state = (continuity_hint.get("end_state") or "").strip()
            transition_to_next = (continuity_hint.get("transition_to_next") or "").strip()
            roles_in_shot = mapping.roles_in_shot
            role_prompt_context = [
                role_description_map[role_name].model_dump()
                for role_name in roles_in_shot
                if role_name in role_description_map
            ]
            role_ref_urls = [
                role_image_map[role_name]
                for role_name in roles_in_shot
                if role_name in role_image_map
            ]
            camera_payload = await client.chat_json(
                system_prompt=CAMERA_SYSTEM_PROMPT,
                user_prompt=(
                    f"Story beat: {highlight}\n"
                    f"Roles in shot: {roles_in_shot}\n"
                    f"Role descriptions: {role_prompt_context}\n"
                    f"Previous shot end state: {previous_end_state or 'N/A'}\n"
                    f"Continuity start state: {continuity_start_state or 'N/A'}\n"
                    f"Target end state for this shot: {continuity_end_state or 'N/A'}\n"
                    f"Transition goal to next shot: {transition_to_next or 'N/A'}\n"
                    "Generate one camera prompt for this shot."
                ),
                temperature=0.8,
                model=text_models.resolve_for_stage("camera", default_text_model),
            )
            camera_prompt = camera_payload["camera_prompt"]
            await _log(reporter, "shots", f"Shot {index + 1} camera prompt generated.")

            first_frame_prompt: str | None = None
            first_frame_url: str | None = None
            shot_video_url: str | None = None
            try:
                first_frame_payload = await client.chat_json(
                    system_prompt=SHOT_FIRST_FRAME_PROMPT_SYSTEM_PROMPT,
                    user_prompt=(
                        f"Story beat: {highlight}\n"
                        f"Roles in shot: {roles_in_shot}\n"
                        f"Role visual context: {role_prompt_context}\n"
                        f"Camera prompt: {camera_prompt}\n"
                        f"Reference role image URLs (shot-only): {role_ref_urls}\n"
                        f"Previous shot end state: {previous_end_state or 'N/A'}\n"
                        f"Continuity start state: {continuity_start_state or 'N/A'}\n"
                        f"Target end state for this shot: {continuity_end_state or 'N/A'}\n"
                        f"Transition goal to next shot: {transition_to_next or 'N/A'}\n"
                        f"Global style lock clause: {style_lock_clause}\n"
                    ),
                    temperature=0.6,
                    model=text_models.resolve_for_stage("shot_image_prompt", default_text_model),
                )
                raw_prompt = first_frame_payload.get("image_prompt")
                if not isinstance(raw_prompt, str) or not raw_prompt.strip():
                    raise ValueError("Missing image_prompt in shot first-frame payload.")
                first_frame_prompt = raw_prompt.strip()
                await _log(reporter, "shots", f"Shot {index + 1} first-frame prompt generated.")
            except (DoubaoClientError, ValueError, TypeError, KeyError) as exc:
                first_frame_prompt = camera_prompt
                warning = (
                    f"Shot {index + 1} first-frame prompt generation failed. "
                    f"Falling back to camera prompt. Error: {exc}"
                )
                warnings.append(warning)
                await _log(reporter, "shots", warning, level="warning")

            if first_frame_prompt and client.config.image_model:
                try:
                    first_frame_prompt = _lock_image_prompt(first_frame_prompt, style_lock_clause)
                    first_frame_url = await client.generate_image(prompt=first_frame_prompt)
                    await _log(reporter, "images", f"Shot {index + 1} first-frame image generated.")
                except DoubaoClientError as exc:
                    warning = f"Shot {index + 1} first-frame image generation failed: {exc}"
                    warnings.append(warning)
                    await _log(reporter, "images", warning, level="warning")

            narration_text = clean_narration_text(highlight)
            intro_roles_in_shot = [
                role_name
                for role_name in roles_in_shot
                if first_appearance_by_role.get(role_name) == (index + 1)
            ]
            removable_role_names = [
                role_name
                for role_name in roles_in_shot
                if role_name not in intro_roles_in_shot
            ]
            if (
                narration_text
                and tts_config.remove_role_names
                and removable_role_names
                and _contains_any_role_name(narration_text, removable_role_names)
            ):
                try:
                    narration_payload = await client.chat_json(
                        system_prompt=NARRATION_ROLE_FILTER_SYSTEM_PROMPT,
                        user_prompt=(
                            f"Original narration text: {narration_text}\n"
                            f"Role names that must be removed: {removable_role_names}\n"
                            f"Role names that are allowed to keep (first appearance in this shot): {intro_roles_in_shot}\n"
                            "Rewrite the sentence in Chinese for voice-over."
                        ),
                        temperature=0.2,
                        model=text_models.resolve_for_stage("story", default_text_model),
                    )
                    rewritten_narration = _extract_rewritten_narration_text(narration_payload)
                    stripped_narration = _remove_role_names_by_replace(
                        rewritten_narration,
                        removable_role_names,
                    )
                    if stripped_narration:
                        narration_text = stripped_narration
                        await _log(
                            reporter,
                            "audio",
                            f"Shot {index + 1} narration role names filtered (keep first appearance names).",
                        )
                except (DoubaoClientError, KeyError, TypeError, ValueError) as exc:
                    warning = (
                        f"Shot {index + 1} narration role-name filtering failed; "
                        f"using original narration. Error: {exc}"
                    )
                    warnings.append(warning)
                    await _log(reporter, "audio", warning, level="warning")

            narration_audio_url = None
            if tts_enabled and narration_text:
                async with tts_lock:
                    if not tts_guard["disabled"]:
                        try:
                            narration_audio_url = await client.synthesize_speech(
                                text=narration_text,
                                tts_config=tts_config,
                            )
                            await _log(reporter, "audio", f"Shot {index + 1} narration audio generated.")
                        except DoubaoClientError as exc:
                            if is_tts_permission_error(str(exc)):
                                tts_guard["disabled"] = True
                                warning = (
                                    "TTS resource is not granted for the current App ID / Access Token; "
                                    "remaining narration audio has been skipped for this run. "
                                    "Check backend/.env APP_TTS_APP_ID, APP_TTS_ACCESS_TOKEN, "
                                    f"cluster={tts_config.cluster}, and voice_type={tts_config.voice_type}. "
                                    f"Original error: {exc}"
                                )
                                warnings.append(warning)
                                await _log(reporter, "audio", warning, level="warning")
                            else:
                                warnings.append(f"Shot {index + 1} narration generation failed: {exc}")
                                await _log(
                                    reporter,
                                    "audio",
                                    f"Shot {index + 1} narration generation failed.",
                                    level="warning",
                                )
            elif not tts_enabled and index == 0:
                await _log(
                    reporter,
                    "audio",
                    "Narration audio disabled; skipping TTS for all shots.",
                    progress_percent=86,
                )

            shot_video_prompt = _compose_shot_video_prompt(
                highlight=highlight,
                scene_note=mapping.scene_note,
                narration_text=narration_text,
                roles_in_shot=roles_in_shot,
                camera_prompt=camera_prompt,
                previous_shot_end_state=previous_end_state,
                continuity_start_state=continuity_start_state,
                continuity_end_state=continuity_end_state,
                transition_to_next=transition_to_next,
            )

            video_model = getattr(client.config, "video_model", None)
            if first_frame_url and video_model and index < effective_video_max_shots:
                try:
                    shot_video_url = await client.generate_video_from_image(
                        prompt=shot_video_prompt,
                        image_url=first_frame_url,
                        audio_url=narration_audio_url,
                        duration_seconds=getattr(client.config, "video_duration_seconds", 5),
                    )
                    if narration_audio_url:
                        muxed_video_url = await _mux_video_with_narration(
                            shot_video_url,
                            narration_audio_url,
                        )
                        if muxed_video_url:
                            shot_video_url = muxed_video_url
                            await _log(
                                reporter,
                                "videos",
                                f"Shot {index + 1} narration audio muxed into video.",
                            )
                        else:
                            warning = (
                                f"Shot {index + 1} video audio mux skipped: ffmpeg not found in runtime."
                            )
                            warnings.append(warning)
                            await _log(reporter, "videos", warning, level="warning")
                    await _log(reporter, "videos", f"Shot {index + 1} video generated.")
                except DoubaoClientError as exc:
                    warning = f"Shot {index + 1} video generation failed: {exc}"
                    warnings.append(warning)
                    await _log(reporter, "videos", warning, level="warning")
                except RuntimeError as exc:
                    detail = str(exc).strip() or repr(exc)
                    warning = f"Shot {index + 1} video audio mux failed: {detail}"
                    warnings.append(warning)
                    await _log(reporter, "videos", warning, level="warning")

            ref_urls = []
            for image_url in role_ref_urls:
                if image_url and image_url not in ref_urls:
                    ref_urls.append(image_url)

            results.append(
                ShotResult(
                    index=index + 1,
                    highlight=highlight,
                    narration_text=narration_text,
                    narration_audio_url=narration_audio_url,
                    roles_in_shot=roles_in_shot,
                    scene_note=mapping.scene_note,
                    continuity_start_state=continuity_start_state or None,
                    continuity_end_state=continuity_end_state or None,
                    continuity_transition_to_next=transition_to_next or None,
                    ref_urls=ref_urls,
                    camera_prompt=camera_prompt,
                    shot_video_prompt=shot_video_prompt,
                    first_frame_prompt=first_frame_prompt,
                    first_frame_url=first_frame_url,
                    shot_video_url=shot_video_url,
                )
            )
            if continuity_end_state:
                previous_end_state = continuity_end_state

        await _log(reporter, "shots", "Shot generation stage completed.", progress_percent=96)
        return results


async def gather_limited(tasks: Iterable[Awaitable], limit: int) -> list:
    semaphore = asyncio.Semaphore(max(1, limit))

    async def runner(task: Awaitable):
        async with semaphore:
            return await task

    return await asyncio.gather(*(runner(task) for task in tasks))


async def _stage(
    reporter: WorkflowReporter | None,
    stage: str,
    message: str,
    progress_percent: int,
) -> None:
    if reporter is not None:
        await reporter.stage(stage, message, progress_percent)


async def _log(
    reporter: WorkflowReporter | None,
    stage: str,
    message: str,
    *,
    progress_percent: int | None = None,
    level: str = "info",
) -> None:
    if reporter is not None:
        await reporter.log(
            stage,
            message,
            progress_percent=progress_percent,
            level=level,
        )


def _summarize_tts_runtime(tts_config: TtsConfig) -> str:
    return (
        "TTS runtime config: "
        f"endpoint={tts_config.endpoint}, "
        f"cluster={tts_config.cluster}, "
        f"voice_type={tts_config.voice_type}, "
        f"app_id={_mask_identifier(tts_config.app_id)}, "
        f"access_token_present={'yes' if bool(tts_config.access_token) else 'no'}."
    )


def _mask_identifier(value: str | None) -> str:
    if not value:
        return "missing"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


def _lock_image_prompt(prompt: str, style_lock_clause: str) -> str:
    base = (prompt or "").strip()
    style = (style_lock_clause or "").strip()
    segments = [segment for segment in [style, base, IMAGE_NEGATIVE_CLAUSE] if segment]
    return "\n".join(segments)


def _compose_style_lock_clause(base_clause: str, payload: object) -> str:
    base = (base_clause or "").strip()
    if not isinstance(payload, dict):
        return base

    ordered_keys = [
        "visual_style",
        "camera_language",
        "lighting_palette",
        "material_texture",
        "costume_architecture_rule",
        "consistency_rule",
        "forbidden_elements",
    ]
    details: list[str] = []
    for key in ordered_keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                details.append(f"{key}: {normalized}")

    if not details:
        return base
    if base:
        return f"{base}\n【任务统一风格基线】" + "；".join(details)
    return "【任务统一风格基线】" + "；".join(details)


def _compose_shot_video_prompt(
    *,
    highlight: str,
    scene_note: str,
    narration_text: str,
    roles_in_shot: list[str],
    camera_prompt: str,
    previous_shot_end_state: str = "",
    continuity_start_state: str = "",
    continuity_end_state: str = "",
    transition_to_next: str = "",
) -> str:
    parts = [
        "Shot story constraints (highest priority):",
        f"- Story beat: {highlight.strip()}",
        f"- Scene note: {(scene_note or '').strip()}",
        f"- Roles in shot: {roles_in_shot}",
        f"- Narration line: {(narration_text or '').strip()}",
    ]
    if any([previous_shot_end_state, continuity_start_state, continuity_end_state, transition_to_next]):
        parts.extend(
            [
                "",
                "Continuity constraints:",
                f"- Previous shot end state: {(previous_shot_end_state or '').strip() or 'N/A'}",
                f"- This shot start state: {(continuity_start_state or '').strip() or 'N/A'}",
                f"- This shot target end state: {(continuity_end_state or '').strip() or 'N/A'}",
                f"- Transition goal to next shot: {(transition_to_next or '').strip() or 'N/A'}",
            ]
        )
    parts.extend(
        [
            "",
            "Camera and visual guidance:",
            camera_prompt.strip(),
            "",
            "Strict alignment rules:",
            "- Body actions and expressions must directly match the story beat and narration for this shot.",
            "- Do not invent unrelated actions, props, events, or emotion turns.",
            "- If there is conflict, preserve story beat semantics first, then camera style.",
        ]
    )
    return "\n".join(parts).strip()


def _build_default_shot_continuity_plan(total_shots: int) -> list[ShotContinuityHint]:
    if total_shots <= 0:
        return []
    return [
        {
            "start_state": "",
            "end_state": "",
            "transition_to_next": "",
        }
        for _ in range(total_shots)
    ]


def _normalize_shot_continuity_plan(payload: object, expected_len: int) -> list[ShotContinuityHint]:
    entries: object = payload
    if isinstance(payload, dict):
        entries = payload.get("shots")
    if not isinstance(entries, list):
        raise ValueError("Shot continuity payload must be a list or {'shots': [...]} object.")
    if len(entries) != expected_len:
        raise ValueError("Shot continuity plan length does not match story beat length.")

    normalized: list[ShotContinuityHint] = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Each continuity item must be an object.")
        normalized.append(
            {
                "start_state": _normalize_continuity_text(item.get("start_state")),
                "end_state": _normalize_continuity_text(item.get("end_state")),
                "transition_to_next": _normalize_continuity_text(
                    item.get("transition_to_next") or item.get("next_transition")
                ),
            }
        )
    return normalized


def _normalize_continuity_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _extract_rewritten_narration_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Narration rewrite payload is not an object.")
    value = payload.get("narration_text")
    if not isinstance(value, str):
        raise ValueError("Narration rewrite payload is missing narration_text.")
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        raise ValueError("Narration rewrite result is empty.")
    return normalized


def _build_first_appearance_index(shot_role_map: list[ShotRoleMap]) -> dict[str, int]:
    first_appearance: dict[str, int] = {}
    for shot_index, mapping in enumerate(shot_role_map, start=1):
        for role_name in mapping.roles_in_shot:
            normalized = (role_name or "").strip()
            if normalized and normalized not in first_appearance:
                first_appearance[normalized] = shot_index
    return first_appearance


def _contains_any_role_name(text: str, role_names: list[str]) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    for role_name in role_names:
        candidate = (role_name or "").strip()
        if candidate and candidate in normalized:
            return True
    return False


def _remove_role_names_by_replace(text: str, role_names: list[str]) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return ""

    cleaned = normalized
    for role_name in sorted({name.strip() for name in role_names if isinstance(name, str)}, key=len, reverse=True):
        if not role_name:
            continue
        cleaned = re.sub(re.escape(role_name), "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    cleaned = cleaned.strip(" ，,。；;：:、")
    return cleaned


async def _mux_video_with_narration(video_url: str, audio_url: str) -> str | None:
    ffmpeg_bin = _find_ffmpeg_binary()
    if not ffmpeg_bin:
        return None

    video_bytes, video_suffix = await _fetch_asset_bytes(video_url, fallback_suffix=".mp4")
    audio_bytes, audio_suffix = await _fetch_asset_bytes(audio_url, fallback_suffix=".mp3")

    with tempfile.TemporaryDirectory(prefix="shot_mux_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        video_in = tmp_dir / f"video_in{video_suffix}"
        audio_in = tmp_dir / f"audio_in{audio_suffix}"
        video_out = tmp_dir / "video_out.mp4"
        video_in.write_bytes(video_bytes)
        audio_in.write_bytes(audio_bytes)

        first_cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video_in),
            "-i",
            str(audio_in),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(video_out),
        ]
        first_result, first_stderr = await _run_subprocess(first_cmd)
        if first_result != 0:
            second_cmd = [
                ffmpeg_bin,
                "-y",
                "-i",
                str(video_in),
                "-i",
                str(audio_in),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-shortest",
                str(video_out),
            ]
            second_result, second_stderr = await _run_subprocess(second_cmd)
            if second_result != 0:
                third_cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-i",
                    str(video_in),
                    "-i",
                    str(audio_in),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    "-ar",
                    "48000",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    "-shortest",
                    str(video_out),
                ]
                third_result, third_stderr = await _run_subprocess(third_cmd)
                if third_result != 0:
                    stderr_tail = _tail_error_text(
                        third_stderr or second_stderr or first_stderr,
                        max_len=1200,
                    )
                    reason = (
                        f"ffmpeg failed to mux narration audio into video "
                        f"(copy={first_result}, reencode={second_result}, compatibility={third_result})."
                    )
                    if stderr_tail:
                        reason = f"{reason} ffmpeg stderr: {stderr_tail}"
                    raise RuntimeError(reason)

        if not video_out.exists() or video_out.stat().st_size <= 0:
            raise RuntimeError("ffmpeg mux completed but output video file is missing or empty.")

        output_bytes = video_out.read_bytes()
        encoded = base64.b64encode(output_bytes).decode("ascii")
        return f"data:video/mp4;base64,{encoded}"


def _find_ffmpeg_binary() -> str | None:
    for candidate in ("ffmpeg", "ffmpeg.exe"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


async def _run_subprocess(cmd: list[str]) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        stderr_text = ""
        if stderr:
            stderr_text = stderr.decode("utf-8", errors="replace")
        return process.returncode, stderr_text
    except NotImplementedError:
        # Windows selector event loop may not implement async subprocess APIs.
        # Fallback to a thread-backed synchronous subprocess call.
        def _run_sync() -> tuple[int, str]:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
            stderr_text = ""
            if completed.stderr:
                stderr_text = completed.stderr.decode("utf-8", errors="replace")
            return completed.returncode, stderr_text

        return await asyncio.to_thread(_run_sync)


async def _fetch_asset_bytes(asset_url: str, *, fallback_suffix: str) -> tuple[bytes, str]:
    if asset_url.startswith("data:"):
        media_type, payload = _decode_data_url(asset_url)
        return payload, _guess_extension(asset_url=asset_url, media_type=media_type, fallback=fallback_suffix)

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.get(asset_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"failed to download asset: {asset_url}; {exc}") from exc
        media_type = response.headers.get("content-type", "").split(";")[0].strip()
        suffix = _guess_extension(asset_url=asset_url, media_type=media_type, fallback=fallback_suffix)
        return response.content, suffix


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError as exc:
        raise RuntimeError("invalid data URL while muxing video/audio.") from exc

    media_type = header[5:].split(";")[0] or "application/octet-stream"
    is_base64 = header.endswith(";base64") or ";base64;" in header
    try:
        if is_base64:
            return media_type, base64.b64decode(encoded)
        return media_type, encoded.encode("utf-8")
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("failed to decode data URL while muxing video/audio.") from exc


def _guess_extension(*, asset_url: str, media_type: str, fallback: str) -> str:
    guessed = mimetypes.guess_extension(media_type or "")
    if guessed:
        return guessed
    parsed = urlparse(asset_url)
    suffix = Path(parsed.path).suffix
    if suffix:
        return suffix
    return fallback


def _tail_error_text(text: str, *, max_len: int = 1200) -> str:
    normalized = (text or "").strip().replace("\r", " ").replace("\n", " | ")
    if len(normalized) <= max_len:
        return normalized
    return normalized[-max_len:]
