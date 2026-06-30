from __future__ import annotations

from ma.agent_loader import AgentLoader


def test_agent_loader_discovers_and_loads_global_agent(tmp_path):
    agents_dir = tmp_path / "agents"
    agent_dir = agents_dir / "sample"
    agent_dir.mkdir(parents=True)
    (agent_dir / "main.py").write_text(
        """
class FakeAgent:
    pass

agent = FakeAgent()

def set_context(context):
    agent.context = context

def get_props():
    return {"display_name": "Sample Agent", "uses_notes": True, "container_id": getattr(agent, "container_id", None)}
""".strip(),
        encoding="utf-8",
    )

    loader = AgentLoader(agents_dir)
    assert loader.discover() == ["sample"]

    loaded = loader.load("sample")
    assert loaded.container_id is None
    loaded.agent.container_id = "container-1"
    loaded.set_context({"ok": True})

    assert loaded.display_name == "Sample Agent"
    assert loaded.uses_notes is True
    assert loaded.uses_todo is False
    assert loaded.container_id == "container-1"
    assert loaded.agent.context == {"ok": True}


def test_agent_loader_reload_reads_changed_file(tmp_path):
    agents_dir = tmp_path / "agents"
    agent_dir = agents_dir / "sample"
    agent_dir.mkdir(parents=True)
    main_py = agent_dir / "main.py"
    main_py.write_text("agent = object()\ndef get_props():\n    return {'display_name': 'One'}\n", encoding="utf-8")

    loader = AgentLoader(agents_dir)
    assert loader.load("sample").display_name == "One"

    main_py.write_text("agent = object()\ndef get_props():\n    return {'display_name': 'Two'}\n", encoding="utf-8")

    assert loader.reload("sample").display_name == "Two"


def test_builtin_data_analyst_agent_is_discoverable_and_loadable():
    loader = AgentLoader("agents")

    assert "data_analyst" in loader.discover()

    loaded = loader.load("data_analyst")

    assert loaded.display_name == "Data Analyst"
    assert loaded.agent is not None


def test_builtin_pro_analyst_agent_is_discoverable_and_loadable():
    loader = AgentLoader("agents")

    assert "pro_analyst" in loader.discover()

    loaded = loader.load("pro_analyst")

    assert loaded.display_name == "Pro Analyst"
    assert loaded.uses_todo is True
    assert loaded.agent is not None
