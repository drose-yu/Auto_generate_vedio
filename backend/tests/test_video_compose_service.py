from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.schemas import (
    RoleDescription,
    RoleImageResult,
    ShotResult,
    ShotRoleMap,
    WorkflowRunResponse,
)
from app.services import video_compose_service
from app.services.video_compose_service import WorkflowComposeError, compose_saved_run_video


def _build_sample_result(shot_count: int = 2) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        title="示例标题",
        key_highlights=[f"节点{i}" for i in range(1, 9)],
        roles=["书生"],
        description_list=[
            RoleDescription(
                name="书生",
                gender="男",
                age="20岁",
                appearance="清瘦书生",
                outfit="青色布衣",
                mood="紧张但坚韧",
                atmosphere="雨夜古寺",
                full_prompt="写实风，书生，青色布衣，古寺雨夜",
            )
        ],
        role_images=[RoleImageResult(role_name="书生", prompt="写实风，书生，青色布衣，古寺雨夜")],
        shot_role_map=[ShotRoleMap(roles_in_shot=["书生"], scene_note="书生在古寺避雨")] * 8,
        shots=[
            ShotResult(
                index=index,
                highlight=f"节点{index}",
                narration_text=f"旁白{index}",
                narration_audio_url=f"https://example.com/audio/{index}.mp3",
                roles_in_shot=["书生"],
                scene_note="书生在古寺避雨",
                ref_urls=[],
                camera_prompt="镜头描述",
                first_frame_prompt="首帧提示词",
                first_frame_url=f"https://example.com/frame/{index}.png",
                shot_video_url=f"https://example.com/video/{index}.mp4",
            )
            for index in range(1, shot_count + 1)
        ],
        warnings=[],
    )


def _prepare_saved_run(
    tmp_root: Path,
    job_id: str,
    *,
    shot_count: int = 2,
    include_audio: bool = True,
) -> None:
    run_dir = tmp_root / job_id
    (run_dir / "shot_videos").mkdir(parents=True, exist_ok=True)
    (run_dir / "shot_audio").mkdir(parents=True, exist_ok=True)

    for index in range(1, shot_count + 1):
        (run_dir / "shot_videos" / f"shot_{index:02d}.mp4").write_bytes(b"video")
        if include_audio:
            (run_dir / "shot_audio" / f"shot_{index:02d}.mp3").write_bytes(b"audio")

    result = _build_sample_result(shot_count=shot_count)
    (run_dir / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")


def test_compose_saved_run_video_requires_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    test_root = Path("backend/.tmp_test_storage") / uuid4().hex
    test_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workflow_storage_dir", str(test_root))
    _prepare_saved_run(test_root, "job_test_001")
    monkeypatch.setattr(video_compose_service.shutil, "which", lambda _: None)

    with pytest.raises(WorkflowComposeError, match="ffmpeg not found"):
        compose_saved_run_video("job_test_001")


def test_compose_saved_run_video_executes_video_audio_mux_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_root = Path("backend/.tmp_test_storage") / uuid4().hex
    test_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workflow_storage_dir", str(test_root))
    _prepare_saved_run(test_root, "job_test_001")
    monkeypatch.setattr(video_compose_service.shutil, "which", lambda _: "ffmpeg")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        calls.append(cmd)
        output_path = Path(cmd[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(video_compose_service.subprocess, "run", fake_run)

    output = compose_saved_run_video("job_test_001", with_audio=True)

    assert output.exists()
    assert output.read_bytes() == b"ok"
    assert len(calls) == 3
    assert "concat=n=2:v=1:a=0[v]" in " ".join(calls[0])
    assert "concat=n=2:v=0:a=1[a]" in " ".join(calls[1])
    assert "-shortest" in calls[2]


def test_compose_saved_run_video_with_audio_requires_local_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_root = Path("backend/.tmp_test_storage") / uuid4().hex
    test_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workflow_storage_dir", str(test_root))
    _prepare_saved_run(test_root, "job_test_001", include_audio=False)
    monkeypatch.setattr(video_compose_service.shutil, "which", lambda _: "ffmpeg")

    with pytest.raises(WorkflowComposeError, match="No local narration audio found"):
        compose_saved_run_video("job_test_001", with_audio=True)
