from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from driftshield.api.auth import require_api_key
from driftshield.api.dependencies import get_db
from driftshield.dashboard.integrity import IntegrityDashboardService

router = APIRouter()


@router.get("/api/dashboard/integrity")
def get_integrity_dashboard(
    api_key: str = Depends(require_api_key),
    db: DBSession = Depends(get_db),
) -> dict[str, dict[str, object]]:
    del api_key
    return IntegrityDashboardService(db).build_dashboard_payload()
