import type { ModelOption, VideoDurationOption, VideoDurationRule } from "../lib/constants";

export function normalizeString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function clampInteger(value: unknown, min: number, max: number, fallback: number): number {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  const rounded = Math.round(numeric);
  return Math.min(max, Math.max(min, rounded));
}

export function formatTimestamp(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function resolvePresetValue(currentValue: string, options: ModelOption[]): string {
  return options.some((option) => option.value === currentValue) ? currentValue : "__custom__";
}

export function resolveMainTextPresetValue(currentValue: string, options: ModelOption[]): string {
  const normalized = normalizeString(currentValue);
  if (!normalized) {
    return "__custom__";
  }
  return resolvePresetValue(normalized, options);
}

export function normalizeModelRuleKey(value: string): string {
  return normalizeString(value).toLowerCase().replace(/_/g, "-");
}

export function resolveVideoDurationRule(model: string): VideoDurationRule {
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

export function buildVideoDurationOptions(rule: VideoDurationRule): VideoDurationOption[] {
  const options: VideoDurationOption[] = [];
  if (rule.allowAuto) {
    options.push({ value: -1, label: "自动（-1，由模型选择）" });
  }
  for (let second = rule.min; second <= rule.max; second += 1) {
    options.push({ value: second, label: `${second} 秒` });
  }
  return options;
}

export function isDurationAllowedByRule(value: number, rule: VideoDurationRule): boolean {
  if (!Number.isInteger(value)) {
    return false;
  }
  if (rule.allowAuto && value === -1) {
    return true;
  }
  return value >= rule.min && value <= rule.max;
}

export function normalizeVideoDurationByRule(
  value: unknown,
  rule: VideoDurationRule,
  fallback: number,
): number {
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

export function normalizeVideoDurationForModel(
  value: unknown,
  model: string,
  fallback: number,
  defaultVideoModelId: string,
): number {
  return normalizeVideoDurationByRule(
    value,
    resolveVideoDurationRule(model || defaultVideoModelId),
    fallback,
  );
}

export function saveBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}
