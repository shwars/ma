from __future__ import annotations

import json

from ma.config import AGENT_DEFAULT_MODEL_ID, load_config, load_dotenv, supports_responses_api


def clear_credential_env(monkeypatch):
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    monkeypatch.delenv("folder_id", raising=False)
    monkeypatch.delenv("api_key", raising=False)


def test_load_config_uses_file_values(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    path = tmp_path / "config.json"
    (tmp_path / ".env").write_text("folder_id=folder-from-dotenv\napi_key=key-from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "folder-from-yandex-env")
    monkeypatch.setenv("YANDEX_API_KEY", "key-from-yandex-env")
    path.write_text(
        json.dumps(
            {
                "folder_id": "folder-from-file",
                "api_key": "key-from-file",
                "models": [
                    {
                        "id": "qwen",
                        "display_name": "Qwen",
                        "model_uri": "gpt://folder/qwen/latest",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.folder_id == "folder-from-file"
    assert config.api_key == "key-from-file"
    assert config.models[0].id == AGENT_DEFAULT_MODEL_ID
    assert config.models[1].id == "qwen"
    assert config.models[1].model_uri == "gpt://folder/qwen/latest"


def test_load_config_uses_dotenv_before_process_env(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    monkeypatch.setenv("YANDEX_FOLDER_ID", "folder-from-yandex-env")
    monkeypatch.setenv("YANDEX_API_KEY", "key-from-yandex-env")
    (tmp_path / ".env").write_text("folder_id=folder-from-dotenv\napi_key=key-from-dotenv\n", encoding="utf-8")

    config = load_config(
        tmp_path / "missing.json",
        model_fetcher=lambda folder_id, api_key: [
            {"id": "aliceai-llm", "display_name": "Alice AI LLM", "model_id": "gpt://%folder_id%/aliceai-llm"}
        ],
    )

    assert config.folder_id == "folder-from-dotenv"
    assert config.api_key == "key-from-dotenv"
    assert config.models[0].id == AGENT_DEFAULT_MODEL_ID
    assert config.models[1].model_uri == "gpt://folder-from-dotenv/aliceai-llm"


def test_load_config_prefers_yandex_env_over_lowercase_env(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    monkeypatch.setenv("YANDEX_FOLDER_ID", "folder-from-env")
    monkeypatch.setenv("YANDEX_API_KEY", "key-from-env")
    monkeypatch.setenv("folder_id", "folder-from-lower-env")
    monkeypatch.setenv("api_key", "key-from-lower-env")

    config = load_config(
        tmp_path / "missing.json",
        model_fetcher=lambda folder_id, api_key: [
            {"id": "aliceai-llm", "display_name": "Alice AI LLM", "model_id": "gpt://%folder_id%/aliceai-llm"}
        ],
    )

    assert config.folder_id == "folder-from-env"
    assert config.api_key == "key-from-env"
    assert config.models[1].model_uri == "gpt://folder-from-env/aliceai-llm"


def test_load_config_uses_lowercase_env_as_final_fallback(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    monkeypatch.setenv("folder_id", "folder-from-lower-env")
    monkeypatch.setenv("api_key", "key-from-lower-env")

    config = load_config(
        tmp_path / "missing.json",
        model_fetcher=lambda folder_id, api_key: [
            {"id": "aliceai-llm", "display_name": "Alice AI LLM", "model_id": "gpt://%folder_id%/aliceai-llm"}
        ],
    )

    assert config.folder_id == "folder-from-lower-env"
    assert config.api_key == "key-from-lower-env"
    assert config.models[1].model_uri == "gpt://folder-from-lower-env/aliceai-llm"


def test_load_config_substitutes_folder_id_and_supports_model_id_alias(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "folder_id": "folder-from-file",
                "api_key": "key-from-file",
                "models": [
                    {
                        "id": "%folder_id%-model",
                        "display_name": "Custom",
                        "model_id": "gpt://%folder_id%/custom/latest",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.models[1].id == "folder-from-file-model"
    assert config.models[1].model_uri == "gpt://folder-from-file/custom/latest"


def test_load_config_queries_models_api_when_config_file_is_missing(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    monkeypatch.setenv("YANDEX_FOLDER_ID", "folder-from-env")
    monkeypatch.setenv("YANDEX_API_KEY", "key-from-env")
    calls = []

    def fake_fetcher(folder_id, api_key):
        calls.append((folder_id, api_key))
        return [
            {"id": "remote-model", "display_name": "Remote Model", "model_id": "gpt://%folder_id%/remote/latest"}
        ]

    config = load_config(tmp_path / "missing.json", model_fetcher=fake_fetcher)

    assert calls == [("folder-from-env", "key-from-env")]
    assert config.models[0].display_name == "Agent Default"
    assert config.models[1].id == "remote-model"
    assert config.models[1].model_uri == "gpt://folder-from-env/remote/latest"


def test_api_discovered_latest_models_get_unique_picker_ids(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    monkeypatch.setenv("YANDEX_FOLDER_ID", "folder-from-env")
    monkeypatch.setenv("YANDEX_API_KEY", "key-from-env")

    config = load_config(
        tmp_path / "missing.json",
        model_fetcher=lambda folder_id, api_key: [
            {"display_name": "First", "model_id": "gpt://folder-from-env/first/latest"},
            {"display_name": "Second", "model_id": "gpt://folder-from-env/second/latest"},
        ],
    )

    model_ids = [model.id for model in config.models]
    assert len(model_ids) == len(set(model_ids))
    assert config.models[1].id == "gpt-folder-from-env-first-latest"
    assert config.models[2].id == "gpt-folder-from-env-second-latest"


def test_model_filter_keeps_only_responses_compatible_gpt_models(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    monkeypatch.setenv("YANDEX_FOLDER_ID", "folder-from-env")
    monkeypatch.setenv("YANDEX_API_KEY", "key-from-env")

    config = load_config(
        tmp_path / "missing.json",
        model_fetcher=lambda folder_id, api_key: [
            {"display_name": "Text", "model_id": "gpt://folder/text/latest"},
            {"display_name": "Image", "model_id": "art://folder/yandex-art/latest"},
            {"display_name": "Realtime", "model_id": "realtime://folder/speech/latest"},
        ],
    )

    assert [model.display_name for model in config.models] == ["Agent Default", "Text"]


def test_configured_non_gpt_models_are_filtered_out(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "folder_id": "folder",
                "api_key": "key",
                "models": [
                    {"display_name": "Text", "model_id": "gpt://folder/text/latest"},
                    {"display_name": "Image", "model_id": "art://folder/yandex-art/latest"},
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert [model.display_name for model in config.models] == ["Agent Default", "Text"]


def test_supports_responses_api_accepts_only_gpt_scheme():
    assert supports_responses_api("gpt://folder/model/latest") is True
    assert supports_responses_api("art://folder/model/latest") is False
    assert supports_responses_api("realtime://folder/model/latest") is False


def test_load_config_does_not_query_models_api_when_config_file_exists(tmp_path, monkeypatch):
    clear_credential_env(monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"folder_id": "folder", "api_key": "key"}), encoding="utf-8")

    config = load_config(path, model_fetcher=lambda folder_id, api_key: (_ for _ in ()).throw(AssertionError))

    assert [model.id for model in config.models] == [AGENT_DEFAULT_MODEL_ID]


def test_load_dotenv_ignores_comments_and_strips_quotes(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        """
# comment
folder_id = "quoted-folder"
api_key='quoted-key'
ignored-line
YANDEX_FOLDER_ID=other-folder
""".strip(),
        encoding="utf-8",
    )

    values = load_dotenv(path)

    assert values["folder_id"] == "quoted-folder"
    assert values["api_key"] == "quoted-key"
    assert values["YANDEX_FOLDER_ID"] == "other-folder"
