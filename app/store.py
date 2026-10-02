"""Qdrant access and the local embedding models shared by ingestion and query time."""

from __future__ import annotations

import atexit
import threading
import uuid
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.config import Settings, get_settings

DENSE = "dense"
SPARSE = "bm25"
KEYWORD_FIELDS = ("doc_id", "ticker", "doc_type", "section", "chunk_type", "period")
INT_FIELDS = ("fiscal_year",)

_client_lock = threading.Lock()
_client: QdrantClient | None = None


def get_client(s: Settings | None = None) -> QdrantClient:
    """Docker Qdrant when FINSIGHT_QDRANT_URL is set, otherwise an embedded on-disk store (one process at a time)."""
    global _client
    s = s or get_settings()
    with _client_lock:
        if _client is None:
            if s.qdrant_url:
                _client = QdrantClient(url=s.qdrant_url, timeout=60)
            else:
                s.qdrant_path.mkdir(parents=True, exist_ok=True)
                _client = QdrantClient(path=str(s.qdrant_path))
            atexit.register(_client.close)
        return _client


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def naive_collection(s: Settings | None = None) -> str:
    return f"{(s or get_settings()).collection}_naive"


def ensure_collection(client: QdrantClient, name: str, dim: int) -> None:
    if client.collection_exists(name):
        return
    client.create_collection(
        name,
        vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    for f in KEYWORD_FIELDS:
        client.create_payload_index(name, f, models.PayloadSchemaType.KEYWORD)
    for f in INT_FIELDS:
        client.create_payload_index(name, f, models.PayloadSchemaType.INTEGER)


class Embedders:
    """Lazily loaded fastembed models (ONNX). Model files download to the fastembed cache on first use."""

    def __init__(self, s: Settings | None = None):
        self.s = s or get_settings()
        self._dense = self._sparse = self._rerank = None
        self._lock = threading.Lock()

    @property
    def dense(self):
        with self._lock:
            if self._dense is None:
                from fastembed import TextEmbedding

                self._dense = TextEmbedding(self.s.dense_model)
            return self._dense

    @property
    def sparse(self):
        with self._lock:
            if self._sparse is None:
                from fastembed import SparseTextEmbedding

                self._sparse = SparseTextEmbedding(self.s.sparse_model)
            return self._sparse

    @property
    def reranker(self):
        with self._lock:
            if self._rerank is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                self._rerank = TextCrossEncoder(self.s.reranker_model)
            return self._rerank

    @property
    def dim(self) -> int:
        return len(next(iter(self.dense.embed(["dimension probe"]))))

    def _torch_encoder(self):
        """(tokenizer, model, device) for bulk embedding on a GPU, or None to use fastembed."""
        if not hasattr(self, "_torch"):
            self._torch = None
            if self.s.embed_device != "cpu":
                try:
                    import torch
                    from transformers import AutoModel, AutoTokenizer

                    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else None
                    device = device if self.s.embed_device == "auto" else self.s.embed_device
                    if device:
                        tok = AutoTokenizer.from_pretrained(self.s.dense_model)
                        model = AutoModel.from_pretrained(self.s.dense_model).to(device).eval()
                        self._torch = (tok, model, device)
                except ImportError:
                    pass
        return self._torch

    def embed_docs(self, texts: list[str]) -> list[list[float]]:
        enc = self._torch_encoder()
        if enc is None:
            return [v.tolist() for v in self.dense.embed(texts, batch_size=32)]
        import torch

        tok, model, device = enc
        out = []
        for i in range(0, len(texts), 32):
            x = tok(texts[i : i + 32], padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
            with torch.no_grad():
                cls = model(**x).last_hidden_state[:, 0]  # BGE uses the [CLS] vector, L2-normalised
            out += torch.nn.functional.normalize(cls, dim=-1).cpu().tolist()
        return out

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self.dense.query_embed(text))).tolist()

    def sparse_docs(self, texts: list[str]) -> list[models.SparseVector]:
        return [
            models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())
            for v in self.sparse.embed(texts, batch_size=64)
        ]

    def sparse_query(self, text: str) -> models.SparseVector:
        v = next(iter(self.sparse.query_embed(text)))
        return models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())


@lru_cache(maxsize=1)
def get_embedders() -> Embedders:
    return Embedders()
