"""Pydantic-схемы для структурированных ответов LLM и конвертации в Strict Mode JSON Schema."""

import copy
from typing import List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


def to_strict_json_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Преобразует JSON-схему Pydantic в схему, совместимую со Strict Mode в OpenAI / OpenRouter:
    1. Устанавливает additionalProperties: False для всех объектов.
    2. Включает все свойства из properties в список required.
    """
    strict_schema = copy.deepcopy(schema)

    def _transform(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                if "properties" in node and isinstance(node["properties"], dict):
                    node["required"] = list(node["properties"].keys())
            for val in list(node.values()):
                _transform(val)
        elif isinstance(node, list):
            for item in node:
                _transform(item)

    _transform(strict_schema)
    return strict_schema


class QuestionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., description="Текст вопроса (максимум 300 символов)")
    options: List[str] = Field(..., min_length=4, max_length=4, description="Ровно 4 варианта ответа")
    correct_answer: str = Field(..., description="Правильный ответ из списка options")
    explanation: str = Field(..., description="Краткое объяснение (максимум 200 символов)")
    difficulty_level: str = Field(..., description="Уровень сложности: easy, medium или hard")


class PostAnalysisSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: str = Field(..., description="Пошаговое обоснование оценок аудиторий")
    is_ad_or_trash: bool = Field(..., description="true, если пост — спам/реклама/не про ИИ")
    is_tech_relevant: bool = Field(..., description="true, если новость интересна разработчикам")
    is_simple_relevant: bool = Field(..., description="true, если новость интересна широкой аудитории")
    tech_facts: List[str] = Field(default_factory=list, description="1-3 инженерных факта")
    simple_facts: List[str] = Field(default_factory=list, description="1-3 простых факта")
    tech_questions: List[QuestionSchema] = Field(default_factory=list, description="Технические вопросы")
    simple_questions: List[QuestionSchema] = Field(default_factory=list, description="Простые вопросы")

    @classmethod
    def to_dict_schema(cls) -> Dict[str, Any]:
        return to_strict_json_schema(cls.model_json_schema())


class WeeklyQuizSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: str = Field(..., description="Обоснование выбора вопросов")
    questions: List[QuestionSchema] = Field(..., min_length=1, max_length=5, description="1-5 отбранных вопросов")

    @classmethod
    def to_dict_schema(cls) -> Dict[str, Any]:
        return to_strict_json_schema(cls.model_json_schema())
