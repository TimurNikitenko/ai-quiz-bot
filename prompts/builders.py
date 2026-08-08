"""Функции формирования готовых промптов для LLM."""

import json
from typing import List, Dict, Any
from .templates import (
    POST_PROMPT_TEMPLATE,
    DIGEST_ASSEMBLY_PROMPT_TEMPLATE,
    SIMPLE_DIGEST_ASSEMBLY_PROMPT_TEMPLATE,
    WEEKLY_QUIZ_SELECTION_PROMPT,
)


def build_post_analysis_prompt(text: str) -> str:
    """Формирует промпт анализа сырого поста."""
    return POST_PROMPT_TEMPLATE.format(post_text=text)


def build_digest_prompt(facts_text: str, digest_type: str = "tech") -> str:
    """Формирует промпт сборки дайджеста (tech или simple)."""
    if digest_type == "simple":
        return SIMPLE_DIGEST_ASSEMBLY_PROMPT_TEMPLATE.format(raw_facts=facts_text)
    return DIGEST_ASSEMBLY_PROMPT_TEMPLATE.format(raw_facts=facts_text)


def build_weekly_quiz_prompt(candidate_questions: List[Dict[str, Any]]) -> str:
    """Формирует промпт отбора еженедельного квиза."""
    formatted_questions = json.dumps(candidate_questions, ensure_ascii=False, indent=2)
    return WEEKLY_QUIZ_SELECTION_PROMPT.format(candidate_questions=formatted_questions)
