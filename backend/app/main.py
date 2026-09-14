from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.health import router as health_router
from app.api.scans import router as scans_router
from app.api.volumes import router as volumes_router
from app.api.session import router as session_router
from app.api.snapshots import router as snapshots_router
from app.api.candidates import router as candidates_router
from app.core.config import APP_NAME, APP_VERSION, FRONTEND_DIST, HOST, PORT


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[HOST])
app.include_router(health_router)
app.include_router(session_router)
app.include_router(scans_router)
app.include_router(volumes_router)
app.include_router(snapshots_router)
app.include_router(candidates_router)


@app.middleware("http")
async def require_local_host(request: Request, call_next):
    if request.headers.get("host", "").lower() != f"{HOST}:{PORT}":
        return PlainTextResponse("Invalid host", status_code=400)
    return await call_next(request)

if FRONTEND_DIST.is_dir():
    from fastapi.responses import FileResponse

    @app.get("/{page}", include_in_schema=False)
    def frontend_page(page: str) -> FileResponse:
        if page not in {"dashboard", "analysis", "large-items", "status", "history", "recommendations", "settings"}:
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        return FileResponse(FRONTEND_DIST / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="web")
else:
    @app.get("/")
    def frontend_not_built() -> JSONResponse:
        return JSONResponse({"detail": "Web UI is not built. Run setup.bat first."}, status_code=503)
