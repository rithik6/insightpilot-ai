from fastapi import APIRouter, HTTPException, Request

from app.services.readiness import dependencies_ready

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness(request: Request) -> dict[str, str]:
    if not dependencies_ready(request.app.state.settings):
        raise HTTPException(status_code=503, detail="Dependencies unavailable.")
    return {"status": "ready"}
