# Perplexity → Hermes MCP Connector

A lightweight Python FastAPI MCP server that bridges [Perplexity AI custom remote connectors](https://www.perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors) to a self-hosted [Hermes Agent](https://hermes-agent.nousresearch.com/) over **Streamable HTTP transport**.

## Architecture

```
Perplexity
    │  HTTPS (Streamable HTTP MCP)
    ▼
┌──────────────────────────────┐
│  OCI Small VM  (1 vCPU/1 GB) │
│  mcp.yourdomain.com          │
│  Nginx + FastAPI MCP Server  │
└────────────┬─────────────────┘
             │  Internal HTTP (API Key)
             ▼
┌──────────────────────────────┐
│  OCI Large VM  (8 CPU/8 GB)  │
│  Hermes Agent API Server     │
│  http://10.x.x.x:8642        │
└──────────────────────────────┘
```

## Available MCP Tools

| Tool | Description |
|---|---|
| `hermes_run_task` | Run a general task on the Hermes agent |
| `hermes_research` | Ask Hermes to research a topic and return a summary |
| `hermes_status` | Check if the Hermes agent is online and healthy |

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/youngsterjaidev/perplexity-hermes-mcp
cd perplexity-hermes-mcp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in:
- `HERMES_BASE_URL` — internal URL of your Hermes API server (e.g. `http://10.0.0.2:8642/v1`)
- `HERMES_API_KEY` — the `API_SERVER_KEY` you set in Hermes
- `CONNECTOR_API_KEY` — a strong secret you will give to Perplexity

### 3. Run locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Test it:
```bash
curl -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: your-connector-key' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

### 4. Deploy with systemd

```bash
sudo cp systemd/perplexity-hermes-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now perplexity-hermes-mcp
```

### 5. Set up Nginx + TLS

See `nginx/mcp.conf` — replace `mcp.yourdomain.com` with your actual domain, then:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d mcp.yourdomain.com
```

### 6. Add to Perplexity

1. Go to Perplexity Settings → Connectors → Add custom
2. Set URL: `https://mcp.yourdomain.com/mcp`
3. Transport: `Streamable HTTP`
4. Auth: `API Key` → enter your `CONNECTOR_API_KEY`
5. Click Add

## Hermes Setup (Large VM)

In `~/.hermes/.env` on the 8 GB VM:
```env
API_SERVER_ENABLED=true
API_SERVER_KEY=your-strong-hermes-key
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
```

Then run:
```bash
hermes gateway
```

> **Security**: Restrict OCI Security List on the Hermes VM so port 8642 is only reachable from the small VM's private IP — not the public internet.

## Project Structure

```
perplexity-hermes-mcp/
├── app/
│   ├── main.py            # FastAPI app + /mcp endpoint
│   ├── mcp_protocol.py    # MCP JSON-RPC request/response models
│   ├── auth.py            # API key validation
│   ├── hermes_client.py   # HTTP client for Hermes API
│   ├── tools.py           # Tool registry and executor
│   └── models.py          # Shared Pydantic models
├── nginx/
│   └── mcp.conf           # Nginx reverse proxy config
├── systemd/
│   └── perplexity-hermes-mcp.service
├── .env.example
├── requirements.txt
└── README.md
```

## License

MIT
