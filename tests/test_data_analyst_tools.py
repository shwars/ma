from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def load_filesystem_tools():
    path = Path("agents/data_analyst/filesystem_tools.py").resolve()
    spec = importlib.util.spec_from_file_location("data_analyst_filesystem_tools_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ls_filters_files_and_rejects_unsafe_masks(tmp_path):
    tools = load_filesystem_tools()
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    tools.configure(root=tmp_path)

    listing = tools.list_files("*.csv")

    assert "data.csv" in listing
    assert "notes.txt" not in listing
    try:
        tools.list_files("../*.csv")
    except ValueError as exc:
        assert "Unsafe mask" in str(exc)
    else:
        raise AssertionError("unsafe mask should fail")


def test_inspect_csv_and_xlsx(tmp_path):
    pd = __import__("pandas")
    tools = load_filesystem_tools()
    frame = pd.DataFrame({"name": ["Ada", "Grace"], "score": [10, 11]})
    frame.to_csv(tmp_path / "scores.csv", index=False)
    frame.to_excel(tmp_path / "scores.xlsx", index=False)
    tools.configure(root=tmp_path)

    csv_info = json.loads(tools.inspect_file("scores.csv"))
    xlsx_info = json.loads(tools.inspect_file("scores.xlsx"))

    assert csv_info["shape"] == [2, 2]
    assert csv_info["columns"] == ["name", "score"]
    assert csv_info["head"][0]["name"] == "Ada"
    assert xlsx_info["sheets"] == ["Sheet1"]
    assert xlsx_info["shape"] == [2, 2]


def test_inspect_rejects_path_traversal(tmp_path):
    tools = load_filesystem_tools()
    tools.configure(root=tmp_path)

    try:
        tools.inspect_file("../secret.csv")
    except ValueError as exc:
        assert "Unsafe path" in str(exc)
    else:
        raise AssertionError("unsafe path should fail")


def test_upload_uses_configured_container_client(tmp_path):
    tools = load_filesystem_tools()
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    calls: list[tuple[str, str]] = []

    class Files:
        @staticmethod
        def create(container_id, file):
            calls.append((container_id, Path(file.name).name))
            return SimpleNamespace(id=f"file-{Path(file.name).stem}")

    client = SimpleNamespace(containers=SimpleNamespace(files=Files()))
    tools.configure(root=tmp_path, client=client, container_id="container-1")

    result = json.loads(tools.upload_files(["data.csv"]))

    assert calls == [("container-1", "data.csv")]
    assert result == {"files": [{"name": "data.csv", "id": "file-data"}]}
