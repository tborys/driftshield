import os

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_PLACEHOLDER_API_KEYS = {
    "",
    "changeme",
    "dev-api-key",
    "dev-key",
    "your-api-key-here",
    "replace-with-a-long-random-api-key",
}


def get_expected_api_key() -> str:
    api_key = os.environ.get("API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="API key is not configured")

    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if environment == "production" and api_key in _PLACEHOLDER_API_KEYS:
        raise HTTPException(status_code=503, detail="API key is not safely configured for production")

    return api_key


def get_max_request_bytes() -> int:
    raw = os.environ.get("MAX_REQUEST_BYTES", str(25 * 1024 * 1024)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("MAX_REQUEST_BYTES must be an integer") from exc

    if value <= 0:
        raise RuntimeError("MAX_REQUEST_BYTES must be positive")
    return value


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.max_request_bytes = get_max_request_bytes()

    async def dispatch(self, request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    return JSONResponse(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        content={"detail": "Invalid Content-Length header"},
                    )
                if declared_size > self.max_request_bytes:
                    return JSONResponse(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        content={"detail": f"Request body exceeds {self.max_request_bytes} bytes"},
                    )

        return await call_next(request)
