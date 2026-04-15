import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import settings
from app.models.schemas import WorkflowJobStatus, WorkflowLogEntry, WorkflowRunRequest
from app.services.export_service import WorkflowExportError, persist_workflow_run
from app.services.workflow_service import WorkflowReporter, WorkflowService, WorkflowServiceError


class WorkflowJobNotFoundError(KeyError):
    pass


class WorkflowJobStateError(RuntimeError):
    pass


class WorkflowJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, WorkflowJobStatus] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, request: WorkflowRunRequest) -> WorkflowJobStatus:
        timestamp = _utcnow()
        job = WorkflowJobStatus(
            job_id=uuid4().hex,
            status="pending",
            created_at=timestamp,
            updated_at=timestamp,
        )
        task = asyncio.create_task(self._run_job(job.job_id, request))
        async with self._lock:
            self._jobs[job.job_id] = job
            self._tasks[job.job_id] = task
        return job.model_copy(deep=True)

    async def get_job(self, job_id: str) -> WorkflowJobStatus:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise WorkflowJobNotFoundError(job_id)
            return job.model_copy(deep=True)

    async def cancel_job(self, job_id: str) -> WorkflowJobStatus:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise WorkflowJobNotFoundError(job_id)

            if job.status in {"cancelled", "cancelling"}:
                return job.model_copy(deep=True)
            if job.status in {"completed", "failed"}:
                raise WorkflowJobStateError("当前任务已结束，无法停止。")

            task = self._tasks.get(job_id)
            if task is None or task.done():
                raise WorkflowJobStateError("当前任务不在运行中，无法停止。")

            job.status = "cancelling"
            job.current_stage = "cancelling"
            job.current_message = "正在停止工作流，请稍候。"
            job.updated_at = _utcnow()

        await self._append_log(job_id, "cancelling", "收到停止请求，正在取消任务。", level="warning")
        task.cancel()
        return await self.get_job(job_id)

    async def _run_job(self, job_id: str, request: WorkflowRunRequest) -> None:
        service = WorkflowService()
        reporter = JobProgressReporter(self, job_id)
        try:
            await self._set_job_state(
                job_id,
                status="running",
                progress_percent=2,
                current_stage="queued",
                current_message="任务已创建，准备开始执行。",
            )
            result = await service.run(request, reporter=reporter)

            saved_artifacts = False
            saved_result_path: str | None = None
            saved_assets_zip_path: str | None = None
            saved_at: datetime | None = None

            if settings.workflow_auto_persist:
                await self._append_log(
                    job_id,
                    "archive",
                    "正在保存本次任务的 JSON 与图片/音频素材到本地磁盘。",
                )
                try:
                    created_at = await self._get_job_created_at(job_id)
                    summary = await persist_workflow_run(
                        job_id=job_id,
                        result=result,
                        created_at=created_at,
                    )
                    saved_artifacts = True
                    saved_result_path = summary.saved_result_path
                    saved_assets_zip_path = summary.saved_assets_zip_path
                    saved_at = summary.saved_at
                    await self._append_log(
                        job_id,
                        "archive",
                        "素材已保存，可在历史任务中随时查看与下载。",
                    )
                except WorkflowExportError as exc:
                    warning = f"素材自动保存失败：{exc}"
                    result.warnings.append(warning)
                    await self._append_log(job_id, "archive", warning, level="warning")

            await self._set_job_state(
                job_id,
                status="completed",
                progress_percent=100,
                current_stage="complete",
                current_message="工作流执行完成。",
                result=result,
                saved_artifacts=saved_artifacts,
                saved_result_path=saved_result_path,
                saved_assets_zip_path=saved_assets_zip_path,
                saved_at=saved_at,
            )
        except asyncio.CancelledError:
            await self._append_log(job_id, "cancelled", "任务已停止。", level="warning")
            await self._set_job_state(
                job_id,
                status="cancelled",
                current_stage="cancelled",
                current_message="工作流已停止。",
            )
        except WorkflowServiceError as exc:
            await self._append_log(job_id, "error", f"任务执行失败：{exc}", level="error")
            await self._set_job_state(
                job_id,
                status="failed",
                current_stage="failed",
                current_message="工作流执行失败。",
                error_message=str(exc),
            )
        except Exception as exc:  # pragma: no cover
            await self._append_log(job_id, "error", f"任务执行异常：{exc}", level="error")
            await self._set_job_state(
                job_id,
                status="failed",
                current_stage="failed",
                current_message="工作流执行异常。",
                error_message=str(exc),
            )
        finally:
            async with self._lock:
                self._tasks.pop(job_id, None)

    async def update_progress(
        self,
        job_id: str,
        *,
        stage: str,
        message: str,
        progress_percent: int,
    ) -> None:
        await self._set_job_state(
            job_id,
            status="running",
            current_stage=stage,
            current_message=message,
            progress_percent=progress_percent,
        )
        await self._append_log(job_id, stage, message)

    async def append_log(
        self,
        job_id: str,
        *,
        stage: str,
        message: str,
        progress_percent: int | None = None,
        level: str = "info",
    ) -> None:
        if progress_percent is not None:
            await self._set_job_state(
                job_id,
                progress_percent=progress_percent,
                current_stage=stage,
                current_message=message,
            )
        await self._append_log(job_id, stage, message, level=level)

    async def _set_job_state(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress_percent: int | None = None,
        current_stage: str | None = None,
        current_message: str | None = None,
        result=None,
        error_message: str | None = None,
        saved_artifacts: bool | None = None,
        saved_result_path: str | None = None,
        saved_assets_zip_path: str | None = None,
        saved_at: datetime | None = None,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise WorkflowJobNotFoundError(job_id)
            if job.status in {"cancelling", "cancelled"} and status not in {"completed", "failed", "cancelled"}:
                progress_percent = None
                current_stage = None
                current_message = None
                status = None
            if status is not None:
                job.status = status
            if progress_percent is not None:
                job.progress_percent = progress_percent
            if current_stage is not None:
                job.current_stage = current_stage
            if current_message is not None:
                job.current_message = current_message
            if result is not None:
                job.result = result
            if error_message is not None:
                job.error_message = error_message
            if saved_artifacts is not None:
                job.saved_artifacts = saved_artifacts
            if saved_result_path is not None:
                job.saved_result_path = saved_result_path
            if saved_assets_zip_path is not None:
                job.saved_assets_zip_path = saved_assets_zip_path
            if saved_at is not None:
                job.saved_at = saved_at
            job.updated_at = _utcnow()

    async def _append_log(
        self,
        job_id: str,
        stage: str,
        message: str,
        *,
        level: str = "info",
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise WorkflowJobNotFoundError(job_id)
            job.logs.append(
                WorkflowLogEntry(
                    timestamp=_utcnow(),
                    stage=stage,
                    message=message,
                    level=level,
                )
            )
            job.updated_at = _utcnow()

    async def _get_job_created_at(self, job_id: str) -> datetime | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return job.created_at


class JobProgressReporter(WorkflowReporter):
    def __init__(self, store: WorkflowJobStore, job_id: str) -> None:
        self._store = store
        self._job_id = job_id

    async def stage(self, stage: str, message: str, progress_percent: int) -> None:
        await self._store.update_progress(
            self._job_id,
            stage=stage,
            message=message,
            progress_percent=progress_percent,
        )

    async def log(
        self,
        stage: str,
        message: str,
        *,
        progress_percent: int | None = None,
        level: str = "info",
    ) -> None:
        await self._store.append_log(
            self._job_id,
            stage=stage,
            message=message,
            progress_percent=progress_percent,
            level=level,
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


workflow_job_store = WorkflowJobStore()
