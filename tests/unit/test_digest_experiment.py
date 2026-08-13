import pytest
from prompts.builders import build_digest_prompt
from tg_bot.keyboards.assessment import get_assessment_keyboard, get_feedback_keyboard
from models.digest_assessment import DigestAssessment


def test_build_digest_prompt_variants():
    facts_text = "• Fact 1 [Источник](http://example.com)\n• Fact 2"

    micro_prompt = build_digest_prompt(facts_text, digest_type="simple", format_variant="micro_tldr")
    assert "MICRO TL;DR" in micro_prompt
    assert "ультра-короткого" in micro_prompt

    tldr_plus_prompt = build_digest_prompt(facts_text, digest_type="simple", format_variant="tldr_plus_highlights")
    assert "TL;DR + HIGHLIGHTS" in tldr_plus_prompt
    assert "Главное за день" in tldr_plus_prompt

    bullet_feed_prompt = build_digest_prompt(facts_text, digest_type="simple", format_variant="bullet_feed")
    assert "BULLET FEED" in bullet_feed_prompt
    assert "плоский список" in bullet_feed_prompt

    standard_prompt = build_digest_prompt(facts_text, digest_type="simple", format_variant="standard_grouped")
    assert "шеф-редактор популярного издания" in standard_prompt

    # Test format_variant embedded in digest_type "simple:micro_tldr"
    embedded_prompt = build_digest_prompt(facts_text, digest_type="simple:micro_tldr")
    assert "MICRO TL;DR" in embedded_prompt


def test_get_assessment_keyboard():
    kb = get_assessment_keyboard(digest_id=10, format_variant="micro_tldr")
    assert len(kb.inline_keyboard) == 1
    assert len(kb.inline_keyboard[0]) == 5
    assert kb.inline_keyboard[0][0].text == "⭐ 1"
    assert kb.inline_keyboard[0][0].callback_data == "assess_vote:10:micro_tldr:1"
    assert kb.inline_keyboard[0][4].text == "⭐ 5"
    assert kb.inline_keyboard[0][4].callback_data == "assess_vote:10:micro_tldr:5"

    kb_voted = get_assessment_keyboard(digest_id=10, format_variant="micro_tldr", selected_rating=4)
    assert len(kb_voted.inline_keyboard) == 1
    assert "Ваша оценка: ⭐⭐⭐⭐ (4/5)" in kb_voted.inline_keyboard[0][0].text


def test_get_feedback_keyboard():
    kb = get_feedback_keyboard()
    assert len(kb.inline_keyboard) == 2
    assert "Оставить комментарий" in kb.inline_keyboard[0][0].text
    assert kb.inline_keyboard[0][0].callback_data == "assess_comment_prompt"
    assert "Завершить" in kb.inline_keyboard[1][0].text
    assert kb.inline_keyboard[1][0].callback_data == "assess_finish"


def test_digest_assessment_model_instantiation():
    assessment = DigestAssessment(
        user_id=1,
        digest_id=10,
        format_variant="micro_tldr",
        rating=5,
        comment="Отличный короткий формат!"
    )
    assert assessment.user_id == 1
    assert assessment.digest_id == 10
    assert assessment.format_variant == "micro_tldr"
    assert assessment.rating == 5
    assert assessment.comment == "Отличный короткий формат!"
