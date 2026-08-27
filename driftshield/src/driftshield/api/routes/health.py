from fastapi import APIRouter

from driftshield import __version__

router = APIRouter()


@router.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "version": __version__,
    }
