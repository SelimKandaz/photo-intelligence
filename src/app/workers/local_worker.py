from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db.connection import Database
from app.db.migrations import run_migrations
from app.db.repository import Repository
from app.ingestion.importer import ImportService


@dataclass
class JobState:
    id: str
    kind: str
    status: str = "queued"
    progress: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str = ""


class LocalWorker:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.jobs: dict[str, JobState] = {}
        self.lock = threading.Lock()
        with self.database.session() as conn:
            run_migrations(conn)
            Repository(conn).mark_interrupted_import_jobs()

    def start_import(self, source_path: str, *, force: bool = False, backend: str | None = None) -> str:
        job_id = uuid.uuid4().hex
        state = JobState(id=job_id, kind="import")
        with self.lock:
            self.jobs[job_id] = state
        with self.database.session() as conn:
            run_migrations(conn)
            Repository(conn).create_import_job(
                job_id,
                source_path,
                backend=backend or self.settings.ocr_backend,
                force=force,
                storage_mode=self.settings.storage_mode,
            )

        thread = threading.Thread(
            target=self._run_import,
            args=(job_id, source_path, force, backend),
            daemon=True,
        )
        thread.start()
        return job_id

    def _run_import(self, job_id: str, source_path: str, force: bool, backend: str | None) -> None:
        self._update(job_id, status="running")
        self._update_db_job(job_id, status="running")
        service = ImportService(self.database, self.settings)
        try:
            result = service.import_folder(
                Path(source_path),
                force=force,
                backend=backend,
                job_id=job_id,
                progress_callback=lambda msg: self._append_progress(job_id, msg),
            )
            self._update(job_id, status="completed", result=result)
            self._update_db_job(job_id, status="completed", result=result)
        except Exception as exc:
            error = f"{exc}\n{traceback.format_exc()}"
            self._update(job_id, status="failed", error=error)
            self._update_db_job(job_id, status="failed", error=error)

    def _append_progress(self, job_id: str, message: str) -> None:
        with self.lock:
            state = self.jobs[job_id]
            state.progress.append(message)
            state.progress = state.progress[-200:]
            progress_text = "\n".join(state.progress[-25:])
        self._update_db_job(job_id, progress_text=progress_text)

    def _update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.lock:
            state = self.jobs[job_id]
            if status:
                state.status = status
            if result is not None:
                state.result = result
            if error is not None:
                state.error = error

    def _update_db_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress_text: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.database.session() as conn:
            Repository(conn).update_import_job(
                job_id,
                status=status,
                progress_text=progress_text,
                result=result,
                error=error,
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            state = self.jobs.get(job_id)
            if state:
                return {
                    "id": state.id,
                    "kind": state.kind,
                    "status": state.status,
                    "progress": list(state.progress),
                    "result": state.result,
                    "error": state.error,
                }
        with self.database.session() as conn:
            job = Repository(conn).get_import_job(job_id)
            if not job:
                return None
            return {
                "id": job["id"],
                "kind": job["kind"],
                "status": job["status"],
                "progress": str(job.get("progress_text") or "").splitlines(),
                "result": job.get("result_json"),
                "error": job.get("error") or "",
            }

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.database.session() as conn:
            db_jobs = Repository(conn).list_import_jobs(limit=50)
        memory_by_id = {}
        with self.lock:
            for state in self.jobs.values():
                memory_by_id[state.id] = {
                    "id": state.id,
                    "kind": state.kind,
                    "status": state.status,
                    "progress": list(state.progress[-5:]),
                    "result": state.result,
                    "error": state.error,
                }
        items = []
        for job in db_jobs:
            item = {
                "id": job["id"],
                "kind": job["kind"],
                "status": job["status"],
                "progress": str(job.get("progress_text") or "").splitlines()[-5:],
                "result": job.get("result_json"),
                "error": job.get("error") or "",
            }
            item.update(memory_by_id.get(job["id"], {}))
            items.append(item)
        return items
