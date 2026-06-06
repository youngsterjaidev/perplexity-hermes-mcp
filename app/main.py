import logging
import os
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.auth import verify_api_key
from app.mcp_protocol import (
    JsonRpcRequest,
    JsonRpcResponse,
    make_error_response,
    make_initialize_result,
    make_tool_call_error,
    make_tool_call_result,
    make_tools_list_result,
)
from app.tools import TOOL_CATALOG, execute_tool

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp_server")

app = FastAPI(
    title="Perplexity → Hermes MCP Connector",
    description="MCP Streamable HTTP server bridging Perplexity to a self-hosted Hermes agent.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)


# ─── Health check (no auth required) ─────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "perplexity-hermes-mcp"}


# ─── MCP Endpoint ─────────────────────────────────────────────────────────────
# Implements Streamable HTTP transport.
# POST /mcp  →  all JSON-RPC requests (initialize, tools/list, tools/call)
# GET  /mcp  →  returns 405; SSE streaming is not implemented in v1

@app.get("/mcp", dependencies=[Depends(verify_api_key)])
async def mcp_get():
    """
    GET /mcp — Perplexity may probe this.
    Returns 405 since SSE streaming is not used in v1; Streamable HTTP uses POST.
    """
    return Response(status_code=405, content="Use POST for MCP Streamable HTTP requests.")


@app.post("/mcp", dependencies=[Depends(verify_api_key)])
async def mcp_post(request: Request) -> JSONResponse:
    """
    POST /mcp — main MCP entry point.
    Handles: initialize, tools/list, tools/call
    All other methods return a JSON-RPC method-not-found error.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=make_error_response(None, -32700, "Parse error: invalid JSON").model_dump(),
        )

    try:
        rpc = JsonRpcRequest(**body)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content=make_error_response(None, -32600, f"Invalid request: {e}").model_dump(),
        )

    logger.info("MCP method: %s (id=%s)", rpc.method, rpc.id)

    # ── initialize ─────────────────────────────────────────────────────────────
    if rpc.method == "initialize":
        result = make_initialize_result()
        return JSONResponse(
            content=JsonRpcResponse(id=rpc.id, result=result).model_dump(),
            headers={"Mcp-Session-Id": "stateless-v1"},
        )

    # ── tools/list ─────────────────────────────────────────────────────────────
    elif rpc.method == "tools/list":
        result = make_tools_list_result(TOOL_CATALOG)
        return JSONResponse(
            content=JsonRpcResponse(id=rpc.id, result=result).model_dump()
        )

    # ── tools/call ─────────────────────────────────────────────────────────────
    elif rpc.method == "tools/call":
        params = rpc.params or {}
        tool_name: str = params.get("name", "")
        arguments: dict[str, Any] = params.get("arguments", {})

        if not tool_name:
            return JSONResponse(
                content=JsonRpcResponse(
                    id=rpc.id,
                    result=make_tool_call_error("'name' is required in tools/call params."),
                ).model_dump()
            )

        try:
            output = await execute_tool(tool_name, arguments)
            result = make_tool_call_result(output)
        except Exception as e:
            logger.error("Tool execution error: %s", e)
            result = make_tool_call_error(str(e))

        return JSONResponse(
            content=JsonRpcResponse(id=rpc.id, result=result).model_dump()
        )

    # ── notifications/initialized (client sends this after initialize, no response needed) ──
    elif rpc.method == "notifications/initialized":
        return JSONResponse(content={}, status_code=200)

    # ── unknown method ─────────────────────────────────────────────────────────
    else:
        return JSONResponse(
            content=make_error_response(
                rpc.id, -32601, f"Method not found: {rpc.method}"
            ).model_dump()
        )


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
