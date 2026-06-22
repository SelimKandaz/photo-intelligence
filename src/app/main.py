from __future__ import annotations

import mimetypes
from pathlib import Path

from app.config import load_settings
from app.db.connection import Database
from app.db.migrations import run_migrations
from app.db.repository import Repository
from app.feedback.manager import FeedbackManager
from app.ocr.image_io import configure_tesseract_executable
from app.search.engine import SearchEngine
from app.services.export import serial_rows_csv
from app.templates import render_index
from app.workers.local_worker import LocalWorker

try:
    import uvicorn  # type: ignore
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, Response
except Exception as exc:  # pragma: no cover - exercised by manual startup.
    uvicorn = None
    FastAPI = None
    HTTPException = None
    Request = None
    HTMLResponse = None
    Response = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None


settings = load_settings()
database = Database(settings.database_url)
with database.session() as conn:
    run_migrations(conn)


def create_app():
    if FastAPI is None:
        raise RuntimeError(
            "FastAPI dependencies are not installed. Run: python -m pip install -r requirements.txt"
        ) from FASTAPI_IMPORT_ERROR

    app = FastAPI(title="Photo Intelligence / Inventory Evidence Search")
    worker = LocalWorker(database, settings)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return render_index(settings)

    @app.get("/api/health")
    def health():
        with database.session() as conn:
            repo = Repository(conn)
            photos = repo.list_photos(limit=1)
            schema_version = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
        tesseract_path = configure_tesseract_executable()
        return {
            "status": "ok",
            "database_url": settings.database_url,
            "sample_photo_count": len(photos),
            "extractor": settings.extractor_name,
            "extractor_version": settings.extractor_version,
            "schema_version": int(schema_version["version"] if schema_version else 0),
            "tesseract_found": bool(tesseract_path),
            "tesseract_cmd": tesseract_path or "",
        }

    @app.post("/api/import")
    async def import_folder(request: Request):
        payload = await request.json()
        source_path = payload.get("source_path") or str(settings.import_folder)
        backend = payload.get("backend") or settings.ocr_backend
        force = bool(payload.get("force", False))
        if not Path(source_path).exists():
            raise HTTPException(status_code=400, detail=f"Folder does not exist: {source_path}")
        job_id = worker.start_import(source_path, force=force, backend=backend)
        return {"job_id": job_id}

    @app.get("/api/jobs")
    def list_jobs():
        return worker.list_jobs()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = worker.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.get("/api/photos")
    def list_photos(limit: int = 100, offset: int = 0):
        with database.session() as conn:
            repo = Repository(conn)
            return {"items": repo.list_photos(limit=limit, offset=offset)}

    @app.get("/api/photos/{photo_id}")
    def photo_detail(photo_id: str):
        with database.session() as conn:
            repo = Repository(conn)
            item = repo.get_photo(photo_id)
            if not item:
                raise HTTPException(status_code=404, detail="Photo not found")
            return item

    @app.get("/media/thumb/{photo_id}")
    def thumbnail(photo_id: str):
        with database.session() as conn:
            repo = Repository(conn)
            item = repo.get_photo(photo_id)
            if not item or not item.get("thumbnail_path"):
                raise HTTPException(status_code=404, detail="Thumbnail not found")
            path = Path(item["thumbnail_path"])
            if not path.exists():
                raise HTTPException(status_code=404, detail="Thumbnail file missing")
            return Response(content=path.read_bytes(), media_type="image/jpeg")

    @app.get("/media/photo/{photo_id}")
    def full_photo(photo_id: str):
        with database.session() as conn:
            repo = Repository(conn)
            item = repo.get_photo(photo_id)
            if not item:
                raise HTTPException(status_code=404, detail="Photo not found")
            path = Path(item.get("storage_path") or item.get("path") or item.get("original_path") or "")
            if not path.exists() or not path.is_file():
                raise HTTPException(status_code=404, detail="Photo file missing")
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return FileResponse(path, media_type=media_type, filename=path.name)

    @app.get("/api/search")
    def search(q: str, limit: int = 50, mode: str = "fast"):
        with database.session() as conn:
            repo = Repository(conn)
            try:
                return SearchEngine(repo).search(q, limit=limit, mode=mode)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/search-click")
    async def search_click(request: Request):
        payload = await request.json()
        with database.session() as conn:
            repo = Repository(conn)
            click_id = repo.record_search_click(
                payload["photo_id"],
                query_id=payload.get("query_id"),
                result_rank=payload.get("rank"),
                action=payload.get("action", "open"),
                query_fingerprint=payload.get("query_fingerprint", ""),
            )
            return {"click_id": click_id}

    @app.get("/api/export/serial-rows")
    def export_serial_rows():
        with database.session() as conn:
            repo = Repository(conn)
            csv_text = serial_rows_csv(repo)
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=serial_rows_printed_vs_barcode_audit.csv"},
        )

    @app.post("/api/photos/{photo_id}/feedback")
    async def add_feedback(photo_id: str, request: Request):
        payload = await request.json()
        with database.session() as conn:
            repo = Repository(conn)
            if not repo.get_photo(photo_id):
                raise HTTPException(status_code=404, detail="Photo not found")
            return FeedbackManager(repo).add_feedback(
                photo_id,
                payload.get("rating", "needs_review"),
                note=payload.get("note", ""),
                query_id=payload.get("query_id"),
                query_fingerprint=payload.get("query_fingerprint", ""),
                result_rank=payload.get("rank"),
            )

    @app.post("/api/photos/{photo_id}/corrections")
    async def add_correction(photo_id: str, request: Request):
        payload = await request.json()
        with database.session() as conn:
            repo = Repository(conn)
            if not repo.get_photo(photo_id):
                raise HTTPException(status_code=404, detail="Photo not found")
            return FeedbackManager(repo).add_correction(
                photo_id,
                payload["entity_type"],
                payload["corrected_value"],
                old_value=payload.get("old_value", ""),
                note=payload.get("note", ""),
                corrected_by=payload.get("corrected_by", ""),
            )

    @app.get("/api/review-queue")
    def review_queue(status: str = "open", limit: int = 100):
        with database.session() as conn:
            repo = Repository(conn)
            return {"items": repo.list_review_queue(status=status, limit=limit)}

    @app.post("/api/review-queue/{review_item_id}/resolve")
    async def resolve_review(review_item_id: str, request: Request):
        payload = await request.json()
        with database.session() as conn:
            repo = Repository(conn)
            item = repo.resolve_review_item(
                review_item_id,
                payload.get("action", "resolved"),
                note=payload.get("note", ""),
            )
            if not item:
                raise HTTPException(status_code=404, detail="Review item not found")
            return item

    @app.get("/api/failed-files")
    def failed_files(limit: int = 100):
        with database.session() as conn:
            return {"items": Repository(conn).list_failed_files(limit=limit)}

    @app.post("/api/failed-files/{failed_file_id}/retry")
    def retry_failed_file(failed_file_id: str):
        with database.session() as conn:
            repo = Repository(conn)
            failed = repo.get_failed_file(failed_file_id)
            if not failed:
                raise HTTPException(status_code=404, detail="Failed file not found")
            repo.mark_failed_file_retry(failed_file_id)
        path = Path(failed["path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"File no longer exists: {path}")
        job_id = worker.start_import(str(path.parent), force=True, backend=settings.ocr_backend)
        return {"job_id": job_id, "retry_path": str(path)}

    return app


app = create_app() if FastAPI is not None else None


def main() -> int:
    if uvicorn is None or app is None:
        raise SystemExit("FastAPI dependencies are not installed. Run: python -m pip install -r requirements.txt")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
