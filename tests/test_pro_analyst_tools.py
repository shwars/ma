from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_pro_filesystem_tools():
    path = Path("agents/pro_analyst/filesystem_tools.py").resolve()
    spec = importlib.util.spec_from_file_location("pro_analyst_filesystem_tools_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pro_skill_tools():
    path = Path("agents/pro_analyst/skill_tools.py").resolve()
    spec = importlib.util.spec_from_file_location("pro_analyst_skill_tools_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pro_main():
    path = Path("agents/pro_analyst/main.py").resolve()
    spec = importlib.util.spec_from_file_location("pro_analyst_main_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_file_rejects_unsafe_paths_and_respects_byte_limit(tmp_path):
    tools = load_pro_filesystem_tools()
    (tmp_path / "note.txt").write_text("abcdef", encoding="utf-8")
    tools.configure(root=tmp_path)

    assert tools.read_local_file("note.txt", max_bytes=3) == "abc"
    with pytest.raises(ValueError, match="Unsafe path"):
        tools.read_local_file("../note.txt")


def test_write_file_creates_files_and_refuses_overwrite(tmp_path):
    tools = load_pro_filesystem_tools()
    tools.configure(root=tmp_path)

    assert "Wrote reports/out.md" in tools.write_local_file("reports/out.md", "# Report")
    assert (tmp_path / "reports" / "out.md").read_text(encoding="utf-8") == "# Report"
    assert "already exists" in tools.write_local_file("reports/out.md", "new")

    tools.write_local_file("reports/out.md", "new", overwrite=True)

    assert (tmp_path / "reports" / "out.md").read_text(encoding="utf-8") == "new"


def test_edit_file_applies_unified_diff_and_rejects_unsafe_paths(tmp_path):
    tools = load_pro_filesystem_tools()
    (tmp_path / "sample.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    tools.configure(root=tmp_path)

    diff = """--- a/sample.txt
+++ b/sample.txt
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
"""

    assert tools.edit_local_file("sample.txt", diff) == "Edited sample.txt."
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "one\nTWO\nthree\n"
    with pytest.raises(ValueError, match="Unsafe path"):
        tools.edit_local_file("../sample.txt", diff)


def test_execute_command_accepts_allowlisted_entrypoint_and_rejects_unknown(tmp_path):
    tools = load_pro_filesystem_tools()
    tools.configure(root=tmp_path)

    if shutil.which("cmd"):
        result = json.loads(tools.run_command("cmd", ["/c", "echo hello"]))
    elif shutil.which("bash"):
        result = json.loads(tools.run_command("bash", ["-lc", "echo hello"]))
    else:
        pytest.skip("No allowlisted command entrypoint is available.")

    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]
    with pytest.raises(ValueError, match="Allowed commands"):
        tools.run_command("python", ["--version"])


def test_skill_tools_discover_bundled_and_current_directory_skills(tmp_path):
    tools = load_pro_skill_tools()
    agent_dir = Path("agents/pro_analyst").resolve()
    skill_dir = tmp_path / "skills" / "pptx_presentation"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        """---
id: pptx_presentation
name: Local PPTX
description: Local override.
tags: [local]
---

# Local instructions
""",
        encoding="utf-8",
    )
    tools.configure(root=tmp_path, agent_dir=agent_dir)

    listing = json.loads(tools.list_skill_metadata())
    by_id = {skill["id"]: skill for skill in listing["skills"]}

    assert "data_exploration" in by_id
    assert "pptx_presentation" in by_id
    assert by_id["pptx_presentation"]["name"] == "Local PPTX"
    assert by_id["pptx_presentation"]["location"] == "current"


def test_load_skill_returns_metadata_and_instructions_and_rejects_unsafe_id(tmp_path):
    tools = load_pro_skill_tools()
    agent_dir = Path("agents/pro_analyst").resolve()
    tools.configure(root=tmp_path, agent_dir=agent_dir)

    skill = json.loads(tools.load_skill_instructions("markdown_to_pdf"))

    assert skill["metadata"]["id"] == "markdown_to_pdf"
    assert "Markdown To PDF" in skill["instructions"]
    with pytest.raises(ValueError, match="Unsafe skill id"):
        tools.load_skill_instructions("../secret")


def test_pro_analyst_reuses_container_and_keeps_upload_consistent(tmp_path):
    main = load_pro_main()
    data_file = tmp_path / "data.csv"
    data_file.write_text("a,b\n1,2\n", encoding="utf-8")
    created: list[str] = []
    uploads: list[tuple[str, str]] = []

    class Containers:
        class files:
            @staticmethod
            def create(container_id, file):
                uploads.append((container_id, Path(file.name).name))
                return SimpleNamespace(
                    id="file-data",
                    container_id=container_id,
                    path="/mnt/data/data.csv",
                    bytes=Path(file.name).stat().st_size,
                )

        @staticmethod
        def create(name):
            created.append(name)
            return SimpleNamespace(id="container-1")

    context = SimpleNamespace(
        client=SimpleNamespace(containers=Containers()),
        model=None,
        todo_tools=[],
        clarification_tools=[],
        log=lambda message: None,
    )

    cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        main.set_context(context)
        main.set_context(context)
        result = json.loads(main._filesystem_tools.upload_files(["data.csv"]))
    finally:
        os.chdir(cwd)

    assert created == ["ma-pro-analysis"]
    assert main.get_container_id() == "container-1"
    assert main.get_props()["container_id"] == "container-1"
    assert uploads == [("container-1", "data.csv")]
    assert result["files"] == [
        {
            "name": "data.csv",
            "id": "file-data",
            "container_id": "container-1",
            "container_path": "/mnt/data/data.csv",
            "bytes": data_file.stat().st_size,
        }
    ]
    assert "container_path" in result["code_interpreter_note"]
    code_tools = [tool for tool in main.agent.tools if getattr(tool, "tool_config", {}).get("type") == "code_interpreter"]
    assert code_tools[-1].tool_config["container"] == "container-1"


def test_pro_analyst_recreates_container_when_client_changes():
    main = load_pro_main()
    created: list[tuple[str, str]] = []

    class Containers:
        def __init__(self, container_id: str) -> None:
            self.container_id = container_id

        def create(self, name):
            created.append((self.container_id, name))
            return SimpleNamespace(id=self.container_id)

    first_context = SimpleNamespace(
        client=SimpleNamespace(containers=Containers("container-1")),
        model=None,
        todo_tools=[],
        clarification_tools=[],
        log=lambda message: None,
    )
    second_context = SimpleNamespace(
        client=SimpleNamespace(containers=Containers("container-2")),
        model=None,
        todo_tools=[],
        clarification_tools=[],
        log=lambda message: None,
    )

    main.set_context(first_context)
    main.set_context(first_context)
    main.set_context(second_context)

    assert created == [("container-1", "ma-pro-analysis"), ("container-2", "ma-pro-analysis")]
    assert main.get_container_id() == "container-2"
    code_tools = [tool for tool in main.agent.tools if getattr(tool, "tool_config", {}).get("type") == "code_interpreter"]
    assert code_tools[-1].tool_config["container"] == "container-2"


def test_pro_analyst_instructions_include_skill_snapshot_and_require_tool_loading(tmp_path):
    main = load_pro_main()

    class Containers:
        @staticmethod
        def create(name):
            return SimpleNamespace(id="container-1")

    context = SimpleNamespace(
        client=SimpleNamespace(containers=Containers()),
        model=None,
        todo_tools=[],
        clarification_tools=[],
        log=lambda message: None,
    )

    cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        main.set_context(context)
    finally:
        os.chdir(cwd)

    assert "Available skills snapshot" in main.agent.instructions
    assert "pptx_presentation" in main.agent.instructions
    assert "review that snapshot before using ls" in main.agent.instructions
    assert "Do not reload skill metadata during execution" in main.agent.instructions
    assert "Do not call list_skills unless the user explicitly asks" in main.agent.instructions
    assert "load_skill(skill_id)" in main.agent.instructions
    assert "Always upload every local data file needed for analysis" in main.agent.instructions


def test_pro_analyst_context_includes_todo_tools(tmp_path):
    main = load_pro_main()

    class Containers:
        @staticmethod
        def create(name):
            return SimpleNamespace(id="container-1")

    todo_tool = object()
    context = SimpleNamespace(
        client=SimpleNamespace(containers=Containers()),
        model=None,
        todo_tools=[todo_tool],
        clarification_tools=[],
        log=lambda message: None,
    )

    cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        main.set_context(context)
    finally:
        os.chdir(cwd)

    assert todo_tool in main.agent.tools
    assert "create TODO items" in main.agent.instructions
