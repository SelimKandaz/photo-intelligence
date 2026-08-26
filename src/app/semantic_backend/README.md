# Optional Semantic Backend

The public desktop application remains the default entry point:

```powershell
python -m app.desktop.main
```

This package adds the optional local semantic backend from the development
prototype. It uses Ollama for embeddings/generation and Qdrant for vector
storage. It does not require a cloud account or an API key.

Run it from `src` after copying `.env.example` to `.env`:

```powershell
python -m app.semantic_backend.main
```

The backend is available at `http://127.0.0.1:8001` by default. Its local
database and source paths come from environment variables. Do not commit
`.env`, company documents, photos, generated databases, logs, or Qdrant
storage. Use synthetic demo data for public examples.

The backend keeps the `detected_entities` SQLite column populated with valid
JSON for every chunk. Empty extraction results use the stable entity schema
defined in `entity_extract.py`.
