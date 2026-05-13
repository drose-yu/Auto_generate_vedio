import asyncio

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.core.config import settings
from app.models.schemas import (
    DoubaoConnectionConfig,
    TtsVoiceTestRequest,
    TtsVoiceTestResponse,
    WorkflowJobStatus,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowSavedRunSummary,
)
from app.services.doubao_client import DoubaoClient, DoubaoClientError
from app.services.export_service import (
    WorkflowExportError,
    build_assets_zip,
    get_saved_assets_zip_path,
    list_saved_runs,
    load_saved_result,
)
from app.services.job_store import (
    WorkflowJobNotFoundError,
    WorkflowJobStateError,
    workflow_job_store,
)
from app.services.workflow_service import WorkflowService, WorkflowServiceError
from app.services.video_compose_service import WorkflowComposeError, compose_saved_run_video

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.post("/run", response_model=WorkflowRunResponse)
async def run_workflow(request: WorkflowRunRequest) -> WorkflowRunResponse:
    service = WorkflowService()
    try:
        return await service.run(request)
    except WorkflowServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tts/test", response_model=TtsVoiceTestResponse)
async def test_tts_voice(request: TtsVoiceTestRequest) -> TtsVoiceTestResponse:
    resolved_tts = request.tts.model_copy(
        update={
            "enabled": True,
            "app_id": request.tts.app_id or settings.tts_app_id,
            "access_token": request.tts.access_token or settings.tts_access_token,
            "cluster": request.tts.cluster or settings.tts_cluster,
        }
    )
    if not resolved_tts.app_id or not resolved_tts.access_token:
        raise HTTPException(
            status_code=400,
            detail="Missing APP_TTS_APP_ID or APP_TTS_ACCESS_TOKEN in backend/.env.",
        )
    if not resolved_tts.voice_type:
        raise HTTPException(status_code=400, detail="voice_type is required.")

    client = DoubaoClient(
        DoubaoConnectionConfig(
            timeout_seconds=60,
        )
    )
    try:
        audio_url = await client.synthesize_speech(text=request.text, tts_config=resolved_tts)
        return TtsVoiceTestResponse(
            ok=True,
            message="Voice type is available.",
            voice_type=resolved_tts.voice_type,
            audio_url=audio_url,
        )
    except DoubaoClientError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Voice type test failed: {exc}",
        ) from exc
    finally:
        await client.aclose()


@router.post("/jobs", response_model=WorkflowJobStatus)
async def create_workflow_job(request: WorkflowRunRequest) -> WorkflowJobStatus:
    return await workflow_job_store.create_job(request)


@router.get("/jobs/{job_id}", response_model=WorkflowJobStatus)
async def get_workflow_job(job_id: str) -> WorkflowJobStatus:
    try:
        return await workflow_job_store.get_job(job_id)
    except WorkflowJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow job not found.") from exc


@router.post("/jobs/{job_id}/cancel", response_model=WorkflowJobStatus)
async def cancel_workflow_job(job_id: str) -> WorkflowJobStatus:
    try:
        return await workflow_job_store.cancel_job(job_id)
    except WorkflowJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow job not found.") from exc
    except WorkflowJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/assets")
async def download_workflow_assets(job_id: str) -> Response:
    try:
        job = await workflow_job_store.get_job(job_id)
    except WorkflowJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow job not found.") from exc

    if job.status != "completed" or job.result is None:
        raise HTTPException(status_code=409, detail="Workflow job is not completed yet.")

    try:
        payload = await build_assets_zip(job.result)
    except WorkflowExportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="workflow-assets-{job_id}.zip"',
        },
    )


@router.get("/history", response_model=list[WorkflowSavedRunSummary])
async def get_workflow_history(limit: int = Query(default=100, ge=1, le=500)) -> list[WorkflowSavedRunSummary]:
    return list_saved_runs(limit=limit)


@router.get("/history/{job_id}/result", response_model=WorkflowRunResponse)
async def get_saved_workflow_result(job_id: str) -> WorkflowRunResponse:
    try:
        return load_saved_result(job_id)
    except WorkflowExportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/history/{job_id}/assets")
async def download_saved_workflow_assets(job_id: str) -> FileResponse:
    try:
        zip_path = get_saved_assets_zip_path(job_id)
    except WorkflowExportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"workflow-assets-{job_id}.zip",
    )


@router.post("/history/{job_id}/compose")
async def compose_saved_workflow_video(
    job_id: str,
    with_audio: bool = Query(default=False),
    with_subtitles: bool = Query(default=False),
) -> FileResponse:
    try:
        output_path = await asyncio.to_thread(
            compose_saved_run_video,
            job_id,
            with_audio=with_audio,
            with_subtitles=with_subtitles,
        )
    except WorkflowComposeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=output_path.name,
    )

