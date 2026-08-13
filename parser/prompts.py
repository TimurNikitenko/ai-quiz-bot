"""Модуль промптов и схем (проксирует пакеты schemas и prompts)."""

from schemas.llm_schemas import PostAnalysisSchema, WeeklyQuizSchema
from prompts.templates import (
    POST_PROMPT_TEMPLATE as post_prompt_template,
    DIGEST_ASSEMBLY_PROMPT_TEMPLATE as digest_assembly_prompt_template,
    SIMPLE_DIGEST_ASSEMBLY_PROMPT_TEMPLATE as simple_digest_assembly_prompt_template,
    SIMPLE_DIGEST_MICRO_TLDR_TEMPLATE as simple_digest_micro_tldr_template,
    SIMPLE_DIGEST_TLDR_PLUS_TEMPLATE as simple_digest_tldr_plus_template,
    SIMPLE_DIGEST_BULLET_FEED_TEMPLATE as simple_digest_bullet_feed_template,
    WEEKLY_QUIZ_SELECTION_PROMPT as weekly_quiz_selection_prompt,
)
from prompts.builders import (
    build_post_analysis_prompt,
    build_digest_prompt,
    build_weekly_quiz_prompt,
)

post_schema = PostAnalysisSchema.to_dict_schema()
weekly_quiz_selection_schema = WeeklyQuizSchema.to_dict_schema()
digest_assembly_prompt = digest_assembly_prompt_template.format(raw_facts="{raw_facts}")

__all__ = [
    "post_prompt_template",
    "digest_assembly_prompt_template",
    "simple_digest_assembly_prompt_template",
    "weekly_quiz_selection_prompt",
    "post_schema",
    "weekly_quiz_selection_schema",
    "digest_assembly_prompt",
    "build_post_analysis_prompt",
    "build_digest_prompt",
    "build_weekly_quiz_prompt",
]
