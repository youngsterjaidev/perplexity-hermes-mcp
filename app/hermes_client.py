import os
import httpx
from dotenv import load_dotenv
from app.models import HermesTaskRequest, HermesTaskResult

load_dotenv()

HERMES_BASE_URL = os.getenv("HERMES_BASE_URL", "http://localhost:8642/v1")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
HERMES_TIMEOUT = float(os.getenv("HERMES_TIMEOUT", "120"))


async def call_hermes(task: HermesTaskRequest) -> HermesTaskResult:
    """
    Sends a prompt to Hermes via its OpenAI-compatible /chat/completions endpoint.
    Returns a normalized HermesTaskResult.
    """
    headers = {
        "Authorization": f"Bearer {HERMES_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "hermes",
        "messages": [{"role": "user", "content": task.prompt}],
        "max_tokens": task.max_tokens,
    }

    async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as client:
        response = await client.post(
            f"{HERMES_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

    data = response.json()
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})

    return HermesTaskResult(
        content=message.get("content", ""),
        model=data.get("model"),
        finish_reason=choice.get("finish_reason"),
    )


async def check_hermes_health() -> dict:
    """
    Pings the Hermes API to check if the agent is reachable and returning models.
    Returns a dict with status and details.
    """
    headers = {"Authorization": f"Bearer {HERMES_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{HERMES_BASE_URL}/models",
                headers=headers,
            )
            response.raise_for_status()
            models = response.json()
        return {
            "status": "online",
            "models_available": [m.get("id") for m in models.get("data", [])],
        }
    except Exception as e:
        return {"status": "offline", "error": str(e)}
