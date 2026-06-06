# Agents

This document describes every agent involved in the `perplexity-hermes-mcp` system — what each one is, what role it plays, how they communicate, and how to extend them.

---

## Agent Overview

The system has two active agents and one passive orchestrator:

| Agent | Type | Location | Role |
|---|---|---|---|
| **Perplexity AI** | Hosted LLM / Orchestrator | Perplexity cloud | Receives user queries, decides when to invoke MCP tools, presents results |
| **MCP Connector** | Protocol bridge / Relay | Small VM (OCI) | Translates MCP calls into OpenAI-style HTTP requests forwarded to Hermes |
| **Hermes Agent** | Autonomous AI agent | Large VM (OCI) | Executes tasks autonomously — research, analysis, file ops, web access, tool use |

```
┌───────────────────────────────────────────────────────────────┐
│                    AGENT INTERACTION FLOW                     │
│                                                               │
│  [User]                                                       │
│    │  natural language query                                  │
│    ▼                                                          │
│  [Perplexity AI]  ── orchestrates ──► MCP tools/call          │
│    │                                       │                  │
│    │               HTTPS, Streamable HTTP  │                  │
│    │                                       ▼                  │
│    │                            [MCP Connector]               │
│    │                            (FastAPI bridge)              │
│    │                                       │                  │
│    │               Internal HTTP :8642     │                  │
│    │                                       ▼                  │
│    │                            [Hermes Agent]                │
│    │                            (autonomous executor)         │
│    │                                       │                  │
│    │◄──────── structured result ───────────┘                  │
└───────────────────────────────────────────────────────────────┘
```

---

## Agent 1 — Perplexity AI (Orchestrator)

### What it is

Perplexity is a hosted AI assistant that supports **custom remote connectors** via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). When a user asks a question in Perplexity, it decides — based on the query and available tools — whether to answer directly from its own knowledge or delegate to an MCP tool.

### Role in this system

- **Receives** the user's natural language query
- **Decides** which MCP tool to call (if any) based on query semantics
- **Sends** a `tools/call` JSON-RPC request to the MCP Connector
- **Receives** the structured result and incorporates it into its response
- **Presents** the final answer to the user

### What Perplexity does NOT do

- It does not execute tasks itself — it delegates to Hermes via the connector
- It does not maintain state between tool calls — each `tools/call` is independent
- It does not have direct access to Hermes — all communication goes through the connector

### MCP initialization sequence

When you add the connector in Perplexity settings, it performs:

```
POST /mcp  →  initialize        (handshake, protocol version)
POST /mcp  →  tools/list        (discover available tools)
```

At query time:

```
POST /mcp  →  tools/call        (execute a specific tool)
```

### How to influence Perplexity's tool selection

Perplexity selects tools based on tool **name** and **description** in the `tools/list` response. If Perplexity is not picking up the right tool for a query, update the `description` field in `app/tools.py` to be more explicit about when that tool should be used.

---

## Agent 2 — MCP Connector (Bridge)

### What it is

The MCP Connector is a **FastAPI application** that runs on the small OCI VM. It is not an AI agent — it is a stateless HTTP translation layer. Its job is to speak MCP to Perplexity and OpenAI-style HTTP to Hermes.

### Role in this system

- **Authenticates** incoming requests from Perplexity using `CONNECTOR_API_KEY`
- **Parses** MCP JSON-RPC requests (`initialize`, `tools/list`, `tools/call`)
- **Validates** tool arguments using Pydantic models before forwarding
- **Translates** tool calls into `POST /v1/chat/completions` payloads for Hermes
- **Returns** structured MCP-compliant JSON-RPC responses to Perplexity
- **Shields** Hermes from direct internet exposure

### Source files

| File | Responsibility |
|---|---|
| `app/main.py` | FastAPI app entry point; `/mcp` POST+GET routes; `/health` endpoint |
| `app/mcp_protocol.py` | MCP JSON-RPC type definitions; response builder functions |
| `app/auth.py` | API key validation middleware (`X-API-Key` and `Authorization: Bearer`) |
| `app/hermes_client.py` | Async `httpx` client that sends requests to Hermes `/v1/chat/completions` |
| `app/tools.py` | Tool catalog (JSON schemas for `tools/list`) and tool executor logic |
| `app/models.py` | Shared Pydantic request/response models |

### Request lifecycle

```
Perplexity sends POST /mcp
        │
        ▼
  auth.py validates X-API-Key
        │
        ▼
  main.py routes by method:
    ├── initialize      → return InitializeResult + Mcp-Session-Id header
    ├── tools/list      → return tool catalog from tools.py
    └── tools/call
            │
            ▼
      tools.py validates arguments (Pydantic)
            │
            ▼
      hermes_client.py builds chat/completions payload
            │
            ▼
      POST http://<HERMES_BASE_URL>/v1/chat/completions
            │
            ▼
      Parse Hermes response → extract content
            │
            ▼
      Return MCP CallToolResult to Perplexity
```

### Configuration

All connector config lives in `.env`:

```env
HERMES_BASE_URL=http://10.0.0.2:8642/v1     # Hermes internal endpoint
HERMES_API_KEY=your-hermes-api-key           # Hermes bearer token
CONNECTOR_API_KEY=your-connector-key         # Key Perplexity sends
HERMES_TIMEOUT=120                           # Max seconds to wait for Hermes
```

### Stateless design

The connector is **fully stateless**. No session state is stored between requests. The `Mcp-Session-Id` header returned on `initialize` is always `stateless-v1`. This keeps the 1 GB VM footprint minimal and makes the connector trivially restartable without data loss.

---

## Agent 3 — Hermes Agent (Executor)

### What it is

[Hermes Agent](https://hermes-agent.nousresearch.com/) by NousResearch is a **self-hosted autonomous AI agent**. Unlike a simple LLM API, Hermes can execute multi-step tasks using built-in tools: web search, file operations, code execution, memory, MCP skill extensions, and more.

### Role in this system

- **Receives** task instructions forwarded by the MCP Connector
- **Plans and executes** multi-step workflows autonomously
- **Uses built-in tools** (web search, file read/write, code execution) as needed
- **Returns** a structured natural language result to the connector
- **Runs continuously** as a `hermes gateway` process on the large VM

### Built-in Hermes capabilities

| Capability | Description |
|---|---|
| Web search | Research topics, fetch URLs, extract content |
| File operations | Read, write, and summarize files on the host VM |
| Code execution | Run Python, Bash, and other scripts |
| Memory | Persist context across sessions using Hermes memory system |
| MCP skills | Load external MCP tool servers as Hermes skills |
| Terminal access | Execute shell commands (treat with caution — scope carefully) |
| Multi-step planning | Break complex goals into steps and execute them sequentially |

### API interface

Hermes exposes an **OpenAI-compatible API** on port 8642:

```
GET  /v1/models                        → list available models
POST /v1/chat/completions              → submit a task prompt
```

Authentication: `Authorization: Bearer <API_SERVER_KEY>`

Example task payload sent by the connector:

```json
{
  "model": "hermes",
  "messages": [
    {
      "role": "user",
      "content": "Research Azure subscription-to-subscription migration blockers for SQL Server 2019. Return a structured summary with key findings, risks, and recommended actions."
    }
  ],
  "max_tokens": 2048
}
```

### Hermes configuration (`~/.hermes/.env`)

```env
API_SERVER_ENABLED=true
API_SERVER_KEY=your-strong-api-key
API_SERVER_HOST=0.0.0.0          # Bind to all interfaces; OCI Security List restricts access
API_SERVER_PORT=8642
```

### Starting Hermes

```bash
hermes gateway
```

For production, run it under a process manager (systemd, tmux, or screen) so it survives SSH disconnects:

```bash
# Quick persistent run
tmux new -s hermes
hermes gateway
# Ctrl+B then D to detach
```

```bash
# Or create a systemd service (recommended)
sudo nano /etc/systemd/system/hermes.service
```

```ini
[Unit]
Description=Hermes Agent Gateway
After=network.target

[Service]
Type=simple
User=ubuntu
ExecStart=/home/ubuntu/.hermes/bin/hermes gateway
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hermes
sudo systemctl status hermes
```

---

## Tool Catalog

These are the MCP tools the connector exposes to Perplexity. Each tool maps to a specific Hermes prompt pattern in `app/tools.py`.

### `hermes_run_task`

**Purpose:** General-purpose autonomous task execution. Use this for anything that doesn't fit `hermes_research` — summarizing commits, generating documentation, analyzing logs, processing structured data.

**Input schema:**

```json
{
  "task": {
    "type": "string",
    "description": "Plain English description of what Hermes should do"
  },
  "max_tokens": {
    "type": "integer",
    "default": 2048,
    "description": "Max tokens in Hermes response"
  }
}
```

**Example Perplexity prompt that triggers this tool:**
> *"Use Hermes to summarize the last 3 commits in the anuntatech-migration repo"*

**Hermes prompt template:**
```
You are an autonomous AI agent. Complete the following task and return a structured result.

Task: {task}

Be thorough, accurate, and concise. If the task requires multiple steps, complete them all before responding.
```

---

### `hermes_research`

**Purpose:** Research a specific topic and return a structured report. Hermes will use web search and its knowledge to compile findings.

**Input schema:**

```json
{
  "topic": {
    "type": "string",
    "description": "Topic or question to research"
  },
  "depth": {
    "type": "string",
    "enum": ["quick", "detailed"],
    "default": "quick",
    "description": "'quick' returns a concise summary; 'detailed' returns a full structured report"
  }
}
```

**Example Perplexity prompt that triggers this tool:**
> *"Use Hermes to research Azure cost optimization strategies for an OCI migration"*

**Hermes prompt template (detailed):**
```
You are a technical research agent. Research the following topic in depth.

Topic: {topic}

Return a structured report with:
1. Executive Summary (3-5 sentences)
2. Key Findings (bullet points)
3. Risks and Considerations
4. Recommended Actions
5. References or sources used
```

---

### `hermes_status`

**Purpose:** Health check. Verifies the Hermes Agent is reachable and responding. Useful for debugging connectivity before running a real task.

**Input schema:** None required (`{}`)

**Returns:**
- `Hermes agent is ONLINE. Available models: hermes` — if reachable
- `Hermes agent is OFFLINE: <error detail>` — if unreachable, with the specific failure reason

**Example Perplexity prompt that triggers this tool:**
> *"Check if Hermes is online"*

---

## Adding a New Tool

To add a new MCP tool exposed to Perplexity:

### Step 1 — Define the tool schema in `app/tools.py`

```python
{
    "name": "hermes_code_review",
    "description": "Submit code to Hermes for autonomous review. Returns findings, issues, and improvement suggestions.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The code snippet or file content to review"
            },
            "language": {
                "type": "string",
                "description": "Programming language (e.g. python, javascript, bash)",
                "default": "python"
            }
        },
        "required": ["code"]
    }
}
```

### Step 2 — Add the executor in `app/tools.py`

```python
async def execute_hermes_code_review(arguments: dict, hermes_client) -> str:
    code = arguments["code"]
    language = arguments.get("language", "python")
    prompt = f"""Review the following {language} code. Return:
1. Summary of what the code does
2. Issues found (bugs, security risks, bad practices)
3. Improvement suggestions
4. Corrected version if changes are needed

Code:
```{language}
{code}
```"""
    return await hermes_client.chat(prompt)
```

### Step 3 — Register the executor in the tool dispatcher

```python
TOOL_EXECUTORS = {
    "hermes_run_task": execute_hermes_run_task,
    "hermes_research": execute_hermes_research,
    "hermes_status": execute_hermes_status,
    "hermes_code_review": execute_hermes_code_review,   # add this
}
```

### Step 4 — Restart the connector

```bash
sudo systemctl restart perplexity-hermes-mcp
```

Perplexity will pick up the new tool automatically on the next `tools/list` call (usually within 60 seconds, or immediately after reconnecting the connector in Settings).

---

## Agent Security Boundaries

This is critical. Each agent boundary has explicit trust rules:

| Boundary | Auth mechanism | What is allowed |
|---|---|---|
| User → Perplexity | Perplexity account auth | Natural language queries |
| Perplexity → Connector | `CONNECTOR_API_KEY` in `X-API-Key` header | Only `initialize`, `tools/list`, `tools/call` for defined tools |
| Connector → Hermes | `HERMES_API_KEY` Bearer token | Only `POST /v1/chat/completions` and `GET /v1/models` |
| Hermes → Host OS | Hermes internal permission model | Scoped to Hermes working directory; no root by default |

**The connector never passes raw user input directly to Hermes without processing.** All tool arguments go through Pydantic validation in `app/tools.py` before being assembled into a Hermes prompt. This prevents prompt injection patterns from reaching Hermes unfiltered.

**Hermes runs on a dedicated VM with no production secrets.** The large VM should not hold cloud provider credentials, SSH keys to other systems, or database access. Hermes's tool outputs go back to Perplexity only — they are never written to external systems in v1.

---

## Extending to ChatGPT

ChatGPT's **Custom GPT Actions** and **MCP connector support** (v1.0 roadmap) use a similar pattern but require **OAuth 2.0** in addition to API key auth. The connector's `auth.py` will need to be extended with an OAuth token endpoint. The tool catalog and Hermes integration remain identical — only the auth handshake changes.

See the [Roadmap](README.md#roadmap) in the README for the planned v1.0 OAuth milestone.

---

*Part of [perplexity-hermes-mcp](https://github.com/youngsterjaidev/perplexity-hermes-mcp) · Built by [Jai Dev](https://github.com/youngsterjaidev)*
