from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from driftshield.api.security import get_expected_api_key

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Security(api_key_header)) -> str:
    expected = get_expected_api_key()
    if not api_key or api_key != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    return api_key
