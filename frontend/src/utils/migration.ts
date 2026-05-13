import type { WorkflowRunRequest, WorkflowTextModels } from "../lib/types";
import {
  DEFAULT_IMAGE_ENDPOINT,
  DEFAULT_STORY_SHOT_COUNT,
  DEFAULT_TEXT_ENDPOINT,
  DEFAULT_TTS_VOICE_TYPE,
  DEFAULT_VIDEO_MODEL_ID,
  GLOBAL_DEFAULTS_KEY,
  LEGACY_IMAGE_SIZE_VALUES,
  MAX_STORY_SHOT_COUNT,
  MIN_STORY_SHOT_COUNT,
  STORAGE_KEY,
  STORAGE_VERSION,
  type TextModelKey,
  TEXT_MODEL_KEYS,
  textModelOverrideFields,
  chatModelOptions,
  legacyImageModelAliases,
  legacyTextModelAliases,
  legacyTtsVoiceTypeAliases,
} from "../lib/constants";
import {
  clampInteger,
  normalizeString,
  normalizeVideoDurationForModel,
  resolveMainTextPresetValue,
  resolvePresetValue,
} from "./helpers";

export function createDefaultTextModels(): WorkflowTextModels {
  return {
    default_model: DEFAULT_TEXT_ENDPOINT,
    story_model: "",
    role_model: "",
    shot_role_model: "",
    camera_model: "",
  };
}

export function createDefaultState(defaultStoryShotCount: number): WorkflowRunRequest {
  const normalizedDefaultStoryShotCount = clampInteger(
    defaultStoryShotCount,
    MIN_STORY_SHOT_COUNT,
    MAX_STORY_SHOT_COUNT,
    DEFAULT_STORY_SHOT_COUNT,
  );
  return {
    story_text: "请输入剧情原文，点击运行后生成分镜与素材。",
    connection: {
      base_url: "https://ark.cn-beijing.volces.com/api/v3",
      chat_model: DEFAULT_TEXT_ENDPOINT,
      image_model: DEFAULT_IMAGE_ENDPOINT,
      video_model: "",
      story_shot_count: normalizedDefaultStoryShotCount,
      video_duration_seconds: 5,
      video_max_shots: normalizedDefaultStoryShotCount,
      timeout_seconds: 120,
      image_size: "2048x2048",
    },
    text_models: createDefaultTextModels(),
    tts: {
      enabled: false,
      endpoint: "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
      cluster: "volcano_tts",
      voice_type: DEFAULT_TTS_VOICE_TYPE,
      remove_role_names: true,
      speed: 1,
      uid: "doubao-workflow-web",
    },
    max_images: 3,
  };
}

export function loadGlobalDefaultStoryShotCount(): number {
  const fallback = DEFAULT_STORY_SHOT_COUNT;
  const raw = localStorage.getItem(GLOBAL_DEFAULTS_KEY);
  if (!raw) {
    return fallback;
  }
  try {
    const parsed = JSON.parse(raw) as { default_story_shot_count?: unknown };
    return clampInteger(
      parsed.default_story_shot_count,
      MIN_STORY_SHOT_COUNT,
      MAX_STORY_SHOT_COUNT,
      fallback,
    );
  } catch {
    return fallback;
  }
}

export function persistGlobalDefaultStoryShotCount(value: number): void {
  localStorage.setItem(
    GLOBAL_DEFAULTS_KEY,
    JSON.stringify({
      default_story_shot_count: value,
    }),
  );
}

export function migrateLegacyTextModel(value: string): string {
  const normalized = normalizeString(value);
  return legacyTextModelAliases[normalized] ?? normalized;
}

export function migrateLegacyImageModel(value: string): string {
  const normalized = normalizeString(value);
  return legacyImageModelAliases[normalized] ?? normalized;
}

export function migrateLegacyTtsVoiceType(value: string): string {
  const normalized = normalizeString(value);
  const mapped = legacyTtsVoiceTypeAliases[normalized] ?? normalized;
  return mapped || DEFAULT_TTS_VOICE_TYPE;
}

export function normalizeTextModelsForSubmit(value: WorkflowTextModels): WorkflowTextModels {
  return {
    default_model: normalizeString(value.default_model),
    story_model: normalizeString(value.story_model),
    role_model: normalizeString(value.role_model),
    shot_role_model: normalizeString(value.shot_role_model),
    camera_model: normalizeString(value.camera_model),
  };
}

export function buildTextModelPresetState(
  source: WorkflowRunRequest,
): Record<TextModelKey, string> {
  return {
    default_model: resolveMainTextPresetValue(
      source.text_models.default_model || (source.connection as { chat_model?: string }).chat_model || "",
      chatModelOptions,
    ),
    story_model: resolvePresetValue(source.text_models.story_model, chatModelOptions),
    role_model: resolvePresetValue(source.text_models.role_model, chatModelOptions),
    shot_role_model: resolvePresetValue(source.text_models.shot_role_model, chatModelOptions),
    camera_model: resolvePresetValue(source.text_models.camera_model, chatModelOptions),
  };
}

export function syncTextModelPresetSelections(
  form: WorkflowRunRequest,
  selectedTextModelPresets: Record<TextModelKey, string>,
): void {
  const next = buildTextModelPresetState(form);
  for (const key of TEXT_MODEL_KEYS) {
    selectedTextModelPresets[key] = next[key];
  }
}

export function setTextModelValue(
  form: WorkflowRunRequest,
  key: TextModelKey,
  value: string,
): void {
  form.text_models[key] = value;
  if (key === "default_model") {
    form.connection.chat_model = value;
  }
}

export function loadInitialState(defaultState: WorkflowRunRequest): WorkflowRunRequest {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) {
    return structuredClone(defaultState);
  }

  try {
    const parsed = JSON.parse(saved) as Partial<WorkflowRunRequest> & {
      _schema_version?: number;
    };
    const savedSchemaVersion = parsed._schema_version ?? 0;
    const { api_key: _ignoredApiKey, ...savedConnection } = parsed.connection ?? {};
    const {
      app_id: _ignoredTtsAppId,
      access_token: _ignoredTtsAccessToken,
      ...savedTts
    } = parsed.tts ?? {};

    const merged: WorkflowRunRequest = {
      ...structuredClone(defaultState),
      ...parsed,
      connection: {
        ...structuredClone(defaultState.connection),
        ...savedConnection,
      },
      text_models: {
        ...createDefaultTextModels(),
        ...(parsed.text_models ?? {}),
      },
      tts: {
        ...structuredClone(defaultState.tts),
        ...savedTts,
      },
    } as WorkflowRunRequest;

    if (savedSchemaVersion < STORAGE_VERSION) {
      merged.connection.chat_model = migrateLegacyTextModel(merged.connection.chat_model);
      merged.connection.image_model = migrateLegacyImageModel(merged.connection.image_model);
      for (const key of TEXT_MODEL_KEYS) {
        merged.text_models[key] = migrateLegacyTextModel(merged.text_models[key]);
      }
    }

    const defaultTextModel = normalizeString(
      merged.text_models.default_model || merged.connection.chat_model || defaultState.text_models.default_model,
    );
    merged.text_models.default_model = defaultTextModel;
    merged.connection.chat_model = defaultTextModel;

    for (const key of textModelOverrideFields.map((item) => item.key)) {
      merged.text_models[key] = normalizeString(merged.text_models[key]);
    }

    merged.connection.image_model = normalizeString(merged.connection.image_model);
    merged.connection.video_model = normalizeString(merged.connection.video_model);
    merged.connection.video_duration_seconds = normalizeVideoDurationForModel(
      merged.connection.video_duration_seconds,
      merged.connection.video_model,
      defaultState.connection.video_duration_seconds,
      DEFAULT_VIDEO_MODEL_ID,
    );
    merged.connection.story_shot_count = clampInteger(
      merged.connection.story_shot_count,
      MIN_STORY_SHOT_COUNT,
      MAX_STORY_SHOT_COUNT,
      defaultState.connection.story_shot_count,
    );
    merged.connection.video_max_shots = clampInteger(
      merged.connection.video_max_shots,
      0,
      merged.connection.story_shot_count,
      Math.min(defaultState.connection.video_max_shots, merged.connection.story_shot_count),
    );
    merged.connection.image_size = normalizeString(merged.connection.image_size) || defaultState.connection.image_size;
    merged.tts.voice_type = migrateLegacyTtsVoiceType(merged.tts.voice_type);

    if (savedSchemaVersion < STORAGE_VERSION) {
      if (!merged.connection.image_model) {
        merged.connection.image_model = DEFAULT_IMAGE_ENDPOINT;
      }
      if (LEGACY_IMAGE_SIZE_VALUES.has(merged.connection.image_size)) {
        merged.connection.image_size = defaultState.connection.image_size;
      }
    }

    return merged;
  } catch {
    return structuredClone(defaultState);
  }
}
