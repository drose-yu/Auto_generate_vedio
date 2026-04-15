from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess

from app.core.config import settings
from app.services.export_service import WorkflowExportError, load_saved_result


class WorkflowComposeError(RuntimeError):
    pass


def compose_saved_run_video(job_id: str, *, with_audio: bool = False) -> Path:
    run_dir = _resolve_run_dir(job_id)
    try:
        result = load_saved_result(job_id)
    except WorkflowExportError as exc:
        raise WorkflowComposeError(str(exc)) from exc

    ffmpeg_bin = _find_ffmpeg_binary()
    if not ffmpeg_bin:
        raise WorkflowComposeError(
            "ffmpeg not found. Please install ffmpeg and ensure it is available in PATH."
        )

    video_paths, audio_paths = _collect_shot_assets(run_dir, result)
    if not video_paths:
        raise WorkflowComposeError(
            f"No local shot videos found for job '{job_id}'. "
            "Expected files under shot_videos/ (for example: shot_01.mp4)."
        )
    if with_audio and not audio_paths:
        raise WorkflowComposeError(
            f"No local narration audio found for job '{job_id}'. "
            "Expected files under shot_audio/ (for example: shot_01.mp3)."
        )

    output_dir = run_dir / "composed"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"workflow-composed-{job_id}-{timestamp}.mp4"

    tmp_dir = run_dir / f".compose_tmp_{job_id}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        video_only_path = tmp_dir / "video_only.mp4"
        _compose_video_track(ffmpeg_bin, video_paths, video_only_path)

        if with_audio and audio_paths:
            audio_track_path = tmp_dir / "audio_track.m4a"
            _compose_audio_track(ffmpeg_bin, audio_paths, audio_track_path)
            _mux_video_and_audio(ffmpeg_bin, video_only_path, audio_track_path, output_path)
        else:
            shutil.copyfile(video_only_path, output_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise WorkflowComposeError("Video compose failed: output file is missing or empty.")
    return output_path


def _resolve_run_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise WorkflowComposeError("Invalid job id.")
    root = Path(settings.workflow_storage_dir).expanduser()
    return root / job_id


def _find_ffmpeg_binary() -> str | None:
    for candidate in ("ffmpeg", "ffmpeg.exe"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _collect_shot_assets(run_dir: Path, result) -> tuple[list[Path], list[Path]]:
    shots = sorted(result.shots, key=lambda item: item.index)
    video_dir = run_dir / "shot_videos"
    audio_dir = run_dir / "shot_audio"

    videos: list[Path] = []
    audios: list[Path] = []
    for shot in shots:
        stem = f"shot_{shot.index:02d}"
        video = _find_asset_file(
            video_dir,
            stem,
            preferred_suffixes=(".mp4", ".mov", ".mkv", ".webm"),
        )
        if video is not None:
            videos.append(video)
            audio = _find_asset_file(
                audio_dir,
                stem,
                preferred_suffixes=(".mp3", ".wav", ".m4a", ".aac", ".flac"),
            )
            if audio is not None:
                audios.append(audio)
    return videos, audios


def _find_asset_file(directory: Path, stem: str, *, preferred_suffixes: tuple[str, ...]) -> Path | None:
    for suffix in preferred_suffixes:
        candidate = directory / f"{stem}{suffix}"
        if candidate.exists() and candidate.is_file():
            return candidate

    if not directory.exists():
        return None

    wildcard_matches = sorted(path for path in directory.glob(f"{stem}.*") if path.is_file())
    if wildcard_matches:
        return wildcard_matches[0]
    return None


def _compose_video_track(ffmpeg_bin: str, inputs: list[Path], output_path: Path) -> None:
    if len(inputs) == 1:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(inputs[0]),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        _run_ffmpeg(cmd, "compose single-shot video")
        return

    cmd = [ffmpeg_bin, "-y"]
    for path in inputs:
        cmd.extend(["-i", str(path)])

    concat_filter = "".join(f"[{index}:v:0]" for index in range(len(inputs)))
    concat_filter += f"concat=n={len(inputs)}:v=1:a=0[v]"
    cmd.extend(
        [
            "-filter_complex",
            concat_filter,
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    _run_ffmpeg(cmd, "compose video track")


def _compose_audio_track(ffmpeg_bin: str, inputs: list[Path], output_path: Path) -> None:
    if len(inputs) == 1:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(inputs[0]),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]
        _run_ffmpeg(cmd, "compose single-shot audio")
        return

    cmd = [ffmpeg_bin, "-y"]
    for path in inputs:
        cmd.extend(["-i", str(path)])

    concat_filter = "".join(f"[{index}:a:0]" for index in range(len(inputs)))
    concat_filter += f"concat=n={len(inputs)}:v=0:a=1[a]"
    cmd.extend(
        [
            "-filter_complex",
            concat_filter,
            "-map",
            "[a]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]
    )
    _run_ffmpeg(cmd, "compose audio track")


def _mux_video_and_audio(
    ffmpeg_bin: str,
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> None:
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_ffmpeg(cmd, "mux composed video and audio")


def _run_ffmpeg(cmd: list[str], purpose: str) -> None:
    completed = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode == 0:
        return

    stderr_text = ""
    if completed.stderr:
        stderr_text = completed.stderr.decode("utf-8", errors="replace").strip()
    if len(stderr_text) > 800:
        stderr_text = stderr_text[-800:]
    detail = f"ffmpeg failed to {purpose}."
    if stderr_text:
        detail = f"{detail} stderr: {stderr_text}"
    raise WorkflowComposeError(detail)
