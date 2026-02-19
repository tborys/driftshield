from fastapi import FastAPI

from driftshield.api.routes.health import router as health_router
from driftshield.api.routes.ingest import router as ingest_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="DriftShield",
        description="AI Decision Forensics API",
        version="0.1.0",
    )
    app.include_router(health_router)
    app.include_router(ingest_router)
    return app
