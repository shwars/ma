from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


AGENT_DEFAULT_MODEL_ID = "__agent_default__"
ModelFetcher = Callable[[str, str], list[Any]]


@dataclass(frozen=True)
class ModelChoice:
    id: str
    display_name: str
    model_uri: str | None

    @property
    def is_agent_default(self) -> bool:
        return self.id == AGENT_DEFAULT_MODEL_ID


@dataclass(frozen=True)
class AppConfig:
    folder_id: str
    api_key: str
    models: list[ModelChoice]
    path: Path

    @property
    def has_credentials(self) -> bool:
        return bool(self.folder_id and self.api_key)


def load_config(path: Path | str | None = None, model_fetcher: ModelFetcher | None = None) -> AppConfig:
    config_path = Path(path) if path is not None else Path.cwd() / "config.json"
    raw: dict[str, Any] = {}
    config_exists = config_path.exists()
    if config_exists:
        raw = json.loads(config_path.read_text(encoding="utf-8"))

    dotenv = load_dotenv(config_path.parent / ".env")
    folder_id = _resolve_credential(raw, dotenv, "folder_id", "YANDEX_FOLDER_ID")
    api_key = _resolve_credential(raw, dotenv, "api_key", "YANDEX_API_KEY")
    raw_models = raw.get("models", [])
    if not config_exists and folder_id and api_key:
        fetcher = model_fetcher or fetch_yandex_models
        raw_models = fetcher(folder_id, api_key)
    models = _load_models(raw_models, folder_id)

    return AppConfig(
        folder_id=folder_id,
        api_key=api_key,
        models=models,
        path=config_path,
    )


def load_dotenv(path: Path | str) -> dict[str, str]:
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _resolve_credential(raw: dict[str, Any], dotenv: dict[str, str], local_name: str, yandex_name: str) -> str:
    return (
        str(raw.get(local_name) or "")
        or dotenv.get(local_name, "")
        or dotenv.get(yandex_name, "")
        or os.getenv(yandex_name, "")
        or os.getenv(local_name, "")
    )


def fetch_yandex_models(folder_id: str, api_key: str) -> list[dict[str, str]]:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://ai.api.cloud.yandex.net/v1",
        api_key=api_key,
        project=folder_id,
    )
    response = client.models.list()
    return [
        {
            "id": _model_choice_id(model.id),
            "display_name": _model_display_name(model.id),
            "model_id": model.id,
        }
        for model in response.data
    ]


def _load_models(raw_models: list[Any], folder_id: str) -> list[ModelChoice]:
    models: list[ModelChoice] = [agent_default_model()]
    for index, item in enumerate(raw_models):
        if isinstance(item, str):
            model_uri = _substitute_folder_id(item, folder_id)
            display_name = item.split("/")[-2] if "/" in item else item
            model_id = _unique_model_choice_id(model_uri)
        else:
            model_uri = item.get("model_id") or item.get("model_uri") or item.get("model") or ""
            model_uri = _substitute_folder_id(model_uri, folder_id)
            display_name = item.get("display_name") or item.get("name") or model_uri
            model_id = _substitute_folder_id(item.get("id") or _unique_model_choice_id(model_uri), folder_id)

        if not model_uri:
            continue
        if not supports_responses_api(model_uri):
            continue
        models.append(ModelChoice(id=model_id or f"model-{index}", display_name=display_name, model_uri=model_uri))

    return models


def agent_default_model() -> ModelChoice:
    return ModelChoice(
        id=AGENT_DEFAULT_MODEL_ID,
        display_name="Agent Default",
        model_uri=None,
    )


def _substitute_folder_id(value: Any, folder_id: str) -> str:
    return str(value or "").replace("%folder_id%", folder_id)


def supports_responses_api(model_uri: str) -> bool:
    return model_uri.startswith("gpt://")


def _model_choice_id(model_id: str) -> str:
    return _unique_model_choice_id(model_id)


def _model_display_name(model_id: str) -> str:
    parts = [part for part in model_id.rstrip("/").split("/") if part]
    if parts and parts[-1] == "latest" and len(parts) >= 2:
        name = parts[-2]
    else:
        name = parts[-1] if parts else model_id
    return name.replace("-", " ").replace("_", " ").title()


def _unique_model_choice_id(model_id: str) -> str:
    return (
        model_id.strip()
        .replace("://", "-")
        .replace("/", "-")
        .replace(":", "-")
        .replace("%", "")
    )
