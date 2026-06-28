from agents import Agent, WebSearchTool


agent = Agent(
    name="Simple",
    instructions=(
        "You are a concise helpful assistant. Use web search when the user asks "
        "for current facts, links, or information that may have changed."
    ),
    tools=[WebSearchTool()],
)


def get_props() -> dict:
    return {
        "display_name": "Simple",
        "uses_notes": False,
        "uses_todo": False,
    }
