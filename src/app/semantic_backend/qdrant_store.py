from __future__ import annotations

import httpx


class QdrantStore:
    def __init__(self, url: str, collection: str, timeout: float = 60.0) -> None:
        self.url = url.rstrip("/")
        self.collection = collection
        self.timeout = timeout

    def health(self) -> dict[str, object]:
        try:
            response = httpx.get(f"{self.url}/collections", timeout=10.0)
            response.raise_for_status()
            payload = response.json()
            collections = payload.get("result", {}).get("collections", [])
            return {"reachable": True, "collections": [item.get("name") for item in collections]}
        except Exception as exc:
            return {"reachable": False, "error": str(exc)}

    def ensure_collection(self, vector_size: int) -> None:
        response = httpx.get(f"{self.url}/collections/{self.collection}", timeout=10.0)
        if response.status_code == 200:
            return
        if response.status_code not in {404}:
            response.raise_for_status()
        create_response = httpx.put(
            f"{self.url}/collections/{self.collection}",
            json={"vectors": {"size": vector_size, "distance": "Cosine"}},
            timeout=self.timeout,
        )
        create_response.raise_for_status()

    def delete_source(self, source_path: str) -> None:
        response = httpx.post(
            f"{self.url}/collections/{self.collection}/points/delete?wait=true",
            json={"filter": {"must": [{"key": "source_path", "match": {"value": source_path}}]}},
            timeout=self.timeout,
        )
        if response.status_code not in {200, 404}:
            response.raise_for_status()

    def upsert(self, points: list[dict[str, object]]) -> None:
        if not points:
            return
        response = httpx.put(
            f"{self.url}/collections/{self.collection}/points?wait=true",
            json={"points": points},
            timeout=self.timeout,
        )
        response.raise_for_status()

    def search(self, vector: list[float], limit: int) -> list[dict[str, object]]:
        response = httpx.post(
            f"{self.url}/collections/{self.collection}/points/search",
            json={"vector": vector, "limit": limit, "with_payload": True},
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json()
        return payload.get("result", [])

    def count_points(self) -> int:
        response = httpx.post(
            f"{self.url}/collections/{self.collection}/points/count",
            json={"exact": True},
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return 0
        response.raise_for_status()
        payload = response.json()
        return int(payload.get("result", {}).get("count", 0))
