import pytest
from tg_bot.publisher import markdown_to_html, split_text
from parser.llm_layer import MessageExtractor


def test_markdown_to_html_formatting():
    raw_md = "### Заголовок\n**Жирный текст** и *курсив* и `код` и [Ссылка](https://example.com)"
    html = markdown_to_html(raw_md)
    
    assert "<b>Заголовок</b>" in html
    assert "<b>Жирный текст</b>" in html
    assert "<i>курсив</i>" in html
    assert "<code>код</code>" in html
    assert '<a href="https://example.com">Ссылка</a>' in html


def test_split_text_long_content():
    long_text = ("Строка текста для проверки нарезки.\n" * 200)
    chunks = split_text(long_text, limit=1000)
    
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1000


def test_deep_clean():
    extractor = MessageExtractor(
        model_names=["deepseek/deepseek-v4-pro"],
        api_keys=["fake-key"],
        proxy=""
    )
    
    dirty_data = {
        "text": "Привет\x00 Мир\t\n",
        "nested": ["Тест\x07"]
    }
    cleaned = extractor._deep_clean(dirty_data)
    assert cleaned["text"] == "Привет Мир"
    assert cleaned["nested"] == ["Тест"]


def test_build_digest_prompt_cta_presence():
    extractor = MessageExtractor(
        model_names=["deepseek/deepseek-v4-pro"],
        api_keys=["fake-key"],
        proxy=""
    )
    
    facts_text = "• Fact 1\n• Fact 2"
    
    # Mon-Sat prompt: should NOT invite to quiz
    weekday_prompt = extractor.build_message_extraction_prompt(
        text=facts_text,
        digest=True,
        has_quiz=False
    )
    assert "пройти квиз" not in weekday_prompt
    
    # Sunday prompt: SHOULD invite to quiz
    sunday_prompt = extractor.build_message_extraction_prompt(
        text=facts_text,
        digest=True,
        has_quiz=True
    )
    assert "пройти квиз для проверки знаний" in sunday_prompt


def test_build_weekly_quiz_selection_prompt():
    extractor = MessageExtractor(
        model_names=["deepseek/deepseek-v4-pro"],
        api_keys=["fake-key"],
        proxy=""
    )
    
    candidate_questions = [
        {
            "question": "Как работает HLA?",
            "options": ["Opt 1", "Opt 2", "Opt 3", "Opt 4"],
            "correct_answer": "Opt 1",
            "explanation": "Объяснение",
            "difficulty_level": "hard"
        }
    ]
    
    prompt = extractor.build_weekly_quiz_selection_prompt(candidate_questions)
    assert "Как работает HLA?" in prompt
    assert "ОТБОРА И ФОРМИРОВАНИЯ" in prompt
