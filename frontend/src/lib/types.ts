export interface DoubaoConnectionConfig {
  base_url: string;
  api_key?: string;
  chat_model: string;
  image_model: string;
  video_model: string;
  story_shot_count: number;
  video_duration_seconds: number;
  video_max_shots: number;
  timeout_seconds: number;
  image_size: string;
}

export interface WorkflowTextModels {
  default_model: string;
  story_model: string;
  role_model: string;
  shot_role_model: string;
  camera_model: string;
  shot_image_prompt_model: string;
}

export interface TtsConfig {
  enabled: boolean;
  endpoint: string;
  app_id?: string;
  access_token?: string;
  cluster: string;
  voice_type: string;
  remove_role_names: boolean;
  speed: number;
  uid: string;
}

export interface WorkflowRunRequest {
  story_text: string;
  connection: DoubaoConnectionConfig;
  text_models: WorkflowTextModels;
  tts: TtsConfig;
  max_images: number;
}

export interface TtsVoiceTestRequest {
  tts: TtsConfig;
  text: string;
}

export interface TtsVoiceTestResponse {
  ok: boolean;
  message: string;
  voice_type: string;
  audio_url?: string | null;
}

export interface RoleDescription {
  name: string;
  gender: string;
  age: string;
  appearance: string;
  outfit: string;
  mood: string;
  atmosphere: string;
  full_prompt: string;
}

export interface RoleImageResult {
  role_name: string;
  prompt: string;
  image_url?: string | null;
  warning?: string | null;
}

export interface ShotRoleMap {
  roles_in_shot: string[];
  scene_note: string;
}

export interface ShotResult {
  index: number;
  highlight: string;
  narration_text: string;
  narration_audio_url?: string | null;
  roles_in_shot: string[];
  scene_note: string;
  ref_urls: string[];
  camera_prompt: string;
  first_frame_prompt?: string | null;
  first_frame_url?: string | null;
  shot_video_url?: string | null;
}

export interface WorkflowRunResponse {
  title: string;
  key_highlights: string[];
  roles: string[];
  description_list: RoleDescription[];
  role_images: RoleImageResult[];
  shot_role_map: ShotRoleMap[];
  shots: ShotResult[];
  warnings: string[];
}

export interface WorkflowLogEntry {
  timestamp: string;
  stage: string;
  message: string;
  level: string;
}

export interface WorkflowJobStatus {
  job_id: string;
  status: "pending" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
  progress_percent: number;
  current_stage?: string | null;
  current_message?: string | null;
  logs: WorkflowLogEntry[];
  result?: WorkflowRunResponse | null;
  error_message?: string | null;
  saved_artifacts: boolean;
  saved_result_path?: string | null;
  saved_assets_zip_path?: string | null;
  saved_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowSavedRunSummary {
  job_id: string;
  title: string;
  created_at?: string | null;
  saved_at: string;
  saved_result_path: string;
  saved_assets_zip_path: string;
  role_image_count: number;
  shot_first_frame_count: number;
  shot_audio_count: number;
}

