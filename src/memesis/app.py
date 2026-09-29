"""FastAPI application — health endpoint + JSON API for product frontend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from memesis.config import settings
from memesis.db.session import make_engine, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.logging_config import configure_logging
from memesis.web.api import api_router


def create_app(database_url: str | None = None) -> FastAPI:
    configure_logging(settings.log_level)
    repository = SqlGraphRepository(
        make_session_factory(make_engine(database_url or settings.database_url))
    )
    app = FastAPI(title="Memesis Market Intelligence API", version="0.1.0")

    # Attach repository to app.state
    app.state.repository = repository

    # Enable CORS for Next.js development server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def health() -> dict[str, object]:
        return repository.health()

    # Mount JSON API router
    app.include_router(api_router)

    return app


app = create_app()
