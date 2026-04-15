import pytest
from pydantic import ValidationError

from app.models.schemas import DoubaoConnectionConfig


def test_image_size_accepts_documented_pixel_value() -> None:
    config = DoubaoConnectionConfig(chat_model="ep-test", image_size="2048x2048")
    assert config.image_size == "2048x2048"


def test_image_size_rejects_legacy_invalid_pixel_value() -> None:
    with pytest.raises(ValidationError):
        DoubaoConnectionConfig(chat_model="ep-test", image_size="576x1024")


def test_video_model_1_0_fast_keeps_current_value() -> None:
    config = DoubaoConnectionConfig(chat_model="ep-test", video_model="doubao-seedance-1-0-pro-fast")
    assert config.video_model == "doubao-seedance-1-0-pro-fast"


def test_video_model_legacy_full_alias_is_migrated_to_new_model() -> None:
    config = DoubaoConnectionConfig(chat_model="ep-test", video_model="doubao-seedance-1-0-pro-fast-251015")
    assert config.video_model == "doubao-seedance-1-5-pro-251215"


def test_video_duration_allows_auto_for_seedance_2_0() -> None:
    config = DoubaoConnectionConfig(
        chat_model="ep-test",
        video_model="doubao-seedance-2-0-fast",
        video_duration_seconds=-1,
    )
    assert config.video_duration_seconds == -1


def test_video_duration_allows_auto_for_seedance_1_5() -> None:
    config = DoubaoConnectionConfig(
        chat_model="ep-test",
        video_model="doubao-seedance-1-5-pro-251215",
        video_duration_seconds=-1,
    )
    assert config.video_duration_seconds == -1


def test_video_duration_rejects_auto_for_seedance_1_0() -> None:
    with pytest.raises(ValidationError):
        DoubaoConnectionConfig(
            chat_model="ep-test",
            video_model="doubao-seedance-1-0-pro-fast",
            video_duration_seconds=-1,
        )


def test_video_duration_rejects_out_of_range_for_seedance_2_0() -> None:
    with pytest.raises(ValidationError):
        DoubaoConnectionConfig(
            chat_model="ep-test",
            video_model="doubao-seedance-2-0",
            video_duration_seconds=3,
        )


def test_story_shot_count_accepts_dynamic_range() -> None:
    config = DoubaoConnectionConfig(
        chat_model="ep-test",
        story_shot_count=12,
        video_max_shots=10,
    )
    assert config.story_shot_count == 12
    assert config.video_max_shots == 10


def test_story_shot_count_rejects_value_below_min() -> None:
    with pytest.raises(ValidationError):
        DoubaoConnectionConfig(
            chat_model="ep-test",
            story_shot_count=0,
        )


def test_video_max_shots_rejects_when_exceeding_story_shot_count() -> None:
    with pytest.raises(ValidationError):
        DoubaoConnectionConfig(
            chat_model="ep-test",
            story_shot_count=5,
            video_max_shots=6,
        )
