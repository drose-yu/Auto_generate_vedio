import json
import re
from typing import Any


def extract_json_payload(raw_text: str) -> Any:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Model returned empty content.")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    for candidate in (text, _slice_json_candidate(text, "{", "}"), _slice_json_candidate(text, "[", "]")):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError("Unable to parse JSON payload from model response.")


def _slice_json_candidate(text: str, opening: str, closing: str) -> str | None:
    start = text.find(opening)
    end = text.rfind(closing)
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def clean_narration_text(text: str) -> str:
    cleaned = re.sub(r"[\(（].*?[\)）]", "", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def is_sensitive_image_error(message: str) -> bool:
    normalized = (message or "").lower()
    return "outputimagesensitivecontentdetected" in normalized


def is_tts_permission_error(message: str) -> bool:
    normalized = (message or "").lower()
    return "requested resource not granted" in normalized or "resource not granted" in normalized


def soften_image_prompt(prompt: str, role_name: str | None = None) -> str:
    softened = (prompt or "").strip()
    replacements = [
        (r"百岁枯瘦老僧", "年长僧人"),
        (r"枯坐老僧", "静坐长者僧人"),
        (r"枯瘦", "清癯"),
        (r"干瘪", "清瘦"),
        (r"皱纹深刻如沟壑", "面容有岁月痕迹"),
        (r"皱纹深刻", "面容沉稳"),
        (r"灰色破旧补丁僧袍", "朴素灰色僧袍"),
        (r"破旧补丁僧袍", "朴素僧袍"),
        (r"废弃仙寺阴暗角落", "古寺禅房一角"),
        (r"阴暗角落", "禅房一角"),
        (r"周围昏暗，仅微弱光线照亮身影", "暖色自然光洒落其身侧"),
        (r"昏暗", "安静"),
        (r"阴暗", "宁静"),
        (r"破旧", "古朴"),
        (r"高深莫测无喜怒", "平和沉稳"),
    ]
    for pattern, replacement in replacements:
        softened = re.sub(pattern, replacement, softened)

    if "全年龄向" not in softened:
        softened = f"{softened}，庄重平和，暖色自然光，全年龄向"
    if role_name and role_name in {"枯坐老僧", "老僧"} and "年长僧人" not in softened:
        softened = f"年长僧人，{softened}"

    softened = re.sub(r"\s+", " ", softened).strip("，, ")
    return softened

