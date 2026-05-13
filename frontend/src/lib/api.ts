import type {
  TtsVoiceTestRequest,
  TtsVoiceTestResponse,
  WorkflowJobStatus,
  WorkflowRunRequest,
  WorkflowRunResponse,
  WorkflowSavedRunSummary,
} from "./types";

export async function runWorkflow(payload: WorkflowRunRequest): Promise<WorkflowRunResponse> {
  const response = await fetch("/api/workflow/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }

  return (await response.json()) as WorkflowRunResponse;
}

export async function testTtsVoice(payload: TtsVoiceTestRequest): Promise<TtsVoiceTestResponse> {
  const response = await fetch("/api/workflow/tts/test", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }

  return (await response.json()) as TtsVoiceTestResponse;
}

export async function createWorkflowJob(payload: WorkflowRunRequest): Promise<WorkflowJobStatus> {
  const response = await fetch("/api/workflow/jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }

  return (await response.json()) as WorkflowJobStatus;
}

export async function getWorkflowJob(jobId: string): Promise<WorkflowJobStatus> {
  const response = await fetch(`/api/workflow/jobs/${jobId}`);
  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }
  return (await response.json()) as WorkflowJobStatus;
}

export async function cancelWorkflowJob(jobId: string): Promise<WorkflowJobStatus> {
  const response = await fetch(`/api/workflow/jobs/${jobId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }
  return (await response.json()) as WorkflowJobStatus;
}

export async function downloadWorkflowAssets(jobId: string): Promise<Blob> {
  const response = await fetch(`/api/workflow/jobs/${jobId}/assets`);
  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }
  return await response.blob();
}

export async function listSavedWorkflowRuns(limit = 100): Promise<WorkflowSavedRunSummary[]> {
  const response = await fetch(`/api/workflow/history?limit=${encodeURIComponent(String(limit))}`);
  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }
  return (await response.json()) as WorkflowSavedRunSummary[];
}

export async function getSavedWorkflowResult(jobId: string): Promise<WorkflowRunResponse> {
  const response = await fetch(`/api/workflow/history/${jobId}/result`);
  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }
  return (await response.json()) as WorkflowRunResponse;
}

export async function downloadSavedWorkflowAssets(jobId: string): Promise<Blob> {
  const response = await fetch(`/api/workflow/history/${jobId}/assets`);
  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }
  return await response.blob();
}

export async function composeSavedWorkflowVideo(jobId: string, withAudio = false, withSubtitles = false): Promise<Blob> {
  const query = new URLSearchParams({ with_audio: String(withAudio), with_subtitles: String(withSubtitles) });
  const response = await fetch(`/api/workflow/history/${jobId}/compose?${query.toString()}`, {
    method: "POST",
  });
  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message);
  }
  return await response.blob();
}

async function safeReadError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? `Request failed with status ${response.status}`;
  } catch {
    return `Request failed with status ${response.status}`;
  }
}

