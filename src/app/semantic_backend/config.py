from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path_value(root: Path, name: str, default: str) -> Path:
    path = Path(os.getenv(name, default))
    return path if path.is_absolute() else root / path


@dataclass(slots=True)
class Settings:
    project_root: Path
    ollama_base_url: str
    llm_model: str
    embedding_model: str
    qdrant_url: str
    qdrant_collection: str
    data_sources_path: Path
    app_db_path: Path
    top_k: int
    max_context_chars: int
    answer_temperature: float
    store_chat_logs: bool

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "Settings":
        root = project_root or Path(__file__).resolve().parents[2]
        _load_dotenv(root / ".env")
        return cls(
            project_root=root,
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            llm_model=os.getenv("LLM_MODEL", "qwen3:14b"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
            qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "photo_intelligence_docs"),
            data_sources_path=_path_value(root, "DATA_SOURCES_PATH", "data_sources"),
            app_db_path=_path_value(root, "APP_DB_PATH", "data/photo_inventory.db"),
            top_k=_env_int("TOP_K", 8),
            max_context_chars=_env_int("MAX_CONTEXT_CHARS", 14000),
            answer_temperature=_env_float("ANSWER_TEMPERATURE", 0.1),
            store_chat_logs=_env_bool("STORE_CHAT_LOGS", False),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "qdrant_collection": self.qdrant_collection,
            "data_sources_path": str(self.data_sources_path),
            "app_db_path": str(self.app_db_path),
            "top_k": self.top_k,
            "max_context_chars": self.max_context_chars,
            "answer_temperature": self.answer_temperature,
            "store_chat_logs": self.store_chat_logs,
        }
