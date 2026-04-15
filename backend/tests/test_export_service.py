import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
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
from app.services.export_service import (
    build_assets_zip,
    get_saved_assets_zip_path,
    list_saved_runs,
    load_saved_result,
    persist_workflow_run,
)


def _build_sample_result() -> WorkflowRunResponse:
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
        role_images=[
            RoleImageResult(
                role_name="书生",
                prompt="写实风，书生，青色布衣，古寺雨夜",
                image_url="data:image/png;base64,aGVsbG8=",
            )
        ],
        shot_role_map=[ShotRoleMap(roles_in_shot=["书生"], scene_note="书生在古寺避雨")] * 8,
        shots=[
            ShotResult(
                index=index,
                highlight=f"节点{index}",
                narration_text=f"旁白{index}",
                narration_audio_url="data:audio/mpeg;base64,aGVsbG8=",
                roles_in_shot=["书生"],
                scene_note="书生在古寺避雨",
                continuity_start_state=f"起始状态{index}",
                continuity_end_state=f"结束状态{index}",
                continuity_transition_to_next=f"转场到下镜头{index}",
                ref_urls=["data:image/png;base64,aGVsbG8="],
                camera_prompt="镜头描述",
                shot_video_prompt=f"视频提示词{index}",
                first_frame_prompt="首帧提示词",
                first_frame_url="data:image/png;base64,aGVsbG8=",
                shot_video_url="data:video/mp4;base64,aGVsbG8=",
            )
            for index in range(1, 9)
        ],
        warnings=[],
    )


@pytest.mark.anyio
async def test_build_assets_zip_includes_result_and_all_embedded_assets() -> None:
    result = _build_sample_result()

    payload = await build_assets_zip(result)
    archive = zipfile.ZipFile(io.BytesIO(payload))
    names = set(archive.namelist())

    assert "result.json" in names
    assert "role_images/01_书生.png" in names
    assert "shot_first_frames/shot_01.png" in names
    assert "shot_videos/shot_01.mp4" in names
    assert "shot_audio/shot_01.mp3" in names
    assert "debug/shot_continuity_system_prompt.txt" in names
    assert "debug/continuity_plan.json" in names
    assert "debug/shot_video_prompts.json" in names

    continuity_plan = archive.read("debug/continuity_plan.json").decode("utf-8")
    assert "起始状态1" in continuity_plan
    shot_video_prompts = archive.read("debug/shot_video_prompts.json").decode("utf-8")
    assert "视频提示词1" in shot_video_prompts


@pytest.mark.anyio
async def test_persist_workflow_run_and_history_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    test_root = Path("backend/.tmp_test_storage") / uuid4().hex
    test_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workflow_storage_dir", str(test_root))
    result = _build_sample_result()

    summary = await persist_workflow_run(
        "job_test_001",
        result,
        created_at=datetime(2026, 4, 14, tzinfo=timezone.utc),
    )

    assert summary.job_id == "job_test_001"
    assert summary.role_image_count == 1
    assert summary.shot_first_frame_count == 8
    assert summary.shot_audio_count == 8

    listed = list_saved_runs(limit=10)
    assert len(listed) == 1
    assert listed[0].job_id == "job_test_001"

    loaded_result = load_saved_result("job_test_001")
    assert loaded_result.title == "示例标题"

    zip_path = get_saved_assets_zip_path("job_test_001")
    assert zip_path.exists()
    assert (test_root / "job_test_001" / "debug" / "shot_continuity_system_prompt.txt").exists()
    assert (test_root / "job_test_001" / "debug" / "continuity_plan.json").exists()
    assert (test_root / "job_test_001" / "debug" / "shot_video_prompts.json").exists()
