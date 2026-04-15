from app.services.helpers import (
    clean_narration_text,
    extract_json_payload,
    is_sensitive_image_error,
    is_tts_permission_error,
    soften_image_prompt,
)


def test_clean_narration_text_removes_parentheses() -> None:
    text = "书生（张生）深夜翻出旧书，心里又怕又急"
    assert clean_narration_text(text) == "书生深夜翻出旧书，心里又怕又急"


def test_extract_json_payload_accepts_code_fence() -> None:
    payload = extract_json_payload("```json\n{\"title\": \"示例\"}\n```")
    assert payload == {"title": "示例"}


def test_is_sensitive_image_error_detects_moderation_code() -> None:
    assert is_sensitive_image_error("OutputImageSensitiveContentDetected")


def test_is_tts_permission_error_detects_resource_not_granted() -> None:
    assert is_tts_permission_error(
        'Failed during speech synthesis: 403 {"code":3001,"message":"[resource_id=volc.tts.default] requested resource not granted"}'
    )


def test_soften_image_prompt_rewrites_risky_old_monk_prompt() -> None:
    softened = soften_image_prompt(
        "百岁枯瘦老僧，光头皱纹深刻，穿灰色破旧补丁僧袍，枯坐废弃仙寺阴暗角落，周围昏暗，仅微弱光线照亮身影",
        "枯坐老僧",
    )
    assert "枯瘦" not in softened
    assert "阴暗角落" not in softened
    assert "全年龄向" in softened

