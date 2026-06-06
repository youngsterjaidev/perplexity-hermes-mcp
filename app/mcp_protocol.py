from typing import Any
from pydantic import BaseModel


# ─── JSON-RPC base types ──────────────────────────────────────────────────────

class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Any | None = None
    error: JsonRpcError | None = None


# ─── MCP Capability constants ─────────────────────────────────────────────────

MCP_PROTOCOL_VERSION = "2025-03-26"

SERVER_INFO = {
    "name": "perplexity-hermes-mcp",
    "version": "0.1.0",
}

SERVER_CAPABILITIES = {
    "tools": {"listChanged": False},
}


# ─── MCP response builders ────────────────────────────────────────────────────

def make_initialize_result() -> dict:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": SERVER_CAPABILITIES,
        "serverInfo": SERVER_INFO,
    }


def make_tools_list_result(tools: list[dict]) -> dict:
    return {"tools": tools}


def make_tool_call_result(content: str) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": content,
            }
        ],
        "isError": False,
    }


def make_tool_call_error(message: str) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": f"Tool execution failed: {message}",
            }
        ],
        "isError": True,
    }


def make_error_response(req_id: Any, code: int, message: str) -> JsonRpcResponse:
    return JsonRpcResponse(
        id=req_id,
        error=JsonRpcError(code=code, message=message),
    )
