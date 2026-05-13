export const STORAGE_KEY = "doubao-workflow-config";
export const GLOBAL_DEFAULTS_KEY = "doubao-workflow-global-defaults";
export const STORAGE_VERSION = 6;
export const POLL_INTERVAL_MS = 1500;
export const CUSTOM_VALUE = "__custom__";
export const DEFAULT_TEXT_ENDPOINT = "";
export const DEFAULT_IMAGE_ENDPOINT = "ep-20260413162910-d72lb";
export const DEFAULT_TTS_VOICE_TYPE = "BV700_streaming";
export const DEFAULT_VIDEO_MODEL_ID = "doubao-seedance-1-5-pro-251215";
export const REMOVED_TEXT_ENDPOINT = "ep-m-202512011114108-wlrg5";
export const LEGACY_IMAGE_SIZE_VALUES = new Set(["576x1024", "1024x576", "1024x1024", "864x1152", "1152x864"]);
export const MIN_STORY_SHOT_COUNT = 1;
export const MAX_STORY_SHOT_COUNT = 20;
export const DEFAULT_STORY_SHOT_COUNT = 8;

export type ModelOption = {
  label: string;
  value: string;
};

export type VideoDurationRule = {
  min: number;
  max: number;
  allowAuto: boolean;
};

export type VideoDurationOption = {
  label: string;
  value: number;
};

export const PROJECT_TEXT_ENDPOINT_OPTIONS: ModelOption[] = [
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

export const TEXT_MODEL_KEYS = [
  "default_model",
  "story_model",
  "role_model",
  "shot_role_model",
  "camera_model",
] as const;

export type TextModelKey = (typeof TEXT_MODEL_KEYS)[number];

export const textModelOverrideFields: Array<{
  key: Exclude<TextModelKey, "default_model">;
  label: string;
  hint: string;
}> = [
  { key: "story_model", label: "剧情模型", hint: "用于生成剧情文本。" },
  { key: "role_model", label: "角色模型", hint: "用于生成角色设定。" },
  { key: "shot_role_model", label: "镜头角色模型", hint: "用于生成分镜中的角色描述。" },
  { key: "camera_model", label: "分镜模型", hint: "用于生成镜头脚本和分镜信息。" },
];

export const chatModelOptions: ModelOption[] = [
  { label: "默认（使用后端配置）", value: "" },
  ...PROJECT_TEXT_ENDPOINT_OPTIONS,
  { label: "Doubao-Seed-2.0-pro | doubao-seed-2-0-pro", value: "doubao-seed-2-0-pro" },
  { label: "Doubao-Seed-2.0-lite | doubao-seed-2-0-lite", value: "doubao-seed-2-0-lite" },
  { label: "Doubao-Seed-2.0-mini | doubao-seed-2-0-mini", value: "doubao-seed-2-0-mini" },
  { label: "DeepSeek-V3.2 | deepseek-v3-2", value: "deepseek-v3-2" },
  { label: "DeepSeek-R1 | deepseek-r1", value: "deepseek-r1" },
  { label: "自定义模型 ID", value: CUSTOM_VALUE },
];

export const overrideTextModelOptions: ModelOption[] = [
  { label: "跟随默认模型", value: "" },
  ...chatModelOptions.filter((option) => option.value !== ""),
];

export const imageModelOptions: ModelOption[] = [
  { label: "默认（使用后端配置）", value: "" },
  { label: `默认图片模型 | ${DEFAULT_IMAGE_ENDPOINT}`, value: DEFAULT_IMAGE_ENDPOINT },
  { label: "Doubao-Seedream-5.0-lite | doubao-seedream-5-0", value: "doubao-seedream-5-0" },
  { label: "Doubao-Seedream-4.5 | doubao-seedream-4-5", value: "doubao-seedream-4-5" },
  { label: "Doubao-Seedream-4.0 | doubao-seedream-4-0", value: "doubao-seedream-4-0" },
  { label: "自定义图片模型 ID", value: CUSTOM_VALUE },
];

export const videoModelOptions: ModelOption[] = [
  { label: "默认（使用后端配置）", value: "" },
  { label: "Doubao-Seedance-2.0 | doubao-seedance-2-0", value: "doubao-seedance-2-0" },
  { label: "Doubao-Seedance-2.0-fast | doubao-seedance-2-0-fast", value: "doubao-seedance-2-0-fast" },
  { label: "Doubao-Seedance-1.5-pro-251215 | doubao-seedance-1-5-pro-251215", value: "doubao-seedance-1-5-pro-251215" },
  { label: "Doubao-Seedance-1.0-pro | doubao-seedance-1-0-pro", value: "doubao-seedance-1-0-pro" },
  { label: "Doubao-Seedance-1.0-pro-fast | doubao-seedance-1-0-pro-fast", value: "doubao-seedance-1-0-pro-fast" },
  { label: "Doubao-Seedance-1.0-lite(t2v) | doubao-seedance-1-0-lite-t2v", value: "doubao-seedance-1-0-lite-t2v" },
  { label: "Doubao-Seedance-1.0-lite(i2v) | doubao-seedance-1-0-lite-i2v", value: "doubao-seedance-1-0-lite-i2v" },
  { label: "自定义视频模型 ID", value: CUSTOM_VALUE },
];

export const imageSizeOptions: ModelOption[] = [
  { label: "2048 x 2048", value: "2048x2048" },
  { label: "2848 x 1600", value: "2848x1600" },
  { label: "1600 x 2848", value: "1600x2848" },
  { label: "自定义尺寸", value: CUSTOM_VALUE },
];

export const ttsVoiceOptions: ModelOption[] = [
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

export const stageLabels: Record<string, string> = {
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

export const legacyTextModelAliases: Record<string, string> = {
  "doubao-seed-character": "",
  [REMOVED_TEXT_ENDPOINT]: "",
};

export const legacyImageModelAliases: Record<string, string> = {
  "doubao-seedream-3-0-t2i": DEFAULT_IMAGE_ENDPOINT,
};

export const legacyTtsVoiceTypeAliases: Record<string, string> = {
  BV113_streaming: DEFAULT_TTS_VOICE_TYPE,
};
