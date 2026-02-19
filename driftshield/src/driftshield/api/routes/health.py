from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "version": "0.1.0",
    }
