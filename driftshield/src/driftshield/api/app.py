import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from driftshield.api.routes.health import router as health_router
from driftshield.api.routes.ingest import router as ingest_router
from driftshield.api.routes.reports import router as reports_router
from driftshield.api.routes.sessions import router as sessions_router
from driftshield.api.security import RequestSizeLimitMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="DriftShield",
        description="AI Decision Forensics API",
        version="0.1.0",
    )
    app.add_middleware(RequestSizeLimitMiddleware)
    app.include_router(health_router)
    app.include_router(ingest_router)
    app.include_router(sessions_router)
    app.include_router(reports_router)

    # Serve React static files in production
    # When installed as a package, __file__ points to site-packages.
    # Use STATIC_DIR env var (set in Docker) or fall back to relative path for local dev.
    static_dir = Path(os.environ.get("STATIC_DIR", Path(__file__).parent.parent.parent.parent / "static"))
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

        @app.get("/{path:path}")
        async def serve_spa(path: str):
            """Serve React SPA. All non-API routes fall through to index.html."""
            file_path = static_dir / path
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(static_dir / "index.html"))

    return app
