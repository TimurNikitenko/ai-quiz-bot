import os
from datetime import datetime, timezone, timedelta
from utils.text_helpers import split_text, markdown_to_html, deep_clean
from utils.time_utils import get_moscow_now, get_seven_days_ago, get_cutoff_time
from utils.media_helpers import extract_valid_media_paths
from schemas.llm_schemas import to_strict_json_schema, PostAnalysisSchema, WeeklyQuizSchema
from prompts.builders import build_post_analysis_prompt, build_digest_prompt, build_weekly_quiz_prompt


def test_text_helpers_split_text():
    text = "Line 1\nLine 2\nLine 3\nLine 4"
    chunks = split_text(text, limit=15)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 15


def test_text_helpers_markdown_to_html():
    md = "### Header\n**Bold** text with [Link](https://example.com) and `code`."
    html_out = markdown_to_html(md)
    assert "<b>Header</b>" in html_out
    assert "<b>Bold</b>" in html_out
    assert '<a href="https://example.com">Link</a>' in html_out
    assert "<code>code</code>" in html_out


def test_text_helpers_deep_clean():
    dirty_data = {"key": "  test\nvalue\x00  ", "list": [" item1 "]}
    cleaned = deep_clean(dirty_data)
    assert cleaned["key"] == "test\nvalue"
    assert cleaned["list"] == ["item1"]


def test_time_utils():
    now_msk = get_moscow_now()
    assert now_msk.tzinfo is not None

    seven_days = get_seven_days_ago()
    diff_seconds = abs((now_msk - seven_days).total_seconds() - 7 * 86400)
    assert diff_seconds < 5.0

    cutoff_default = get_cutoff_time()
    assert cutoff_default.tzinfo is not None

    custom_pub_date = datetime.now(timezone.utc) - timedelta(hours=5)
    cutoff_pub = get_cutoff_time(custom_pub_date)
    assert cutoff_pub == custom_pub_date


def test_strict_mode_schema_transformer():
    raw_schema = PostAnalysisSchema.model_json_schema()
    strict_schema = to_strict_json_schema(raw_schema)

    assert strict_schema["additionalProperties"] is False
    assert "required" in strict_schema
    assert set(strict_schema["properties"].keys()) == set(strict_schema["required"])

    # Check nested QuestionSchema object in $defs
    question_def = strict_schema["$defs"]["QuestionSchema"]
    assert question_def["additionalProperties"] is False
    assert "required" in question_def
    assert set(question_def["properties"].keys()) == set(question_def["required"])


def test_prompt_builders():
    post_prompt = build_post_analysis_prompt("Новость про ИИ")
    assert "Новость про ИИ" in post_prompt

    tech_digest = build_digest_prompt("Факты", digest_type="tech")
    assert "главный редактор IT-канала" in tech_digest

    simple_digest = build_digest_prompt("Факты", digest_type="simple")
    assert "шеф-редактор популярного издания" in simple_digest

    quiz_prompt = build_weekly_quiz_prompt([{"question": "Тест?"}])
    assert "Тест?" in quiz_prompt
