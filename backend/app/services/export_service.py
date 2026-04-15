import base64
import binascii
import io
import json
import mimetypes
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.models.schemas import WorkflowRunResponse, WorkflowSavedRunSummary
from app.services.prompts import SHOT_CONTINUITY_PLAN_SYSTEM_PROMPT


class WorkflowExportError(RuntimeError):
    pass


async def build_assets_zip(result: WorkflowRunResponse) -> bytes:
    output = io.BytesIO()
    notes: list[str] = []
    debug_files = _build_debug_artifacts(result)

    async with httpx.AsyncClient(timeout=60.0) as client:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("result.json", result.model_dump_json(indent=2))
            for path, content in debug_files.items():
                archive.writestr(path, content)

            for asset_url, target_prefix in _iter_asset_targets(result):
                try:
                    media_type, binary = await _fetch_asset_binary(client, asset_url)
                    extension = _extension_from_media_type(media_type, asset_url)
                    archive.writestr(f"{target_prefix}{extension}", binary)
                except WorkflowExportError as exc:
                    notes.append(str(exc))

            if notes:
                archive.writestr("export_notes.txt", "\n".join(notes))

    return output.getvalue()


async def persist_workflow_run(
    job_id: str,
    result: WorkflowRunResponse,
    *,
    created_at: datetime | None = None,
) -> WorkflowSavedRunSummary:
    run_dir = _resolve_run_dir(job_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    debug_files = _build_debug_artifacts(result)

    result_path = run_dir / "result.json"
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    for path, content in debug_files.items():
        target_path = run_dir / Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")

    async with httpx.AsyncClient(timeout=60.0) as client:
        for asset_url, target_prefix in _iter_asset_targets(result):
            try:
                media_type, binary = await _fetch_asset_binary(client, asset_url)
                extension = _extension_from_media_type(media_type, asset_url)
                target_path = run_dir / f"{target_prefix}{extension}"
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(binary)
            except WorkflowExportError as exc:
                notes.append(str(exc))

    if notes:
        notes_path = run_dir / "export_notes.txt"
        notes_path.write_text("\n".join(notes), encoding="utf-8")

    zip_payload = await build_assets_zip(result)
    zip_path = run_dir / "assets.zip"
    zip_path.write_bytes(zip_payload)

    summary = WorkflowSavedRunSummary(
        job_id=job_id,
        title=result.title,
        created_at=created_at,
        saved_at=datetime.now(timezone.utc),
        saved_result_path=str(result_path.resolve()),
        saved_assets_zip_path=str(zip_path.resolve()),
        role_image_count=sum(1 for item in result.role_images if item.image_url),
        shot_first_frame_count=sum(1 for item in result.shots if item.first_frame_url),
        shot_audio_count=sum(1 for item in result.shots if item.narration_audio_url),
    )
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    return summary


def list_saved_runs(*, limit: int = 100) -> list[WorkflowSavedRunSummary]:
    root = Path(settings.workflow_storage_dir).expanduser()
    if not root.exists():
        return []

    items: list[WorkflowSavedRunSummary] = []
    for run_dir in root.iterdir():
        if not run_dir.is_dir():
            continue
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            try:
                summary = WorkflowSavedRunSummary.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
                items.append(summary)
                continue
            except Exception:
                pass
        summary = _build_fallback_summary_from_run_dir(run_dir)
        if summary is not None:
            items.append(summary)

    items.sort(key=lambda item: item.saved_at, reverse=True)
    return items[: max(1, limit)]


def load_saved_result(job_id: str) -> WorkflowRunResponse:
    run_dir = _resolve_run_dir(job_id)
    result_path = run_dir / "result.json"
    if not result_path.exists():
        raise WorkflowExportError(f"Saved result not found for job '{job_id}'.")
    try:
        return WorkflowRunResponse.model_validate_json(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WorkflowExportError(f"Saved result is invalid for job '{job_id}': {exc}") from exc


def get_saved_assets_zip_path(job_id: str) -> Path:
    run_dir = _resolve_run_dir(job_id)
    zip_path = run_dir / "assets.zip"
    if not zip_path.exists():
        raise WorkflowExportError(f"Saved assets zip not found for job '{job_id}'.")
    return zip_path


def _resolve_run_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise WorkflowExportError("Invalid job id.")
    root = Path(settings.workflow_storage_dir).expanduser()
    return root / job_id


def _build_fallback_summary_from_run_dir(run_dir: Path) -> WorkflowSavedRunSummary | None:
    result_path = run_dir / "result.json"
    if not result_path.exists():
        return None
    try:
        result = WorkflowRunResponse.model_validate_json(result_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    zip_path = run_dir / "assets.zip"
    saved_at = datetime.fromtimestamp(run_dir.stat().st_mtime, tz=timezone.utc)
    return WorkflowSavedRunSummary(
        job_id=run_dir.name,
        title=result.title,
        created_at=None,
        saved_at=saved_at,
        saved_result_path=str(result_path.resolve()),
        saved_assets_zip_path=str(zip_path.resolve()),
        role_image_count=sum(1 for item in result.role_images if item.image_url),
        shot_first_frame_count=sum(1 for item in result.shots if item.first_frame_url),
        shot_audio_count=sum(1 for item in result.shots if item.narration_audio_url),
    )


def _iter_asset_targets(result: WorkflowRunResponse) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for index, role_image in enumerate(result.role_images, start=1):
        if role_image.image_url:
            targets.append(
                (
                    role_image.image_url,
                    f"role_images/{index:02d}_{_slugify(role_image.role_name)}",
                )
            )

    for shot in result.shots:
        if shot.first_frame_url:
            targets.append((shot.first_frame_url, f"shot_first_frames/shot_{shot.index:02d}"))
        if shot.shot_video_url:
            targets.append((shot.shot_video_url, f"shot_videos/shot_{shot.index:02d}"))
        if shot.narration_audio_url:
            targets.append((shot.narration_audio_url, f"shot_audio/shot_{shot.index:02d}"))

    return targets


def _build_debug_artifacts(result: WorkflowRunResponse) -> dict[str, str]:
    continuity_plan: list[dict[str, object]] = []
    shot_video_prompts: list[dict[str, object]] = []

    for shot in sorted(result.shots, key=lambda item: item.index):
        continuity_plan.append(
            {
                "index": shot.index,
                "highlight": shot.highlight,
                "continuity_start_state": shot.continuity_start_state,
                "continuity_end_state": shot.continuity_end_state,
                "continuity_transition_to_next": shot.continuity_transition_to_next,
            }
        )
        shot_video_prompts.append(
            {
                "index": shot.index,
                "highlight": shot.highlight,
                "shot_video_prompt": shot.shot_video_prompt,
            }
        )

    return {
        "debug/shot_continuity_system_prompt.txt": SHOT_CONTINUITY_PLAN_SYSTEM_PROMPT.strip() + "\n",
        "debug/continuity_plan.json": json.dumps(continuity_plan, ensure_ascii=False, indent=2),
        "debug/shot_video_prompts.json": json.dumps(shot_video_prompts, ensure_ascii=False, indent=2),
    }


async def _fetch_asset_binary(client: httpx.AsyncClient, asset_url: str) -> tuple[str, bytes]:
    if asset_url.startswith("data:"):
        return _decode_data_url(asset_url)

    try:
        response = await client.get(asset_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WorkflowExportError(f"Failed to download asset: {asset_url}; {exc}") from exc

    media_type = response.headers.get("content-type", "").split(";")[0].strip()
    return media_type, response.content


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError as exc:
        raise WorkflowExportError("Invalid data URL.") from exc

    media_type = header[5:].split(";")[0] or "application/octet-stream"
    is_base64 = header.endswith(";base64") or ";base64;" in header
    try:
        if is_base64:
            return media_type, base64.b64decode(encoded)
        return media_type, encoded.encode("utf-8")
    except (ValueError, binascii.Error) as exc:
        raise WorkflowExportError("Failed to decode data URL.") from exc


def _extension_from_media_type(media_type: str, asset_url: str | None = None) -> str:
    guessed = mimetypes.guess_extension(media_type or "")
    if guessed:
        return guessed
    if asset_url:
        suffix = re.search(r"(\.[a-zA-Z0-9]{2,5})(?:$|\?)", urlparse(asset_url).path)
        if suffix:
            return suffix.group(1)
    return ".bin"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value).strip("_")
    return slug or "asset"

