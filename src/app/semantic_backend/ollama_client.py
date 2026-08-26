from __future__ import annotations

from typing import Sequence

import httpx


class OllamaClient:
    def __init__(self, base_url: str, llm_model: str, embedding_model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.llm_model = llm_model
        self.embedding_model = embedding_model
        self.timeout = timeout

    def health(self) -> dict[str, object]:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=10.0)
            response.raise_for_status()
            payload = response.json()
            models = [item.get("name") for item in payload.get("models", [])]
            return {"reachable": True, "models": models}
        except Exception as exc:
            return {"reachable": False, "error": str(exc)}

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.embedding_model, "input": list(texts) if len(texts) > 1 else texts[0]}
        try:
            response = httpx.post(f"{self.base_url}/api/embed", json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            if "embeddings" in data:
                return data["embeddings"]
            if "embedding" in data:
                return [data["embedding"]]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        embeddings: list[list[float]] = []
        for text in texts:
            response = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embedding_model, "prompt": text},
                timeout=self.timeout,
            )
            response.raise_for_status()
            embeddings.append(response.json()["embedding"])
        return embeddings

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        response = httpx.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.llm_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("response", "").strip()
