from typing import Any
import json
import logging
from itertools import cycle
import time
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_not_exception_type,
)
import jsonschema
from openai import OpenAI
from openai import (
    RateLimitError as ORRateLimitError,
    APIConnectionError as ORAPIConnectionError,
    APIStatusError as ORAPIStatusError,
    AuthenticationError as ORAuthError,
    BadRequestError as ORBadRequestError
)

import datetime
from prompts import post_prompt_template

logger = logging.getLogger(__name__)

class MessageExtractor:
    """Слой для общения с OpenRouter"""

    def __init__(
        self,
        model_names: list[str],
        api_keys: list[str],
        proxy: str,
        limit: int = 15000,
        temperature: float = 0.0,
    ):
        self.keys = list(api_keys) if api_keys else []
        self.keys_iterator = cycle(self.keys) if self.keys else None
        self.model_names = model_names or []

        if not self.keys:
            raise ValueError(
                "Нужно предоставить хотя бы один API ключ"
            )

        self.proxy = proxy
        self.limit = limit
        self.temperature = temperature
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
       # retry=retry_if_not_exception_type(ORRateLimitError),
    )
    def call_llm(
        self,
        user_prompt,
        system_prompt: str = "",
        schema: dict = {},
    ):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            jsonschema.Draft7Validator.check_schema(schema)
        except jsonschema.SchemaError as e:
            raise ValueError(f"Некорректная схема: {e}") from e

        try:
            working_key = next(self.keys_iterator)
            model_name = self.model_names[0]

            api_kwargs = {
                "model": model_name,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": 4096,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "digest_quize",
                        "strict": True,
                        "schema": schema,
                    },
                }
            }

            with httpx.Client(proxy=self.proxy) as http_client:
                client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=working_key,
                    http_client=http_client,
                    max_retries=0,
                    default_headers={
                        "HTTP-Referer": "https://github.com/",
                        "X-Title": "MessageExtractor",
                    },
                )
                start_time = time.time()

                raw_response = client.chat.completions.with_raw_response.create(
                    **api_kwargs
                )
                latency = round(time.time() - start_time, 2)

                parsed_response = raw_response.parse()
                if not getattr(parsed_response, "choices", None):
                    logger.error(
                        f"Operouter не вернул choices, меняем модель. Ответ: {parsed_response}"
                    )
                res = parsed_response.choices[0].message.content or ""

            try:
                res = "".join(
                    ch for ch in res if ord(ch) >= 32 or ch in "\n\r\t"
                )
                res = json.loads(res)

                self.temperature = 0.0
                tokens = (
                    parsed_response.usage.total_tokens
                    if parsed_response.usage
                    else 0
                )
                logger.info(
                    f"Успешный ответ LLM: {res}",
                    extra={
                        "llm.model": model_name,
                        "llm.latency_sec": latency,
                        "llm.tokens.total": parsed_response.usage.total_tokens,
                    },
                )
                return res, tokens
            except json.JSONDecodeError as e:
                logger.info("Ошибка парсинга JSON, меняем модель")

        except ORBadRequestError as e:
            error_msg = str(e).lower()
            reason = "unknown"
            if "schema" in error_msg or "format" in error_msg:
                reason = "schema_not_supported"
            elif (
                "context" in error_msg
                or "length" in error_msg
                or "token" in error_msg
            ):
                reason = "context_window_exceeded"

            logger.error(
                f"Плохой запрос (400) к OpenRouter: {e}",
                extra={
                    "llm.model": model_name,
                    "llm.error_type": "bad_request",
                    "llm.bad_request_reason": reason,
                },
            )
            raise

        except ORRateLimitError:
            logger.warning(
                f"OpenRouter: Rate Limit 429 для модели {model_name}",
                extra={
                    "llm.model": model_name,
                    "llm.error_type": "rate_limit",
                    "llm.status_code": 429,
                    "llm.key_prefix": working_key[:6],
                },
            )
            raise
        except ORAuthError as e:
            logger.error(f"Ошибка аутенфикации на OpenRouter: {e}")
            raise

        except ORAPIStatusError as e:
            logger.error(f"Ошибка статуса API OpenRouter: {e}")
            raise

        except ORAPIConnectionError as e:
            logger.error(f"Ошибка соединения с OpenRouter: {e}")
            raise

        except Exception as e:
            logger.error(f"Неожиданная ошибка на OpenRouter: {e}")
            raise
 

    def build_message_extraction_prompt(
        self, text: str, url: str = "", reference_date=None
    ) -> str:
        if isinstance(reference_date, datetime.datetime):
            ref_str = reference_date.strftime("%Y-%m-%d (%A)")
        elif isinstance(reference_date, str):
            ref_str = reference_date
        else:
            ref_str = datetime.datetime.now().strftime("%Y-%m-%d (%A)")

        prompt = post_prompt_template.format(
            post_text=text
            )
        return prompt

    def _deep_clean(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: self._deep_clean(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._deep_clean(i) for i in data]
        if isinstance(data, str):
            cleaned = "".join(ch for ch in data if ch.isprintable())
            return cleaned.strip()
        return data
