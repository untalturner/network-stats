from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

from app.api.routes import router
from app.database import SessionLocal
from app.services.discovery import recover_interrupted_discovery_scans
from app.services.scheduler import monitoring_scheduler


logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        recover_interrupted_discovery_scans(db)

    monitoring_scheduler.start()

    try:
        yield
    finally:
        monitoring_scheduler.shutdown()


app = FastAPI(
    title="Network Stats",
    description="Self-hosted network observability platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")

frontend_dir = Path(
    os.getenv("NETWORK_STATS_FRONTEND_DIR", "/app/frontend/dist")
)

if frontend_dir.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=frontend_dir, html=True),
        name="frontend",
    )
