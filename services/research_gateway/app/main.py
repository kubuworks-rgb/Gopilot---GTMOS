from __future__ import annotations

from fastapi import FastAPI, HTTPException

from services.research_gateway.app.agent_reach import agent_reach_health
from services.research_gateway.app.schemas import AdapterHealth, FetchRequest
from services.research_gateway.app.security.url_policy import UnsafeUrlError, validate_public_url


app = FastAPI(title="GTM Research Gateway", version="0.1.0")


@app.get("/internal/v1/health", response_model=AdapterHealth)
async def health() -> AdapterHealth:
    return await agent_reach_health()


@app.post("/internal/v1/fetch/validate")
def validate_fetch(request: FetchRequest) -> dict[str, str]:
    try:
        url = validate_public_url(str(request.url))
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "allowed", "url": url}
