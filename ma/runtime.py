from __future__ import annotations

from functools import lru_cache

from .config import AppConfig, ModelChoice


@lru_cache(maxsize=16)
def create_yandex_model(folder_id: str, api_key: str, model_uri: str):
    from agents import set_tracing_disabled
    from agents.models.openai_responses import OpenAIResponsesModel
    from openai import AsyncOpenAI

    set_tracing_disabled(True)
    client = AsyncOpenAI(
        base_url="https://ai.api.cloud.yandex.net/v1",
        api_key=api_key,
        project=folder_id,
    )
    return OpenAIResponsesModel(model=model_uri, openai_client=client)


def build_model(config: AppConfig, choice: ModelChoice | None):
    if choice is None:
        return None
    if choice.is_agent_default:
        return None
    if not config.has_credentials:
        return None
    if not choice.model_uri:
        return None
    return create_yandex_model(config.folder_id, config.api_key, choice.model_uri)
