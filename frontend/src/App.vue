<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

import {
  cancelWorkflowJob,
  composeSavedWorkflowVideo,
  createWorkflowJob,
  downloadSavedWorkflowAssets,
  downloadWorkflowAssets,
  getSavedWorkflowResult,
  getWorkflowJob,
  listSavedWorkflowRuns,
  testTtsVoice,
} from "./lib/api";
import type {
  WorkflowJobStatus,
  WorkflowRunRequest,
  WorkflowRunResponse,
  WorkflowSavedRunSummary,
  WorkflowTextModels,
} from "./lib/types";

const STORAGE_KEY = "doubao-workflow-config";
const GLOBAL_DEFAULTS_KEY = "doubao-workflow-global-defaults";
const STORAGE_VERSION = 6;
const POLL_INTERVAL_MS = 1500;
const CUSTOM_VALUE = "__custom__";
const DEFAULT_TEXT_ENDPOINT = "";
const DEFAULT_IMAGE_ENDPOINT = "ep-20260413162910-d72lb";
const DEFAULT_TTS_VOICE_TYPE = "BV700_streaming";
const DEFAULT_VIDEO_MODEL_ID = "doubao-seedance-1-5-pro-251215";
const REMOVED_TEXT_ENDPOINT = "ep-m-202512011114108-wlrg5";
const LEGACY_IMAGE_SIZE_VALUES = new Set(["576x1024", "1024x576", "1024x1024", "864x1152", "1152x864"]);
const MIN_STORY_SHOT_COUNT = 1;
const MAX_STORY_SHOT_COUNT = 20;
const DEFAULT_STORY_SHOT_COUNT = 8;

type ModelOption = {
  label: string;
  value: string;
};

type VideoDurationRule = {
  min: number;
  max: number;
  allowAuto: boolean;
};

type VideoDurationOption = {
  label: string;
  value: number;
};

const PROJECT_TEXT_ENDPOINT_OPTIONS: ModelOption[] = [
  {
    label: "Doubao-1.5-pro-32k | ep-m-20260226012309-yfjzs",
    value: "ep-m-20260226012309-yfjzs",
  },
  {
    label: "Doubao-Seed-1.6-lite | ep-m-20251201143833-8lslh",
    value: "ep-m-20251201143833-8lslh",
  },
  {
    label: "Doubao-Seed-1.6 | ep-m-202512011114108-wlrg5",
    value: "ep-m-202512011114108-wlrg5",
  },
  {
    label: "Doubao-Seed-1.6(251015) | ep-m-20251201102738-pq7rz",
    value: "ep-m-20251201102738-pq7rz",
  },
];

const TEXT_MODEL_KEYS = [
  "default_model",
  "story_model",
  "role_model",
  "shot_role_model",
  "camera_model",
] as const;

type TextModelKey = (typeof TEXT_MODEL_KEYS)[number];

const textModelOverrideFields: Array<{
  key: Exclude<TextModelKey, "default_model">;
  label: string;
  hint: string;
}> = [
  { key: "story_model", label: "剧情模型", hint: "用于生成剧情文本。" },
  { key: "role_model", label: "角色模型", hint: "用于生成角色设定。" },
  { key: "shot_role_model", label: "镜头角色模型", hint: "用于生成分镜中的角色描述。" },
  { key: "camera_model", label: "分镜模型", hint: "用于生成镜头脚本和分镜信息。" },
];

const chatModelOptions: ModelOption[] = [
  { label: "默认（使用后端配置）", value: "" },
  ...PROJECT_TEXT_ENDPOINT_OPTIONS,
  { label: "Doubao-Seed-2.0-pro | doubao-seed-2-0-pro", value: "doubao-seed-2-0-pro" },
  { label: "Doubao-Seed-2.0-lite | doubao-seed-2-0-lite", value: "doubao-seed-2-0-lite" },
  { label: "Doubao-Seed-2.0-mini | doubao-seed-2-0-mini", value: "doubao-seed-2-0-mini" },
  { label: "DeepSeek-V3.2 | deepseek-v3-2", value: "deepseek-v3-2" },
  { label: "DeepSeek-R1 | deepseek-r1", value: "deepseek-r1" },
  { label: "自定义模型 ID", value: CUSTOM_VALUE },
];

const overrideTextModelOptions: ModelOption[] = [
  { label: "跟随默认模型", value: "" },
  ...chatModelOptions.filter((option) => option.value !== ""),
];

const imageModelOptions: ModelOption[] = [
  { label: "默认（使用后端配置）", value: "" },
  { label: `默认图片模型 | ${DEFAULT_IMAGE_ENDPOINT}`, value: DEFAULT_IMAGE_ENDPOINT },
  { label: "Doubao-Seedream-5.0-lite | doubao-seedream-5-0", value: "doubao-seedream-5-0" },
  { label: "Doubao-Seedream-4.5 | doubao-seedream-4-5", value: "doubao-seedream-4-5" },
  { label: "Doubao-Seedream-4.0 | doubao-seedream-4-0", value: "doubao-seedream-4-0" },
  { label: "自定义图片模型 ID", value: CUSTOM_VALUE },
];

const videoModelOptions: ModelOption[] = [
  { label: "默认（使用后端配置）", value: "" },
  {
    label: "Doubao-Seedance-2.0 | doubao-seedance-2-0",
    value: "doubao-seedance-2-0",
  },
  {
    label: "Doubao-Seedance-2.0-fast | doubao-seedance-2-0-fast",
    value: "doubao-seedance-2-0-fast",
  },
  {
    label: "Doubao-Seedance-1.5-pro-251215 | doubao-seedance-1-5-pro-251215",
    value: "doubao-seedance-1-5-pro-251215",
  },
  {
    label: "Doubao-Seedance-1.0-pro | doubao-seedance-1-0-pro",
    value: "doubao-seedance-1-0-pro",
  },
  {
    label: "Doubao-Seedance-1.0-pro-fast | doubao-seedance-1-0-pro-fast",
    value: "doubao-seedance-1-0-pro-fast",
  },
  {
    label: "Doubao-Seedance-1.0-lite(t2v) | doubao-seedance-1-0-lite-t2v",
    value: "doubao-seedance-1-0-lite-t2v",
  },
  {
    label: "Doubao-Seedance-1.0-lite(i2v) | doubao-seedance-1-0-lite-i2v",
    value: "doubao-seedance-1-0-lite-i2v",
  },
  { label: "自定义视频模型 ID", value: CUSTOM_VALUE },
];

const imageSizeOptions: ModelOption[] = [
  { label: "2048 x 2048", value: "2048x2048" },
  { label: "2848 x 1600", value: "2848x1600" },
  { label: "1600 x 2848", value: "1600x2848" },
  { label: "自定义尺寸", value: CUSTOM_VALUE },
];

const ttsVoiceOptions: ModelOption[] = [
  { label: "BV700_streaming (TTS 2.0 test)", value: "BV700_streaming" },
  { label: "Vivi 2.0 | zh_female_vv_uranus_bigtts", value: "zh_female_vv_uranus_bigtts" },
  { label: "小何 2.0 | zh_female_xiaohe_uranus_bigtts", value: "zh_female_xiaohe_uranus_bigtts" },
  { label: "云舟 2.0 | zh_male_m191_uranus_bigtts", value: "zh_male_m191_uranus_bigtts" },
  { label: "小天 2.0 | zh_male_taocheng_uranus_bigtts", value: "zh_male_taocheng_uranus_bigtts" },
  { label: "刘飞 2.0 | zh_male_liufei_uranus_bigtts", value: "zh_male_liufei_uranus_bigtts" },
  { label: "魅力苏菲 2.0 | zh_male_sophie_uranus_bigtts", value: "zh_male_sophie_uranus_bigtts" },
  { label: "清新女声 2.0 | zh_female_qingxinnvsheng_uranus_bigtts", value: "zh_female_qingxinnvsheng_uranus_bigtts" },
  { label: "知性灿灿 2.0 | zh_female_cancan_uranus_bigtts", value: "zh_female_cancan_uranus_bigtts" },
  { label: "撒娇学妹 2.0 | zh_female_sajiaoxuemei_uranus_bigtts", value: "zh_female_sajiaoxuemei_uranus_bigtts" },
  { label: "甜美小源 2.0 | zh_female_tianmeixiaoyuan_uranus_bigtts", value: "zh_female_tianmeixiaoyuan_uranus_bigtts" },
  { label: "甜美桃子 2.0 | zh_female_tianmeitaozi_uranus_bigtts", value: "zh_female_tianmeitaozi_uranus_bigtts" },
  { label: "爽快思思 2.0 | zh_female_shuangkuaisisi_uranus_bigtts", value: "zh_female_shuangkuaisisi_uranus_bigtts" },
  { label: "佩奇猪 2.0 | zh_female_peiqi_uranus_bigtts", value: "zh_female_peiqi_uranus_bigtts" },
  { label: "邻家女孩 2.0 | zh_female_linjianvhai_uranus_bigtts", value: "zh_female_linjianvhai_uranus_bigtts" },
  { label: "少年梓辛/Brayan 2.0 | zh_male_shaonianzixin_uranus_bigtts", value: "zh_male_shaonianzixin_uranus_bigtts" },
  { label: "猴哥 2.0 | zh_male_sunwukong_uranus_bigtts", value: "zh_male_sunwukong_uranus_bigtts" },
  { label: "Tina老师 2.0 | zh_female_yingyujiaoxue_uranus_bigtts", value: "zh_female_yingyujiaoxue_uranus_bigtts" },
  { label: "暖阳女声 2.0 | zh_female_kefunvsheng_uranus_bigtts", value: "zh_female_kefunvsheng_uranus_bigtts" },
  { label: "儿童绘本 2.0 | zh_female_xiaoxue_uranus_bigtts", value: "zh_female_xiaoxue_uranus_bigtts" },
  { label: "大壹 2.0 | zh_male_dayi_uranus_bigtts", value: "zh_male_dayi_uranus_bigtts" },
  { label: "黑猫侦探社咪仔 2.0 | zh_female_mizai_uranus_bigtts", value: "zh_female_mizai_uranus_bigtts" },
  { label: "鸡汤女 2.0 | zh_female_jitangnv_uranus_bigtts", value: "zh_female_jitangnv_uranus_bigtts" },
  { label: "魅力女友 2.0 | zh_female_meilinvyou_uranus_bigtts", value: "zh_female_meilinvyou_uranus_bigtts" },
  { label: "流畅女声 2.0 | zh_female_liuchangnv_uranus_bigtts", value: "zh_female_liuchangnv_uranus_bigtts" },
  { label: "儒雅逸辰 2.0 | zh_male_ruyayichen_uranus_bigtts", value: "zh_male_ruyayichen_uranus_bigtts" },
  { label: "Tim | en_male_tim_uranus_bigtts", value: "en_male_tim_uranus_bigtts" },
  { label: "Dacey | en_female_dacey_uranus_bigtts", value: "en_female_dacey_uranus_bigtts" },
  { label: "Stokie | en_female_stokie_uranus_bigtts", value: "en_female_stokie_uranus_bigtts" },
  { label: "可爱女生 | saturn_zh_female_keainvsheng_tob", value: "saturn_zh_female_keainvsheng_tob" },
  { label: "调皮公主 | saturn_zh_female_tiaopigongzhu_tob", value: "saturn_zh_female_tiaopigongzhu_tob" },
  { label: "爽朗少年 | saturn_zh_male_shuanglangshaonian_tob", value: "saturn_zh_male_shuanglangshaonian_tob" },
  { label: "天才同桌 | saturn_zh_male_tiancaitongzhuo_tob", value: "saturn_zh_male_tiancaitongzhuo_tob" },
  { label: "知性灿灿 | saturn_zh_female_cancan_tob", value: "saturn_zh_female_cancan_tob" },
  { label: "轻盈朵朵 2.0 | saturn_zh_female_qingyingduoduo_cs_tob", value: "saturn_zh_female_qingyingduoduo_cs_tob" },
  { label: "温婉珊珊 2.0 | saturn_zh_female_wenwanshanshan_cs_tob", value: "saturn_zh_female_wenwanshanshan_cs_tob" },
  { label: "热情艾娜 2.0 | saturn_zh_female_reqingaina_cs_tob", value: "saturn_zh_female_reqingaina_cs_tob" },
  { label: "BV001_streaming", value: "BV001_streaming" },
  { label: "BV002_streaming", value: "BV002_streaming" },
  { label: "BV003_streaming", value: "BV003_streaming" },
  { label: "自定义 Voice Type", value: CUSTOM_VALUE },
];

const stageLabels: Record<string, string> = {
  queued: "排队中",
  story: "生成剧情",
  roles: "生成角色",
  shot_roles: "生成镜头角色",
  images: "生成图片提示词",
  shots: "生成镜头视频",
  audio: "生成旁白音频",
  cancelling: "取消中",
  cancelled: "已取消",
  complete: "已完成",
  failed: "失败",
  error: "错误",
};

const legacyTextModelAliases: Record<string, string> = {
  "doubao-seed-character": "",
  [REMOVED_TEXT_ENDPOINT]: "",
};

const legacyImageModelAliases: Record<string, string> = {
  "doubao-seedream-3-0-t2i": DEFAULT_IMAGE_ENDPOINT,
};

const legacyTtsVoiceTypeAliases: Record<string, string> = {
  BV113_streaming: DEFAULT_TTS_VOICE_TYPE,
};

const globalDefaultStoryShotCount = ref(loadGlobalDefaultStoryShotCount());
const defaultState: WorkflowRunRequest = createDefaultState(globalDefaultStoryShotCount.value);

const form = reactive(loadInitialState());
const errorMessage = ref("");
const result = ref<WorkflowRunResponse | null>(null);
const jobStatus = ref<WorkflowJobStatus | null>(null);
const isPolling = ref(false);
const isDownloadingAssets = ref(false);
const isDownloadingHistoryAssets = ref(false);
const isComposingHistoryVideo = ref(false);
const isLoadingHistory = ref(false);
const historyError = ref("");
const historyRuns = ref<WorkflowSavedRunSummary[]>([]);
const selectedHistoryJobId = ref("");
const isTestingVoice = ref(false);
const voiceTestText = ref("这是一个语音合成测试文本。");
const voiceTestAudioUrl = ref("");
const voiceTestMessage = ref("");
const resultPanelRef = ref<HTMLElement | null>(null);
const selectedTextModelPresets = reactive(buildTextModelPresetState(form));
const selectedImageModel = ref(resolvePresetValue(form.connection.image_model, imageModelOptions));
const selectedVideoModel = ref(resolvePresetValue(form.connection.video_model, videoModelOptions));
const selectedImageSize = ref(resolvePresetValue(form.connection.image_size, imageSizeOptions));
form.tts.voice_type = migrateLegacyTtsVoiceType(form.tts.voice_type);
const selectedTtsVoice = ref(resolvePresetValue(form.tts.voice_type, ttsVoiceOptions));
let pollTimer: number | null = null;

const effectiveVideoModel = computed(() => normalizeString(form.connection.video_model) || DEFAULT_VIDEO_MODEL_ID);
const effectiveStoryShotCount = computed(() =>
  clampInteger(
    form.connection.story_shot_count,
    MIN_STORY_SHOT_COUNT,
    MAX_STORY_SHOT_COUNT,
    defaultState.connection.story_shot_count,
  ),
);
const videoDurationRule = computed(() => resolveVideoDurationRule(effectiveVideoModel.value));
const videoDurationOptions = computed(() => buildVideoDurationOptions(videoDurationRule.value));
const videoDurationHint = computed(() => {
  const rule = videoDurationRule.value;
  const autoHint = rule.allowAuto ? "，也可选择自动（-1）。" : "。";
  return `当前模型支持 ${rule.min}~${rule.max} 秒${autoHint}`;
});

const isRunning = computed(() => {
  const status = jobStatus.value?.status;
  return status === "pending" || status === "running";
});
const isCancelling = computed(() => jobStatus.value?.status === "cancelling");
const canCancel = computed(() => {
  const status = jobStatus.value?.status;
  return status === "pending" || status === "running" || status === "cancelling";
});
const hasMainTextModel = computed(() => normalizeString(form.text_models.default_model).length > 0);

const completionRate = computed(() => {
  if (!result.value) {
    return 0;
  }
  const total = result.value.shots.length || 1;
  const withAudio = result.value.shots.filter((shot) => shot.narration_audio_url).length;
  return Math.round((withAudio / total) * 100);
});

const progressPercent = computed(() => jobStatus.value?.progress_percent ?? 0);
const currentStageLabel = computed(() => {
  const stage = jobStatus.value?.current_stage;
  if (!stage) {
    return "未开始";
  }
  return stageLabels[stage] ?? stage;
});
const currentMessage = computed(() => jobStatus.value?.current_message ?? "等待任务开始");
const logs = computed(() => jobStatus.value?.logs ?? []);
const roleImageMap = computed(() => {
  const map = new Map<string, string>();
  for (const item of result.value?.role_images ?? []) {
    if (item.image_url) {
      map.set(item.role_name, item.image_url);
    }
  }
  return map;
});

watch(
  globalDefaultStoryShotCount,
  (value) => {
    const normalized = clampInteger(
      value,
      MIN_STORY_SHOT_COUNT,
      MAX_STORY_SHOT_COUNT,
      DEFAULT_STORY_SHOT_COUNT,
    );
    if (normalized !== value) {
      globalDefaultStoryShotCount.value = normalized;
      return;
    }
    persistGlobalDefaultStoryShotCount(normalized);
    defaultState.connection.story_shot_count = normalized;
    defaultState.connection.video_max_shots = normalized;
  },
  { immediate: true },
);

watch(
  form,
  (value) => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...value,
        _schema_version: STORAGE_VERSION,
      }),
    );
  },
  { deep: true },
);

watch(
  selectedTextModelPresets,
  (value) => {
    for (const key of TEXT_MODEL_KEYS) {
      if (value[key] !== CUSTOM_VALUE) {
        setTextModelValue(key, value[key]);
      }
    }
  },
  { deep: true },
);

watch(
  () => form.text_models.default_model,
  (value) => {
    form.connection.chat_model = value.trim();
  },
);

watch(selectedImageModel, (value) => {
  if (value !== CUSTOM_VALUE) {
    form.connection.image_model = value;
  }
});

watch(selectedVideoModel, (value) => {
  if (value !== CUSTOM_VALUE) {
    form.connection.video_model = value;
  }
});

watch(
  videoDurationRule,
  (rule) => {
    form.connection.video_duration_seconds = normalizeVideoDurationByRule(
      form.connection.video_duration_seconds,
      rule,
      defaultState.connection.video_duration_seconds,
    );
  },
  { immediate: true },
);

watch(
  () => form.connection.story_shot_count,
  (value) => {
    const normalizedStoryShotCount = clampInteger(
      value,
      MIN_STORY_SHOT_COUNT,
      MAX_STORY_SHOT_COUNT,
      defaultState.connection.story_shot_count,
    );
    if (normalizedStoryShotCount !== value) {
      form.connection.story_shot_count = normalizedStoryShotCount;
      return;
    }
    form.connection.video_max_shots = clampInteger(
      form.connection.video_max_shots,
      0,
      normalizedStoryShotCount,
      Math.min(defaultState.connection.video_max_shots, normalizedStoryShotCount),
    );
  },
  { immediate: true },
);

watch(selectedImageSize, (value) => {
  if (value !== CUSTOM_VALUE) {
    form.connection.image_size = value;
  }
});

watch(selectedTtsVoice, (value) => {
  if (value !== CUSTOM_VALUE) {
    form.tts.voice_type = value;
  }
});

onMounted(() => {
  void loadHistoryRuns();
});

onBeforeUnmount(() => {
  stopPolling();
});

async function handleSubmit() {
  stopPolling();
  errorMessage.value = "";
  result.value = null;

  if (!hasMainTextModel.value) {
    errorMessage.value = "请先配置主文本模型（默认模型）后再运行。";
    return;
  }

  try {
    jobStatus.value = await createWorkflowJob(buildPayload());
    await pollJob();
    if (jobStatus.value && (jobStatus.value.status === "pending" || jobStatus.value.status === "running")) {
      startPolling();
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "任务提交失败，请检查配置后重试。";
  }
}

function buildPayload(): WorkflowRunRequest {
  const text_models = normalizeTextModelsForSubmit(form.text_models);
  const storyShotCount = clampInteger(
    form.connection.story_shot_count,
    MIN_STORY_SHOT_COUNT,
    MAX_STORY_SHOT_COUNT,
    defaultState.connection.story_shot_count,
  );
  const videoMaxShots = clampInteger(
    form.connection.video_max_shots,
    0,
    storyShotCount,
    Math.min(defaultState.connection.video_max_shots, storyShotCount),
  );
  return {
    ...form,
    story_text: form.story_text.trim(),
    connection: {
      ...form.connection,
      chat_model: text_models.default_model,
      image_model: form.connection.image_model.trim(),
      video_model: form.connection.video_model.trim(),
      story_shot_count: storyShotCount,
      video_duration_seconds: normalizeVideoDurationForModel(
        form.connection.video_duration_seconds,
        form.connection.video_model,
        defaultState.connection.video_duration_seconds,
      ),
      video_max_shots: videoMaxShots,
      image_size: form.connection.image_size.trim(),
    },
    text_models,
  };
}

function startPolling() {
  stopPolling();
  pollTimer = window.setInterval(() => {
    void pollJob();
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollJob() {
  if (!jobStatus.value || isPolling.value) {
    return;
  }

  isPolling.value = true;
  try {
    const next = await getWorkflowJob(jobStatus.value.job_id);
    jobStatus.value = next;

    if (next.status === "completed") {
      result.value = next.result ?? null;
      selectedHistoryJobId.value = next.job_id;
      void loadHistoryRuns();
      stopPolling();
      return;
    }

    if (next.status === "cancelled") {
      stopPolling();
      return;
    }

    if (next.status === "failed") {
      errorMessage.value = next.error_message ?? "任务执行失败。";
      stopPolling();
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "查询任务状态失败。";
    stopPolling();
  } finally {
    isPolling.value = false;
  }
}

async function handleCancel() {
  if (!jobStatus.value || isCancelling.value) {
    return;
  }

  errorMessage.value = "";
  try {
    const next = await cancelWorkflowJob(jobStatus.value.job_id);
    jobStatus.value = next;
    if (next.status === "cancelled") {
      stopPolling();
      return;
    }
    startPolling();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "取消任务失败，请重试。";
  }
}

function resetToDefault() {
  Object.assign(form, structuredClone(defaultState));
  syncTextModelPresetSelections();
  selectedImageModel.value = resolvePresetValue(form.connection.image_model, imageModelOptions);
  selectedVideoModel.value = resolvePresetValue(form.connection.video_model, videoModelOptions);
  selectedImageSize.value = resolvePresetValue(form.connection.image_size, imageSizeOptions);
  selectedTtsVoice.value = resolvePresetValue(form.tts.voice_type, ttsVoiceOptions);
  result.value = null;
  errorMessage.value = "";
  jobStatus.value = null;
  stopPolling();
}

function loadInitialState(): WorkflowRunRequest {
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

function formatTimestamp(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function exportResultJson() {
  if (!result.value) {
    return;
  }
  const blob = new Blob([JSON.stringify(result.value, null, 2)], { type: "application/json;charset=utf-8" });
  saveBlob(blob, "workflow-result.json");
}

async function exportAssetsZip() {
  if (!jobStatus.value) {
    return;
  }

  isDownloadingAssets.value = true;
  errorMessage.value = "";
  try {
    const blob = await downloadWorkflowAssets(jobStatus.value.job_id);
    saveBlob(blob, `workflow-assets-${jobStatus.value.job_id}.zip`);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "下载产物失败，请重试。";
  } finally {
    isDownloadingAssets.value = false;
  }
}

async function loadHistoryRuns() {
  isLoadingHistory.value = true;
  historyError.value = "";
  try {
    historyRuns.value = await listSavedWorkflowRuns(100);
  } catch (error) {
    historyError.value = error instanceof Error ? error.message : "加载历史记录失败，请重试。";
  } finally {
    isLoadingHistory.value = false;
  }
}

async function focusResultPanel() {
  await nextTick();
  resultPanelRef.value?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function openHistoryRun(jobId: string, options?: { scrollToResult?: boolean }) {
  errorMessage.value = "";
  try {
    result.value = await getSavedWorkflowResult(jobId);
    selectedHistoryJobId.value = jobId;
    if (options?.scrollToResult) {
      await focusResultPanel();
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "加载历史任务详情失败，请重试。";
  }
}

async function handleHistorySelect(jobId: string) {
  await openHistoryRun(jobId, { scrollToResult: true });
}

async function downloadHistoryAssets(jobId: string) {
  isDownloadingHistoryAssets.value = true;
  errorMessage.value = "";
  try {
    const blob = await downloadSavedWorkflowAssets(jobId);
    saveBlob(blob, `workflow-assets-${jobId}.zip`);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "下载历史产物失败，请重试。";
  } finally {
    isDownloadingHistoryAssets.value = false;
  }
}

async function composeHistoryVideo(jobId: string) {
  isComposingHistoryVideo.value = true;
  errorMessage.value = "";
  try {
    const blob = await composeSavedWorkflowVideo(jobId, true, true);
    saveBlob(blob, `workflow-composed-with-audio-${jobId}.mp4`);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "合成历史视频失败，请重试。";
  } finally {
    isComposingHistoryVideo.value = false;
  }
}

async function handleTestVoiceType() {
  isTestingVoice.value = true;
  errorMessage.value = "";
  voiceTestAudioUrl.value = "";
  voiceTestMessage.value = "";
  try {
    const payload = {
      tts: {
        ...form.tts,
        enabled: true,
      },
      text: voiceTestText.value.trim() || "这是一个语音合成测试文本。",
    };
    const response = await testTtsVoice(payload);
    voiceTestAudioUrl.value = response.audio_url ?? "";
    voiceTestMessage.value = response.message;
  } catch (error) {
    voiceTestMessage.value = error instanceof Error ? error.message : "语音测试失败，请重试。";
  } finally {
    isTestingVoice.value = false;
  }
}

function saveBlob(blob: Blob, filename: string) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

function createDefaultState(defaultStoryShotCount: number): WorkflowRunRequest {
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
    subtitle_enabled: false,
  };
}

function loadGlobalDefaultStoryShotCount(): number {
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

function persistGlobalDefaultStoryShotCount(value: number) {
  localStorage.setItem(
    GLOBAL_DEFAULTS_KEY,
    JSON.stringify({
      default_story_shot_count: value,
    }),
  );
}

function createDefaultTextModels(): WorkflowTextModels {
  return {
    default_model: DEFAULT_TEXT_ENDPOINT,
    story_model: "",
    role_model: "",
    shot_role_model: "",
    camera_model: "",
  };
}

function buildTextModelPresetState(source: WorkflowRunRequest): Record<TextModelKey, string> {
  return {
    default_model: resolveMainTextPresetValue(source.text_models.default_model || source.connection.chat_model),
    story_model: resolvePresetValue(source.text_models.story_model, overrideTextModelOptions),
    role_model: resolvePresetValue(source.text_models.role_model, overrideTextModelOptions),
    shot_role_model: resolvePresetValue(source.text_models.shot_role_model, overrideTextModelOptions),
    camera_model: resolvePresetValue(source.text_models.camera_model, overrideTextModelOptions),
  };
}

function syncTextModelPresetSelections() {
  const next = buildTextModelPresetState(form);
  for (const key of TEXT_MODEL_KEYS) {
    selectedTextModelPresets[key] = next[key];
  }
}

function setTextModelValue(key: TextModelKey, value: string) {
  form.text_models[key] = value;
  if (key === "default_model") {
    form.connection.chat_model = value;
  }
}

function normalizeTextModelsForSubmit(value: WorkflowTextModels): WorkflowTextModels {
  return {
    default_model: normalizeString(value.default_model),
    story_model: normalizeString(value.story_model),
    role_model: normalizeString(value.role_model),
    shot_role_model: normalizeString(value.shot_role_model),
    camera_model: normalizeString(value.camera_model),
  };
}

function migrateLegacyTextModel(value: string): string {
  const normalized = normalizeString(value);
  return legacyTextModelAliases[normalized] ?? normalized;
}

function migrateLegacyImageModel(value: string): string {
  const normalized = normalizeString(value);
  return legacyImageModelAliases[normalized] ?? normalized;
}

function migrateLegacyTtsVoiceType(value: string): string {
  const normalized = normalizeString(value);
  const mapped = legacyTtsVoiceTypeAliases[normalized] ?? normalized;
  return mapped || DEFAULT_TTS_VOICE_TYPE;
}

function resolveVideoDurationRule(model: string): VideoDurationRule {
  const normalized = normalizeModelRuleKey(model);
  if (normalized.includes("seedance-2-0") || normalized.includes("seedance-2.0")) {
    return { min: 4, max: 15, allowAuto: true };
  }
  if (normalized.includes("seedance-1-5") || normalized.includes("seedance-1.5")) {
    return { min: 4, max: 12, allowAuto: true };
  }
  if (normalized.includes("seedance-1-0") || normalized.includes("seedance-1.0")) {
    return { min: 2, max: 12, allowAuto: false };
  }
  return { min: 2, max: 30, allowAuto: false };
}

function buildVideoDurationOptions(rule: VideoDurationRule): VideoDurationOption[] {
  const options: VideoDurationOption[] = [];
  if (rule.allowAuto) {
    options.push({ value: -1, label: "自动（-1，由模型选择）" });
  }
  for (let second = rule.min; second <= rule.max; second += 1) {
    options.push({ value: second, label: `${second} 秒` });
  }
  return options;
}

function normalizeVideoDurationForModel(value: unknown, model: string, fallback: number): number {
  return normalizeVideoDurationByRule(value, resolveVideoDurationRule(model || DEFAULT_VIDEO_MODEL_ID), fallback);
}

function normalizeVideoDurationByRule(value: unknown, rule: VideoDurationRule, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (Number.isFinite(parsed)) {
    const rounded = Math.round(parsed);
    if (isDurationAllowedByRule(rounded, rule)) {
      return rounded;
    }
  }
  if (isDurationAllowedByRule(fallback, rule)) {
    return fallback;
  }
  return rule.min;
}

function isDurationAllowedByRule(value: number, rule: VideoDurationRule): boolean {
  if (!Number.isInteger(value)) {
    return false;
  }
  if (rule.allowAuto && value === -1) {
    return true;
  }
  return value >= rule.min && value <= rule.max;
}

function normalizeModelRuleKey(value: string): string {
  return normalizeString(value).toLowerCase().replace(/_/g, "-");
}

function normalizeString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function clampInteger(value: unknown, min: number, max: number, fallback: number): number {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  const rounded = Math.round(numeric);
  return Math.min(max, Math.max(min, rounded));
}

function resolvePresetValue(currentValue: string, options: ModelOption[]): string {
  return options.some((option) => option.value === currentValue) ? currentValue : CUSTOM_VALUE;
}

function resolveMainTextPresetValue(currentValue: string): string {
  const normalized = normalizeString(currentValue);
  if (!normalized) {
    return CUSTOM_VALUE;
  }
  return resolvePresetValue(normalized, chatModelOptions);
}
</script>

<template>
  <div class="page-shell">
    <section class="hero-panel">
      <div class="hero-copy">
        <p class="eyebrow">Python + Vue</p>
        <h1>视频生成工作流</h1>
        <p class="hero-text">
          配置文本模型、图片模型和语音参数后，一键生成剧情、角色、分镜、首帧、视频与旁白。建议先在后端配置好 API Key，再在此页按需调整参数。
        </p>
      </div>
      <div class="hero-stats">
        <div class="stat-card">
          <span>当前阶段</span>
          <strong>{{ currentStageLabel }}</strong>
        </div>
        <div class="stat-card">
          <span>任务进度</span>
          <strong>{{ progressPercent }}%</strong>
        </div>
        <div class="stat-card">
          <span>旁白完成率</span>
          <strong>{{ completionRate }}%</strong>
        </div>
      </div>
    </section>

    <section class="workspace-grid">
      <aside class="history-sidebar">
        <article class="history-panel">
          <div class="history-panel-header">
            <h2>历史任务</h2>
            <button class="ghost-button" type="button" @click="loadHistoryRuns">刷新历史</button>
          </div>
          <p class="field-hint">点击某条历史任务会自动跳转到右侧详情区域。</p>
          <p v-if="historyError" class="error-banner">{{ historyError }}</p>
          <div v-else-if="isLoadingHistory" class="log-empty">正在加载历史任务...</div>
          <div v-else-if="!historyRuns.length" class="log-empty">暂无历史任务。</div>
          <div v-else class="history-list">
            <article
              v-for="item in historyRuns"
              :key="item.job_id"
              :class="['history-item', { active: selectedHistoryJobId === item.job_id }]"
              role="button"
              tabindex="0"
              @click="handleHistorySelect(item.job_id)"
              @keydown.enter.prevent="handleHistorySelect(item.job_id)"
              @keydown.space.prevent="handleHistorySelect(item.job_id)"
            >
              <div>
                <p class="history-title">{{ item.title }}</p>
                <p class="history-meta">{{ formatTimestamp(item.saved_at) }} · {{ item.job_id }}</p>
              </div>
              <div class="history-buttons">
                <button class="secondary-button" type="button" :disabled="isComposingHistoryVideo" @click.stop="composeHistoryVideo(item.job_id)">
                  {{ isComposingHistoryVideo ? "合成中..." : "合成视频(含字幕)" }}
                </button>
                <button class="secondary-button" type="button" :disabled="isDownloadingHistoryAssets" @click.stop="downloadHistoryAssets(item.job_id)">
                  {{ isDownloadingHistoryAssets ? "下载中..." : "下载 ZIP" }}
                </button>
              </div>
            </article>
          </div>
        </article>
      </aside>

      <form class="config-panel" @submit.prevent="handleSubmit">
        <div class="panel-header">
          <h2>运行配置</h2>
          <button class="ghost-button" type="button" @click="resetToDefault">重置</button>
        </div>

        <label class="field">
          <span>剧情原文</span>
          <textarea
            v-model="form.story_text"
            rows="8"
            placeholder="请输入剧情原文"
          />
        </label>

        <div class="section-title">豆包文本与图片</div>

        <label class="field">
          <span>Base URL</span>
          <input v-model="form.connection.base_url" type="text" />
        </label>

        <p class="field-hint">请在后端 <code>backend/.env</code> 中配置 API Key。该页面主要用于调整模型和运行参数。</p>

        <label class="field">
          <span>默认文本模型 ID</span>
          <select v-model="selectedTextModelPresets.default_model">
            <option v-for="option in chatModelOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <input
            v-if="selectedTextModelPresets.default_model === CUSTOM_VALUE"
            v-model="form.text_models.default_model"
            type="text"
            placeholder="请输入文本模型 ID（如 ep-...）"
          />
        </label>
        <p class="field-hint">
          若出现 <code>InvalidEndpointOrModel.NotFound</code>，通常表示模型 ID 不存在或当前账号无权限访问。
        </p>

        <details class="advanced-panel">
          <summary>高级配置：按阶段覆写文本模型</summary>
          <p class="field-hint advanced-hint">
            可按阶段单独指定模型；留空时将沿用“默认文本模型 ID”。
          </p>
          <div class="advanced-grid">
            <label v-for="field in textModelOverrideFields" :key="field.key" class="field">
              <span>{{ field.label }}</span>
              <select v-model="selectedTextModelPresets[field.key]">
                <option
                  v-for="option in overrideTextModelOptions"
                  :key="`${field.key}-${option.value}`"
                  :value="option.value"
                >
                  {{ option.label }}
                </option>
              </select>
              <input
                v-if="selectedTextModelPresets[field.key] === CUSTOM_VALUE"
                v-model="form.text_models[field.key]"
                type="text"
                placeholder="请输入模型 ID（如 ep-...）"
              />
              <span class="mini-hint">{{ field.hint }}</span>
            </label>
          </div>
        </details>

        <label class="field">
          <span>默认图片模型 ID</span>
          <select v-model="selectedImageModel">
            <option v-for="option in imageModelOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <input
            v-if="selectedImageModel === CUSTOM_VALUE"
            v-model="form.connection.image_model"
            type="text"
            placeholder="请输入图片模型 ID（如 ep-...）"
          />
        </label>
        <p class="field-hint">
          建议使用常见图片比例，例如 <code>2048x2048</code>、<code>2848x1600</code>、<code>1600x2848</code>。
        </p>

        <div class="field-row">
          <label class="field">
            <span>图片尺寸</span>
            <select v-model="selectedImageSize">
              <option v-for="option in imageSizeOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
            <input
              v-if="selectedImageSize === CUSTOM_VALUE"
              v-model="form.connection.image_size"
              type="text"
              placeholder="请输入图片尺寸（如 768x1152）"
            />
          </label>
          <label class="field">
            <span>最大角色图数</span>
            <input v-model.number="form.max_images" type="number" min="1" max="6" />
          </label>
        </div>

        <p class="field-hint">可根据需求调整图片尺寸与生成数量，数量越大通常耗时越长。</p>

        <div class="section-title">镜头视频生成</div>

        <label class="field">
          <span>视频模型 ID</span>
          <select v-model="selectedVideoModel">
            <option v-for="option in videoModelOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <input
            v-if="selectedVideoModel === CUSTOM_VALUE"
            v-model="form.connection.video_model"
            type="text"
            placeholder="请输入视频模型 ID（如 doubao-seedance-1-5-pro-251215）"
          />
        </label>

        <label class="field">
          <span>全局默认 N（新会话/重置默认）</span>
          <input
            v-model.number="globalDefaultStoryShotCount"
            type="number"
            :min="MIN_STORY_SHOT_COUNT"
            :max="MAX_STORY_SHOT_COUNT"
          />
        </label>

        <div class="field-row">
          <label class="field">
            <span>剧情节点/镜头总数（N）</span>
            <input
              v-model.number="form.connection.story_shot_count"
              type="number"
              :min="MIN_STORY_SHOT_COUNT"
              :max="MAX_STORY_SHOT_COUNT"
            />
          </label>
          <label class="field">
            <span>生成视频镜头数量</span>
            <input v-model.number="form.connection.video_max_shots" type="number" min="0" :max="effectiveStoryShotCount" />
          </label>
          <label class="field">
            <span>每个镜头时长（秒）</span>
            <select v-model.number="form.connection.video_duration_seconds">
              <option
                v-for="option in videoDurationOptions"
                :key="`video-duration-${option.value}`"
                :value="option.value"
              >
                {{ option.label }}
              </option>
            </select>
            <span class="mini-hint">{{ videoDurationHint }}</span>
          </label>
        </div>

        <p class="field-hint">全局默认 N 会保存在浏览器本地；N 控制源头剧情与分镜数量，生成视频镜头数量设为 0 则仅生成首帧图。</p>

        <div class="section-title tts-head">
          <span>语音（TTS）配置</span>
          <div class="field-row">
            <label class="toggle">
              <input v-model="form.tts.enabled" type="checkbox" />
              <span>启用</span>
            </label>
            <label class="toggle">
              <input v-model="form.tts.remove_role_names" type="checkbox" />
              <span>旁白去角色名</span>
            </label>
          </div>
        </div>

        <p class="field-hint">
          请在后端 <code>backend/.env</code> 中配置 TTS 所需的 <code>App ID</code> 与 <code>Access Token</code>。
        </p>

        <div class="field-row">
          <label class="field">
            <span>Cluster</span>
            <input v-model="form.tts.cluster" type="text" />
          </label>
          <label class="field">
            <span>Voice Type</span>
            <select v-model="selectedTtsVoice">
              <option v-for="option in ttsVoiceOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
            <input
              v-if="selectedTtsVoice === CUSTOM_VALUE"
              v-model="form.tts.voice_type"
              type="text"
              placeholder="请输入 Voice Type（如 BV003_streaming）"
            />
          </label>
        </div>

        <div class="field-row">
          <label class="field">
            <span>TTS Endpoint</span>
            <input v-model="form.tts.endpoint" type="text" />
          </label>
          <label class="field">
            <span>语速</span>
            <input v-model.number="form.tts.speed" type="number" min="0.2" max="3" step="0.1" />
          </label>
        </div>

        <label class="field">
          <span>TTS 试听文案</span>
          <input v-model="voiceTestText" type="text" placeholder="请输入试听文案" />
        </label>

        <div class="action-row">
          <button class="secondary-button" type="button" :disabled="isTestingVoice" @click="handleTestVoiceType">
            {{ isTestingVoice ? "试听中..." : "试听声音" }}
          </button>
        </div>
        <p v-if="voiceTestMessage" class="field-hint">{{ voiceTestMessage }}</p>
        <audio v-if="voiceTestAudioUrl" :src="voiceTestAudioUrl" controls preload="none" />

        <div class="section-title tts-head" style="margin-top: 8px">
          <span>字幕</span>
          <label class="toggle">
            <input v-model="form.subtitle_enabled" type="checkbox" />
            <span>启用字幕</span>
          </label>
        </div>
        <p class="field-hint">
          启用后将为每个镜头生成 SRT 字幕（依赖 TTS 旁白音频），字幕会烧录到合成视频中。
        </p>

        <div class="action-stack">
          <button class="run-button" type="submit" :disabled="isRunning || isCancelling">
            {{ isCancelling ? "取消中..." : isRunning ? "运行中..." : "开始运行" }}
          </button>
          <button
            v-if="canCancel"
            class="danger-button"
            type="button"
            :disabled="isCancelling"
            @click="handleCancel"
          >
            {{ isCancelling ? "取消中..." : "取消任务" }}
          </button>
        </div>

        <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
      </form>

      <section ref="resultPanelRef" class="result-panel">
        <article class="result-card progress-card">
          <div class="card-title-row">
            <h3>任务进度</h3>
            <span v-if="jobStatus">{{ progressPercent }}%</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${progressPercent}%` }" />
          </div>
          <p class="progress-stage">{{ currentStageLabel }}</p>
          <p class="progress-message">{{ currentMessage }}</p>
          <p v-if="jobStatus?.job_id" class="job-id">任务 ID：{{ jobStatus.job_id }}</p>
        </article>

        <article class="result-card log-card">
          <div class="card-title-row">
            <h3>运行日志</h3>
            <span>{{ logs.length }} 条</span>
          </div>
          <div v-if="logs.length" class="log-list">
            <div v-for="entry in logs" :key="`${entry.timestamp}-${entry.message}`" class="log-item">
              <div class="log-head">
                <span class="log-time">{{ formatTimestamp(entry.timestamp) }}</span>
                <span class="log-stage">{{ stageLabels[entry.stage] ?? entry.stage }}</span>
              </div>
              <p :class="['log-message', `log-${entry.level}`]">{{ entry.message }}</p>
            </div>
          </div>
          <div v-else class="log-empty">暂无日志，任务启动后会在这里显示。</div>
        </article>

        <div v-if="result" class="action-row">
          <button class="secondary-button" type="button" @click="exportResultJson">导出结果 JSON</button>
          <button class="secondary-button" type="button" :disabled="isDownloadingAssets" @click="exportAssetsZip">
            {{ isDownloadingAssets ? "下载中..." : "下载 ZIP" }}
          </button>
        </div>

        <div v-if="!result" class="empty-state">
          <h2>还没有结果</h2>
          <p>右侧会展示标题、剧情节点、角色信息、首帧图片、镜头视频与旁白音频。</p>
        </div>

        <template v-else>
          <article class="result-card title-card">
            <p class="card-tag">标题</p>
            <h2>{{ result.title }}</h2>
          </article>

          <article class="result-card">
            <div class="card-title-row">
              <h3>剧情节点</h3>
              <span>{{ result.key_highlights.length }} 条</span>
            </div>
            <ol class="timeline-list">
              <li v-for="highlight in result.key_highlights" :key="highlight">{{ highlight }}</li>
            </ol>
          </article>

          <article v-if="result.warnings.length" class="result-card warning-card">
              <h3>警告信息</h3>
            <ul class="warning-list">
              <li v-for="warning in result.warnings" :key="warning">{{ warning }}</li>
            </ul>
          </article>

          <article class="result-card">
            <h3>角色设定与原型图</h3>
            <div class="role-grid">
              <div
                v-for="description in result.description_list"
                :key="description.name"
                class="role-card"
              >
                <img
                  v-if="roleImageMap.get(description.name)"
                  :src="roleImageMap.get(description.name)"
                  :alt="description.name"
                  class="role-image"
                />
                <div class="role-meta">
                  <h4>{{ description.name }}</h4>
                  <p>{{ description.gender }} 路 {{ description.age }}</p>
                  <p>{{ description.appearance }}</p>
                  <p>{{ description.outfit }}</p>
                  <p>{{ description.mood }}</p>
                </div>
              </div>
            </div>
          </article>

          <article class="result-card">
            <h3>镜头拆解</h3>
            <div class="shot-list">
              <section v-for="shot in result.shots" :key="shot.index" class="shot-card">
                <div class="shot-index">镜头 {{ shot.index }}</div>
                <p class="shot-highlight">{{ shot.highlight }}</p>
                <p class="shot-note">{{ shot.scene_note }}</p>
                <div class="chip-row">
                  <span v-for="role in shot.roles_in_shot" :key="role" class="chip">{{ role }}</span>
                </div>
                <p class="shot-prompt">{{ shot.camera_prompt }}</p>
                <p v-if="shot.first_frame_prompt" class="shot-prompt">首帧提示词：{{ shot.first_frame_prompt }}</p>
                <div class="audio-block">
                  <span>旁白文案：{{ shot.narration_text }}</span>
                  <audio v-if="shot.narration_audio_url" :src="shot.narration_audio_url" controls preload="none" />
                </div>
                <details v-if="shot.subtitle_srt" class="subtitle-details">
                  <summary>字幕 (SRT)</summary>
                  <pre class="subtitle-preview">{{ shot.subtitle_srt }}</pre>
                </details>
                <div v-if="shot.first_frame_url" class="video-block">
                  <span>首帧图片</span>
                  <img :src="shot.first_frame_url" :alt="`Shot ${shot.index} first frame`" class="shot-video" />
                </div>
                <div v-if="shot.shot_video_url" class="video-block">
                  <span>镜头视频</span>
                  <video :src="shot.shot_video_url" controls preload="metadata" class="shot-video" />
                </div>
                <div v-if="shot.ref_urls.length" class="thumb-row">
                  <img v-for="url in shot.ref_urls" :key="url" :src="url" alt="参考图" class="thumb" />
                </div>
              </section>
            </div>
          </article>
        </template>
      </section>
    </section>
  </div>
</template>



