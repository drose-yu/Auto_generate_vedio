import asyncio

import pytest

from app.models.schemas import DoubaoConnectionConfig, WorkflowRunRequest
from app.services import job_store as job_store_module


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class SlowWorkflowService:
    async def run(self, request: WorkflowRunRequest, reporter=None):  # pragma: no cover - cancellation path only
        if reporter is not None:
            await reporter.stage("story", "开始执行慢任务。", 10)
        await asyncio.sleep(10)
        raise AssertionError("The slow workflow service should have been cancelled.")


@pytest.mark.anyio
async def test_cancel_job_marks_workflow_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_store_module, "WorkflowService", SlowWorkflowService)
    store = job_store_module.WorkflowJobStore()
    request = WorkflowRunRequest(
        story_text="测试剧情",
        connection=DoubaoConnectionConfig(chat_model="ep-test-chat"),
    )

    job = await store.create_job(request)
    await asyncio.sleep(0.05)

    cancelling_job = await store.cancel_job(job.job_id)
    assert cancelling_job.status == "cancelling"

    cancelled_job = None
    for _ in range(50):
        latest = await store.get_job(job.job_id)
        if latest.status == "cancelled":
            cancelled_job = latest
            break
        await asyncio.sleep(0.02)

    assert cancelled_job is not None
    assert cancelled_job.current_stage == "cancelled"
    assert cancelled_job.current_message == "工作流已停止。"
    assert any(entry.stage == "cancelled" for entry in cancelled_job.logs)
