from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audit_tools import AuditTools
from .config import Settings
from .db import Database
from .ingest import Ingestor
from .ollama_client import OllamaClient
from .qdrant_store import QdrantStore
from .rag import RAGEngine


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parents[2]
STATIC_ROOT = APP_ROOT / "static"


@dataclass(slots=True)
class Services:
    settings: Settings
    database: Database
    ollama: OllamaClient
    qdrant: QdrantStore
    ingestor: Ingestor
    rag_engine: RAGEngine
    audit_tools: AuditTools


class AskRequest(BaseModel):
    question: str
    top_k: int | None = None


def build_services(settings: Settings | None = None) -> Services:
    active_settings = settings or Settings.from_env(PROJECT_ROOT)
    database = Database(active_settings.app_db_path)
    ollama = OllamaClient(active_settings.ollama_base_url, active_settings.llm_model, active_settings.embedding_model)
    qdrant = QdrantStore(active_settings.qdrant_url, active_settings.qdrant_collection)
    ingestor = Ingestor(active_settings, database, ollama, qdrant)
    rag_engine = RAGEngine(active_settings, ollama, qdrant)
    audit_tools = AuditTools(database)
    return Services(
        settings=active_settings,
        database=database,
        ollama=ollama,
        qdrant=qdrant,
        ingestor=ingestor,
        rag_engine=rag_engine,
        audit_tools=audit_tools,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    services = build_services(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services.database.ensure_schema()
        yield

    app = FastAPI(title="PrivateAI POC", version="0.2.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")
    app.state.services = services

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/health")
    def health() -> dict[str, object]:
        services: Services = app.state.services
        db_stats = services.database.get_index_stats()
        return {
            "status": "ok",
            "ollama": services.ollama.health(),
            "qdrant": services.qdrant.health(),
            "models": {
                "llm_model": services.settings.llm_model,
                "embedding_model": services.settings.embedding_model,
            },
            **db_stats,
        }

    @app.get("/status")
    @app.get("/stats")
    def stats() -> dict[str, object]:
        services: Services = app.state.services
        stats_payload = services.database.get_stats()
        stats_payload.update(
            {
                "settings": services.settings.public_status(),
                "ollama": services.ollama.health(),
                "qdrant": services.qdrant.health(),
                "failed_files": services.database.list_failed_files(),
            }
        )
        return stats_payload

    @app.get("/sources")
    def sources(limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, object]:
        services: Services = app.state.services
        return {"items": services.database.list_files(limit=limit)}

    @app.post("/ingest")
    def ingest(force: bool = False) -> dict[str, object]:
        services: Services = app.state.services
        try:
            return services.ingestor.ingest(force=force)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/ask")
    def ask(request: AskRequest) -> dict[str, object]:
        services: Services = app.state.services
        try:
            return services.rag_engine.ask(request.question, top_k=request.top_k)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/audit/serial-conflicts")
    def audit_serial_conflicts() -> dict[str, object]:
        services: Services = app.state.services
        return {"items": services.audit_tools.serial_conflicts()}

    @app.get("/audit/duplicate-serials")
    def audit_duplicate_serials() -> dict[str, object]:
        services: Services = app.state.services
        return {"items": services.audit_tools.duplicate_serials()}

    @app.get("/audit/customer-followups")
    def audit_customer_followups() -> dict[str, object]:
        services: Services = app.state.services
        return {"items": services.audit_tools.customer_followups()}

    @app.get("/audit/failed-reports")
    def audit_failed_reports() -> dict[str, object]:
        services: Services = app.state.services
        return {"items": services.audit_tools.failed_reports()}

    @app.get("/audit/po-so-summary")
    def audit_po_so_summary(query: str = Query(..., min_length=1)) -> dict[str, object]:
        services: Services = app.state.services
        return services.audit_tools.po_so_summary(query)

    return app


app = create_app()
