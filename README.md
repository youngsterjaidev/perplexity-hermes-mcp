# Perplexity → Hermes MCP Connector

> A lightweight Python FastAPI bridge that connects [Perplexity AI custom remote connectors](https://www.perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors) to a self-hosted [Hermes Agent](https://hermes-agent.nousresearch.com/) using the **Model Context Protocol (MCP) over Streamable HTTP**.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![MCP](https://img.shields.io/badge/MCP-2025--03--26-purple)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What Is This Project?

**`perplexity-hermes-mcp`** is a personal infrastructure project by [Jai Dev](https://github.com/youngsterjaidev) — a Cloud Solutions Architect and DevOps Engineer working extensively with Azure, AWS, and GCP migrations.

### The Problem

Jai wanted to use **Perplexity AI** (and eventually ChatGPT) as a natural-language interface to send long-running research tasks, cloud migration analysis, and documentation jobs to a **self-hosted AI agent running on his own server** — without paying for hosted AI compute per task.

The challenge: Perplexity's custom connector system speaks **MCP (Model Context Protocol)** over HTTPS. Hermes Agent speaks **OpenAI-compatible HTTP** (`/v1/chat/completions`). These two protocols do not talk to each other natively.

### The Solution

This project builds a **thin protocol bridge** — a FastAPI server that:

1. **Speaks MCP** to Perplexity (initialize, tools/list, tools/call)
2. **Translates** those tool calls into OpenAI-style requests
3. **Forwards** them to a self-hosted Hermes Agent running on a private VM
4. **Returns** structured results back to Perplexity

The result: you can open Perplexity, type a task like _"Research Azure migration blockers for SQL Server 2019"_, and Hermes — running on your own server — does the work autonomously and returns the result directly into your Perplexity conversation.

### Why Self-Host Hermes?

- **Cost control** — run your own LLM inference or connect Hermes to your existing API keys
- **Data privacy** — cloud migration work involves internal architecture details, cost data, and infrastructure specs that should not leave your environment
- **Custom tools** — Hermes supports pluggable skills and MCP tool extensions tailored to your workflow
- **Always-on agent** — your server runs 24/7 independent of any third-party hosted agent service

### Who Is This For?

This project is built for engineers, architects, and DevOps practitioners who:

- Run or want to run a self-hosted autonomous AI agent
- Want to control costs while still using frontier AI interfaces (Perplexity, ChatGPT)
- Work with sensitive technical domains (cloud migrations, infrastructure, databases) where data privacy matters
- Want a reproducible, auditable, version-controlled automation bridge — not a no-code SaaS connector

---

## Table of Contents

- [What Is This Project?](#what-is-this-project)
- [Overview](#overview)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [MCP Tools](#mcp-tools)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Server](#running-the-server)
- [Testing the MCP Endpoint](#testing-the-mcp-endpoint)
- [Production Deployment](#production-deployment)
  - [Systemd Service](#systemd-service)
  - [Nginx + TLS](#nginx--tls)
- [Connecting Perplexity](#connecting-perplexity)
- [Hermes Agent Setup](#hermes-agent-setup)
- [OCI Network Security](#oci-network-security)
- [Security Considerations](#security-considerations)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview

This project solves a specific protocol mismatch problem:

- **Perplexity** custom remote connectors expect a proper [MCP server](https://modelcontextprotocol.io/) over HTTPS with Streamable HTTP or SSE transport.
- **Hermes Agent** exposes an OpenAI-compatible `/v1/chat/completions` API — not an MCP server.

This connector sits between them, speaking MCP to Perplexity and OpenAI-style HTTP to Hermes. Perplexity discovers tools, calls them, and gets results — all without knowing or caring that Hermes is behind the scenes.

```
You, in Perplexity
       │
       │  "Research Azure migration blockers for project X"
       ▼
  [Perplexity AI]
       │  MCP tools/call → hermes_research
       ▼
  [This Connector]  ←── HTTPS, Streamable HTTP, API Key
       │  POST /v1/chat/completions
       ▼
  [Hermes Agent]  ←── Internal HTTP, Bearer token
       │  Autonomous task execution
       ▼
  Structured result back to Perplexity
```

---

## Architecture

Designed for a **two-VM setup on Oracle Cloud Infrastructure (OCI)**:

```
                        INTERNET
                           │
                    HTTPS :443
                           │
          ┌────────────────▼─────────────────┐
          │   OCI Small VM  (1 vCPU / 1 GB)  │
          │   mcp.yourdomain.com             │
          │                                  │
          │   ┌──────────┐  ┌─────────────┐  │
          │   │  Nginx   │  │  FastAPI    │  │
          │   │  TLS     ├──►  MCP Server │  │
          │   │  Proxy   │  │  :8000      │  │
          │   └──────────┘  └──────┬──────┘  │
          └─────────────────────────┼────────┘
                                    │
                          Internal HTTP :8642
                          (OCI private network)
                                    │
          ┌─────────────────────────▼────────┐
          │   OCI Large VM  (8 CPU / 8 GB)   │
          │   (private, no public exposure)  │
          │                                  │
          │   ┌────────────────────────────┐  │
          │   │   Hermes Agent             │  │
          │   │   API Server :8642         │  │
          │   │   OpenAI-compatible API    │  │
          │   └────────────────────────────┘  │
          └──────────────────────────────────┘
```

| VM | Size | Role | Public? |
|---|---|---|---|
| Small VM | 1 vCPU / 1 GB RAM | MCP connector, Nginx, TLS termination | Yes (443 only) |
| Large VM | 8 CPU / 8 GB RAM | Hermes Agent execution engine | No (internal only) |

**Why this split?**
Hermes is resource-intensive — it runs an autonomous agent with tools, memory, and web access. The small VM only needs to handle lightweight HTTP translation. Keeping them separate also means the Hermes execution surface is never directly exposed to the internet.

---

## How It Works

The connector implements a subset of the [MCP Streamable HTTP transport spec (2025-03-26)](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports).

### MCP Initialization Flow

```
Perplexity                          Connector
    │                                   │
    │── POST /mcp initialize ──────────►│
    │◄─ 200 InitializeResult ───────────│  (with Mcp-Session-Id header)
    │                                   │
    │── POST /mcp tools/list ──────────►│
    │◄─ 200 { tools: [...] } ───────────│
    │                                   │
    │── POST /mcp tools/call ──────────►│
    │         { name, arguments }       │
    │                             ┌─────▼──────────────────────┐
    │                             │  Validate + forward        │
    │                             │  POST /v1/chat/completions  │
    │                             │  → Hermes Agent             │
    │                             └─────┬──────────────────────┘
    │◄─ 200 { content: [...] } ─────────│
```

### Key design decisions

- **Stateless sessions** — `Mcp-Session-Id: stateless-v1` is returned on initialize. No Redis or DB needed for v1.
- **API Key auth only** — OAuth is intentionally skipped for v1. Perplexity supports API Key natively; it's simpler and less brittle.
- **Narrow tool surface** — Only 3 tools are exposed. No raw shell access or arbitrary execution is passed to Hermes.
- **Strict input validation** — Tool arguments are validated before hitting Hermes, using Pydantic models.
- **Async throughout** — `httpx.AsyncClient` is used for all Hermes calls so the FastAPI event loop never blocks.

---

## MCP Tools

Perplexity will see these three tools after connecting:

### `hermes_run_task`
Runs a general-purpose autonomous task on Hermes.

```json
{
  "task": "Summarize the last 3 commits in the anuntatech-migration repo and identify any blockers",
  "max_tokens": 2048
}
```

### `hermes_research`
Ask Hermes to research a topic and return a structured summary or detailed report.

```json
{
  "topic": "Azure subscription-to-subscription migration blockers for SQL Server 2019",
  "depth": "detailed"
}
```

`depth` accepts `"quick"` (default) or `"detailed"`.

### `hermes_status`
Checks if the Hermes agent is reachable and responding. Useful for debugging connectivity.

```json
{}
```

**Returns:** `Hermes agent is ONLINE. Available models: hermes` or an error message with the failure reason.

---

## Prerequisites

### Small VM (MCP Connector)
- Ubuntu 22.04 or 24.04
- Python 3.11+
- Nginx
- A domain name pointed at this VM's public IP
- Port 443 open in OCI Security List

### Large VM (Hermes Agent)
- Ubuntu 22.04 or 24.04 (or any Linux/macOS/WSL2 Hermes supports)
- Hermes Agent installed (`curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`)
- Port 8642 open **only to the small VM's private IP** in OCI Security List
- Sufficient RAM for your chosen LLM provider (8 GB recommended minimum)

---

## Project Structure

```
perplexity-hermes-mcp/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, /mcp POST+GET, /health
│   ├── mcp_protocol.py    # MCP JSON-RPC types and response builders
│   ├── auth.py            # API key validation (X-API-Key + Bearer)
│   ├── hermes_client.py   # Async HTTP client → Hermes /v1/chat/completions
│   ├── tools.py           # Tool catalog (schemas) + tool executor
│   └── models.py          # Shared Pydantic models
├── nginx/
│   └── mcp.conf           # Nginx reverse proxy with Streamable HTTP headers
├── systemd/
│   └── perplexity-hermes-mcp.service  # Systemd unit file
├── .env.example           # Config template — 3 required values
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Installation

Run these commands on the **small VM** (1 vCPU / 1 GB):

```bash
# Clone the repo
git clone https://github.com/youngsterjaidev/perplexity-hermes-mcp
cd perplexity-hermes-mcp

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Configuration

```bash
cp .env.example .env
nano .env
```

```env
# URL of Hermes API server on the large VM (internal OCI network IP)
HERMES_BASE_URL=http://10.0.0.2:8642/v1

# Must match API_SERVER_KEY in ~/.hermes/.env on the Hermes VM
HERMES_API_KEY=your-hermes-api-key

# Key you will paste into Perplexity when adding the custom connector
CONNECTOR_API_KEY=your-perplexity-connector-key

# Optional — defaults shown
HOST=0.0.0.0
PORT=8000
HERMES_TIMEOUT=120
```

> ⚠️ **Never commit `.env` to Git.** It is already in `.gitignore`.

---

## Running the Server

### Development

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Production (direct, no systemd)

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

> Use `--workers 1` only. The connector is stateless and lightweight; multiple workers add complexity without benefit on a 1 GB VM.

---

## Testing the MCP Endpoint

Run these `curl` tests locally to verify each MCP method works before connecting Perplexity.

### Health check (no auth)

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","service":"perplexity-hermes-mcp"}
```

### MCP initialize

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: your-connector-key' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    }
  }' | python3 -m json.tool
```

**Expected response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": {"tools": {"listChanged": false}},
    "serverInfo": {"name": "perplexity-hermes-mcp", "version": "0.1.0"}
  }
}
```

### MCP tools/list

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: your-connector-key' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | python3 -m json.tool
```

### MCP tools/call — hermes_status

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: your-connector-key' \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "hermes_status",
      "arguments": {}
    }
  }' | python3 -m json.tool
```

### Test auth rejection

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
# Expected: 401 Unauthorized
```

---

## Production Deployment

### Systemd Service

Install and start the systemd service on the small VM:

```bash
# Copy the unit file
sudo cp systemd/perplexity-hermes-mcp.service /etc/systemd/system/

# Edit User= and WorkingDirectory= if your user is not 'ubuntu'
sudo nano /etc/systemd/system/perplexity-hermes-mcp.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now perplexity-hermes-mcp

# Check status
sudo systemctl status perplexity-hermes-mcp

# View logs
sudo journalctl -u perplexity-hermes-mcp -f
```

### Nginx + TLS

```bash
# Install Nginx and Certbot
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

# Copy config (edit domain name first)
sudo cp nginx/mcp.conf /etc/nginx/sites-available/mcp
nano /etc/nginx/sites-available/mcp  # replace mcp.yourdomain.com

sudo ln -s /etc/nginx/sites-available/mcp /etc/nginx/sites-enabled/mcp
sudo nginx -t
sudo systemctl reload nginx

# Get TLS certificate
sudo certbot --nginx -d mcp.yourdomain.com

# Verify HTTPS
curl https://mcp.yourdomain.com/health
```

> Certbot auto-renews via a systemd timer. No manual renewal needed.

---

## Connecting Perplexity

Once the server is running behind HTTPS:

1. Open **Perplexity** → Settings → **Connectors**
2. Click **Add custom connector**
3. Fill in:
   - **URL**: `https://mcp.yourdomain.com/mcp`
   - **Transport**: `Streamable HTTP`
   - **Auth**: `API Key`
   - **API Key value**: your `CONNECTOR_API_KEY` from `.env`
4. Click **Add**
5. Perplexity will probe `POST /mcp` with `initialize` — if it succeeds, the connector shows as connected.

You can now ask Perplexity things like:
- *"Use Hermes to research Azure cost optimization strategies for OCI migration"*
- *"Run a task on Hermes to summarize the latest commits in my migration repo"*
- *"Check if Hermes is online"*

---

## Hermes Agent Setup

On the **large VM** (8 CPU / 8 GB):

### Install Hermes

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

### Configure API Server

Edit `~/.hermes/.env`:

```env
API_SERVER_ENABLED=true
API_SERVER_KEY=your-strong-hermes-api-key
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
```

### Start Hermes

```bash
hermes gateway
```

Verify it is running from the small VM:

```bash
# Run this on the small VM
curl -H "Authorization: Bearer your-hermes-api-key" \
  http://10.0.0.2:8642/v1/models
```

---

## OCI Network Security

Apply these rules in the OCI Console under **Networking → VCN → Security Lists**:

### Small VM (MCP Connector) — Ingress rules

| Protocol | Port | Source | Purpose |
|---|---|---|---|
| TCP | 443 | `0.0.0.0/0` | HTTPS (Perplexity + Certbot) |
| TCP | 80 | `0.0.0.0/0` | HTTP (Certbot ACME challenge only) |
| TCP | 22 | Your IP | SSH |

### Large VM (Hermes) — Ingress rules

| Protocol | Port | Source | Purpose |
|---|---|---|---|
| TCP | 8642 | Small VM private IP | Hermes API |
| TCP | 22 | Your IP | SSH |

> ❌ **Do NOT expose port 8642 to `0.0.0.0/0`.** Hermes has terminal and file tools — unrestricted access means full remote code execution.

---

## Security Considerations

| Risk | Mitigation |
|---|---|
| Unauthorized MCP access | `CONNECTOR_API_KEY` enforced on every request in `auth.py` |
| Hermes exposed to internet | Bind to internal IP; OCI Security List restricts port 8642 to small VM only |
| Arbitrary shell injection via tools | Only 3 narrow tools exposed; arguments validated via Pydantic before Hermes call |
| Secret leakage | `.env` in `.gitignore`; never committed |
| Long-running task abuse | `HERMES_TIMEOUT` env var caps execution time (default 120s) |
| Oversized request bodies | Nginx `client_max_body_size 1m` enforced in `nginx/mcp.conf` |

**Recommended additions for hardening (beyond v1):**
- Rate limiting on `/mcp` in Nginx (`limit_req_zone`)
- Request logging with IP for audit trail
- Fail2ban on 401 patterns
- Separate non-root system user for the connector service

---

## Troubleshooting

### Perplexity shows `[FETCHER_HTML_STATUS_CODE_ERROR]`

This means Perplexity reached your server but got an unexpected response.

- Confirm the URL is `https://yourdomain.com/mcp`, not the root `/`.
- Confirm `POST /mcp` returns valid JSON-RPC, not HTML or plain text.
- Check Nginx is proxying to port 8000, not returning its default page.

```bash
curl -v -X POST https://mcp.yourdomain.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: your-key' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

### Connector shows 401 Unauthorized

- Check the API key in Perplexity matches `CONNECTOR_API_KEY` in `.env` exactly.
- Check that Perplexity is sending it as `X-API-Key`, not in a different header. If needed, `auth.py` also accepts `Authorization: Bearer <key>`.

### `hermes_status` returns OFFLINE

- SSH into the small VM and test the internal Hermes connection directly:
  ```bash
  curl -H "Authorization: Bearer your-hermes-key" http://10.0.0.2:8642/v1/models
  ```
- Check OCI Security List — port 8642 must allow the small VM's private IP.
- Verify Hermes gateway is running on the large VM: `hermes status` or `ps aux | grep hermes`.

### FastAPI app not starting

```bash
source venv/bin/activate
python -c "from app.main import app; print('OK')"
sudo journalctl -u perplexity-hermes-mcp -n 50
```

---

## Roadmap

- [ ] **v0.2** — Add `hermes_file_job` tool for file/text processing tasks
- [ ] **v0.2** — Add `hermes_code_review` tool for code analysis via Hermes
- [ ] **v0.3** — Async job queue with polling (`hermes_submit_task` + `hermes_get_result`)
- [ ] **v0.3** — Redis-backed session store for stateful multi-turn MCP sessions
- [ ] **v0.4** — Nginx rate limiting and structured request/response audit logging
- [ ] **v1.0** — OAuth 2.0 support for ChatGPT MCP compatibility
- [ ] **v1.0** — Docker Compose packaging for one-command deployment

---

## License

MIT — use freely, break responsibly.

---

*Built by [Jai Dev](https://github.com/youngsterjaidev) · Powered by [Hermes Agent](https://hermes-agent.nousresearch.com/) · Protocol: [Model Context Protocol](https://modelcontextprotocol.io/)*
