"""Функции формирования готовых промптов для LLM."""

import json
from typing import List, Dict, Any
from .templates import (
    POST_PROMPT_TEMPLATE,
    DIGEST_ASSEMBLY_PROMPT_TEMPLATE,
    SIMPLE_DIGEST_ASSEMBLY_PROMPT_TEMPLATE,
    SIMPLE_DIGEST_MICRO_TLDR_TEMPLATE,
    SIMPLE_DIGEST_TLDR_PLUS_TEMPLATE,
    SIMPLE_DIGEST_BULLET_FEED_TEMPLATE,
    WEEKLY_QUIZ_SELECTION_PROMPT,
)


def build_post_analysis_prompt(text: str) -> str:
    """Формирует промпт анализа сырого поста."""
    return POST_PROMPT_TEMPLATE.format(post_text=text)


def build_digest_prompt(facts_text: str, digest_type: str = "tech", format_variant: str = "standard_grouped") -> str:
    """Формирует промпт сборки дайджеста (tech или различные варианты simple)."""
    if digest_type.startswith("simple"):
        if format_variant == "micro_tldr" or digest_type == "simple:micro_tldr":
            return SIMPLE_DIGEST_MICRO_TLDR_TEMPLATE.format(raw_facts=facts_text)
        elif format_variant == "tldr_plus_highlights" or digest_type == "simple:tldr_plus_highlights":
            return SIMPLE_DIGEST_TLDR_PLUS_TEMPLATE.format(raw_facts=facts_text)
        elif format_variant == "bullet_feed" or digest_type == "simple:bullet_feed":
            return SIMPLE_DIGEST_BULLET_FEED_TEMPLATE.format(raw_facts=facts_text)
        return SIMPLE_DIGEST_ASSEMBLY_PROMPT_TEMPLATE.format(raw_facts=facts_text)
    return DIGEST_ASSEMBLY_PROMPT_TEMPLATE.format(raw_facts=facts_text)


def build_weekly_quiz_prompt(candidate_questions: List[Dict[str, Any]]) -> str:
    """Формирует промпт отбора еженедельного квиза."""
    formatted_questions = json.dumps(candidate_questions, ensure_ascii=False, indent=2)
    return WEEKLY_QUIZ_SELECTION_PROMPT.format(candidate_questions=formatted_questions)
