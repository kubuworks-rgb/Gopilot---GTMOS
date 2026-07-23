from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.config import settings

settings.validate()

if settings.research_mode == "live":
    from apps.api.app.api.live_routes import router
else:
    from apps.api.app.api.routes import router

app = FastAPI(
    title="GTM Intelligence OS API",
    version="0.1.0",
    description="Evidence-backed account opportunity intelligence.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Demo-User", "X-Workspace-Id"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.research_mode, "service": "api"}
