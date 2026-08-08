"""Пакет шаблонов и генераторов промптов."""

from .templates import (
    POST_PROMPT_TEMPLATE,
    DIGEST_ASSEMBLY_PROMPT_TEMPLATE,
    SIMPLE_DIGEST_ASSEMBLY_PROMPT_TEMPLATE,
    WEEKLY_QUIZ_SELECTION_PROMPT,
)
from .builders import (
    build_post_analysis_prompt,
    build_digest_prompt,
    build_weekly_quiz_prompt,
)

__all__ = [
    "POST_PROMPT_TEMPLATE",
    "DIGEST_ASSEMBLY_PROMPT_TEMPLATE",
    "SIMPLE_DIGEST_ASSEMBLY_PROMPT_TEMPLATE",
    "WEEKLY_QUIZ_SELECTION_PROMPT",
    "build_post_analysis_prompt",
    "build_digest_prompt",
    "build_weekly_quiz_prompt",
]
