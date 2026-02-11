"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import database as db
from .routers import analytics, metadata, prices

logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DuckDB on startup, close on shutdown."""
    logger.info("Starting API server, initializing DuckDB...")
    db.get_connection()
    yield
    logger.info("Shutting down, closing DuckDB...")
    db.close_connection()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Noticias Agricolas API",
        description="Brazilian commodity price data — 158 indicators, 24 commodities, 2,200+ locations, 6 years of history.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routers
    app.include_router(metadata.router)
    app.include_router(prices.router)
    app.include_router(analytics.router)

    # Dashboard (lazy import to avoid hard dep on jinja2 at import time)
    try:
        from ..dashboard.router import router as dashboard_router
        app.include_router(dashboard_router)
        # Static files
        static_dir = DASHBOARD_DIR / "static"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    except ImportError:
        logger.warning("Dashboard dependencies not available, skipping dashboard routes")

    @app.get("/", tags=["root"])
    def root():
        return {
            "name": "Noticias Agricolas API",
            "version": "1.0.0",
            "docs": "/docs",
            "endpoints": {
                "metadata": ["/v1/commodities", "/v1/categories", "/v1/locations", "/v1/contracts", "/v1/status"],
                "prices": ["/v1/prices", "/v1/prices/latest", "/v1/prices/timeseries"],
                "analytics": [
                    "/v1/analytics/basis", "/v1/analytics/basis-panel",
                    "/v1/analytics/crush-margin",
                    "/v1/analytics/futures-curve", "/v1/analytics/regional-spread",
                    "/v1/analytics/fx-adjusted", "/v1/analytics/seasonal",
                    "/v1/analytics/rankings",
                ],
                "dashboard": "/dashboard",
            },
        }

    return app


app = create_app()


def main():
    """Entry point for na-api command."""
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "noticiasagricolas_etl.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
