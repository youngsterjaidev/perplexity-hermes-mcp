from typing import Any
from app.hermes_client import call_hermes, check_hermes_health
from app.models import HermesTaskRequest


# ─── Tool Catalog ─────────────────────────────────────────────────────────────
# Each entry defines the MCP tool schema exactly as Perplexity expects it.

TOOL_CATALOG = [
    {
        "name": "hermes_run_task",
        "description": (
            "Run a general task or instruction on the Hermes autonomous agent. "
            "Use this for actions like file operations, code execution, "
            "summarization, or any multi-step autonomous task."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "A clear description of what Hermes should do.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max tokens for the Hermes response. Default is 2048.",
                    "default": 2048,
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "hermes_research",
        "description": (
            "Ask the Hermes agent to research a topic and return a structured summary. "
            "Hermes will use its available tools (web search, files, memory) to research "
            "and compile a report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic or question to research.",
                },
                "depth": {
                    "type": "string",
                    "enum": ["quick", "detailed"],
                    "description": "'quick' for a short summary, 'detailed' for an in-depth report.",
                    "default": "quick",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "hermes_status",
        "description": "Check if the Hermes agent is online, reachable, and ready to accept tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ─── Tool Executor ─────────────────────────────────────────────────────────────

async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """
    Routes a tools/call request to the appropriate handler.
    Returns a string result to embed in the MCP tool response.
    """
    if name == "hermes_run_task":
        task_text = arguments.get("task", "")
        max_tokens = int(arguments.get("max_tokens", 2048))
        if not task_text:
            return "Error: 'task' argument is required."
        result = await call_hermes(HermesTaskRequest(prompt=task_text, max_tokens=max_tokens))
        return result.content

    elif name == "hermes_research":
        topic = arguments.get("topic", "")
        depth = arguments.get("depth", "quick")
        if not topic:
            return "Error: 'topic' argument is required."
        prompt = (
            f"Research the following topic and provide a {'detailed report' if depth == 'detailed' else 'concise summary'}:\n\n{topic}"
        )
        result = await call_hermes(HermesTaskRequest(prompt=prompt, max_tokens=4096 if depth == "detailed" else 2048))
        return result.content

    elif name == "hermes_status":
        health = await check_hermes_health()
        if health["status"] == "online":
            models = ", ".join(health.get("models_available", [])) or "unknown"
            return f"Hermes agent is ONLINE. Available models: {models}"
        else:
            return f"Hermes agent is OFFLINE. Error: {health.get('error', 'unknown')}"

    else:
        return f"Error: Unknown tool '{name}'."
