import os
from fastapi import Header, HTTPException, status
from dotenv import load_dotenv

load_dotenv()

CONNECTOR_API_KEY = os.getenv("CONNECTOR_API_KEY", "")


def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    """
    Accepts the key in either:
      - X-API-Key header  (Perplexity custom connector sends it here)
      - Authorization: Bearer <key>
    """
    if not CONNECTOR_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CONNECTOR_API_KEY is not configured on the server.",
        )

    # Check X-API-Key header first
    if x_api_key and x_api_key == CONNECTOR_API_KEY:
        return

    # Check Authorization: Bearer <key>
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == CONNECTOR_API_KEY:
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key.",
    )
