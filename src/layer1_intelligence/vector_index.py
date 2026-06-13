"""
Vector indexing and retrieval services for grounded RAG.

Design goals:
- keep the retrieval contract backend-agnostic
- support deterministic tests without external services
- make Qdrant integration a drop-in adapter rather than a hard dependency
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import Iterable, Protocol, Sequence

from src.layer0_model_infra.gateway import EmbeddingRequest, ModelGateway, get_gateway
from src.layer3_domain.document_ingestion import DocumentChunker
from src.layer3_domain.document_models import (
    DocumentChunk,
    IngestedDocument,
    RetrievalQuery,
    RetrievalResult,
)
from src.layer3_domain.document_structure import (
    chunk_article_number,
    extract_article_reference,
    find_article_span_by_number,
    normalize_article_number,
)
from src.layer3_domain.medical_document_structure import detect_drug_names
from src.shared.config import get_settings
from src.shared.errors import EmbeddingError, RAGError
from src.shared.logger import get_logger, log_rag_retrieval

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )
except Exception:  # pragma: no cover - optional runtime dependency behavior
    QdrantClient = None
    Distance = None
    FieldCondition = None
    Filter = None
    MatchValue = None
    PointStruct = None
    VectorParams = None

logger = get_logger(__name__)
settings = get_settings()
_CROSS_ENCODER = None
_CROSS_ENCODER_UNAVAILABLE = False
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NUMERIC_TOKEN_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_DOSE_QUERY_RE = re.compile(r"\b(max(?:imum)?|dose|dosage|daily dose|mg|milligram)\b", re.I)
_DOSE_SECTION_RE = re.compile(r"\b(dosage|administration|dose|dosing|tablet|strength)\b", re.I)
_NONCLINICAL_DOSE_RE = re.compile(
    r"\b(maximum recommended human daily dose|body surface area|carcinogenesis|mutagenesis|fertility|rats?|mice|animal|nonclinical)\b",
    re.I,
)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "i",
    "in", "is", "it", "of", "on", "or", "that", "the", "their", "this", "to",
    "was", "what", "when", "where", "which", "who", "why", "with", "your",
}


def _normalize_vector(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return [0.0 for _ in values]
    return [value / norm for value in values]


def _sigmoid(value: float) -> float:
    """Numerically stable logistic squashing (for cross-encoder logits)."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _significant_terms(text: str) -> list[str]:
    return [token for token in _tokenize(text) if token not in _STOPWORDS]


def _numeric_tokens(text: str) -> set[str]:
    return set(_NUMERIC_TOKEN_RE.findall(text.lower()))


def _article_reference_bonus(query: str, chunk: DocumentChunk) -> float:
    article_number = extract_article_reference(query)
    if not article_number:
        return 0.0

    normalized = normalize_article_number(article_number)
    chunk_number = chunk_article_number(chunk.content, chunk.metadata)
    if chunk_number == normalized:
        return 0.55
    if find_article_span_by_number(chunk.page_text, normalized):
        return 0.36
    return -0.18


def _dose_query_bonus(query: str, chunk: DocumentChunk) -> float:
    if not _DOSE_QUERY_RE.search(query):
        return 0.0

    text = _build_retrieval_text(chunk)
    section_text = " ".join(
        part
        for part in [
            chunk.section_title or "",
            chunk.metadata.get("section_name", ""),
            chunk.metadata.get("subsection_name", ""),
        ]
        if part
    )
    bonus = 0.0
    if _DOSE_SECTION_RE.search(section_text):
        bonus += 0.45
    if re.search(r"\b(max(?:imum)?|recommended|daily|dose|dosage|mg)\b", text, re.I):
        bonus += 0.18
    if re.search(r"\b\d+(?:,\d{3})?\s*mg\b", text, re.I):
        bonus += 0.18
    if _NONCLINICAL_DOSE_RE.search(text):
        bonus -= 0.55
    return bonus


def _chunk_drug_matches(chunk: DocumentChunk, requested_drugs: set[str]) -> bool:
    if not requested_drugs:
        return True
    haystack = " ".join(
        part
        for part in [
            chunk.title,
            chunk.section_title or "",
            chunk.metadata.get("drug_name", ""),
            chunk.content[:500],
        ]
        if part
    ).lower()
    for drug in requested_drugs:
        drug_terms = {term for term in _tokenize(drug) if len(term) >= 4}
        if drug.lower() in haystack or drug_terms.intersection(_tokenize(haystack)):
            return True
    return False


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    normalized_text = " ".join(_tokenize(text))
    normalized_phrase = " ".join(_tokenize(phrase))
    if not normalized_text or not normalized_phrase:
        return False
    return normalized_phrase in normalized_text


def _build_retrieval_text(chunk: DocumentChunk) -> str:
    heading_parts = [chunk.title]
    drug_name = chunk.metadata.get("drug_name")
    section_name = chunk.metadata.get("section_name")
    subsection_name = chunk.metadata.get("subsection_name")
    if drug_name:
        heading_parts.extend([drug_name, drug_name])
    if section_name:
        heading_parts.extend([section_name, section_name])
    if subsection_name:
        heading_parts.append(subsection_name)
    if chunk.section_title:
        heading_parts.extend([chunk.section_title, chunk.section_title])
    heading = " | ".join(part for part in heading_parts if part)
    return f"{heading}\n\n{chunk.content}".strip()


def _lexical_feature_scores(query: str, chunk: DocumentChunk) -> tuple[float, list[str]]:
    query_terms = _significant_terms(query)
    if not query_terms:
        query_terms = _tokenize(query)
    if not query_terms:
        return 0.0, []

    retrieval_text = _build_retrieval_text(chunk)
    chunk_terms = _significant_terms(retrieval_text)
    if not chunk_terms:
        chunk_terms = _tokenize(retrieval_text)
    if not chunk_terms:
        return 0.0, []

    query_counter = Counter(query_terms)
    chunk_counter = Counter(chunk_terms)
    shared_terms = sorted(set(query_counter).intersection(chunk_counter))
    if not shared_terms:
        return 0.0, []

    overlap_hits = sum(min(query_counter[token], chunk_counter[token]) for token in shared_terms)
    query_norm = math.sqrt(sum(value * value for value in query_counter.values()))
    chunk_norm = math.sqrt(sum(value * value for value in chunk_counter.values()))
    cosine_overlap = overlap_hits / max(query_norm * chunk_norm, 1e-9)
    coverage = len(shared_terms) / max(len(set(query_terms)), 1)
    density = overlap_hits / max(len(chunk_terms), 1)
    rarity_bonus = sum(1.0 / max(chunk_counter[token], 1) for token in shared_terms) / max(
        len(shared_terms), 1
    )

    phrase_bonus = 0.0
    if _contains_normalized_phrase(chunk.content, query):
        phrase_bonus += 0.28
    elif len(query_terms) >= 2:
        query_bigrams = list(zip(query_terms, query_terms[1:]))
        matching_bigrams = sum(
            1 for first, second in query_bigrams
            if f"{first} {second}" in " ".join(_tokenize(chunk.content))
        )
        phrase_bonus += min(0.18, matching_bigrams * 0.08)

    title_bonus = 0.0
    title_terms = set(_significant_terms(chunk.title))
    section_terms = set(_significant_terms(chunk.section_title or ""))
    if title_terms.intersection(query_terms):
        title_bonus += 0.10
    if section_terms.intersection(query_terms):
        title_bonus += 0.16
    if set(query_terms).issubset(section_terms) and section_terms:
        title_bonus += 0.10

    numeric_bonus = 0.0
    query_numbers = _numeric_tokens(query)
    chunk_numbers = _numeric_tokens(f"{chunk.content} {chunk.page_text}")
    if query_numbers and query_numbers.intersection(chunk_numbers):
        numeric_bonus += 0.16
    article_bonus = _article_reference_bonus(query, chunk)
    dose_bonus = _dose_query_bonus(query, chunk)

    score = (
        cosine_overlap * 0.43
        + coverage * 0.22
        + min(density * 4.0, 0.08)
        + min(rarity_bonus, 0.12)
        + phrase_bonus
        + title_bonus
        + numeric_bonus
        + article_bonus
        + dose_bonus
    )
    if len(set(chunk_terms)) <= 40:
        score += 0.05
    return round(score, 4), shared_terms


class EmbeddingProvider(Protocol):
    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts."""


class VectorStore(Protocol):
    def upsert(
        self,
        items: Sequence[tuple[DocumentChunk, list[float]]],
        *,
        namespace: str = "default",
    ) -> None:
        """Store chunk vectors."""

    def search(
        self,
        vector: Sequence[float],
        request: RetrievalQuery,
        *,
        namespace: str = "default",
    ) -> list[RetrievalResult]:
        """Search for similar chunks."""

    def has_namespace(self, namespace: str) -> bool:
        """Whether a namespace/collection already exists."""


class GatewayEmbeddingProvider:
    """Embedding provider backed by the Layer 0 model gateway."""

    def __init__(
        self,
        model_id: str | None = None,
        gateway: ModelGateway | None = None,
    ) -> None:
        self.model_id = model_id or settings.DEFAULT_EMBEDDING_MODEL
        self.gateway = gateway or get_gateway()

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self.gateway.embed(
                EmbeddingRequest(model_id=self.model_id, texts=list(texts))
            )
        except Exception as exc:  # pragma: no cover - depends on external runtime
            raise EmbeddingError(
                text=texts[0] if texts else "",
                details={"count": len(texts), "provider": "gateway", "error": str(exc)},
            ) from exc
        return [_normalize_vector(vector) for vector in response.embeddings]


class ResilientEmbeddingProvider:
    """
    Prefer the configured embedding model, then fall back locally if needed.

    This keeps the app usable in development while still upgrading retrieval
    quality whenever a real embedding backend is available.

    When the primary backend drops out, the local hash fallback produces
    vectors in a different space (and generally a different dimension) than
    the neural index, so matching its dimension to the index buys nothing.
    ``InMemoryVectorStore.search`` instead carries a dimension guard that
    drops the now-meaningless semantic signal and lets lexical / BM25
    retrieval carry the query until the backend recovers.
    """

    def __init__(
        self,
        primary: EmbeddingProvider | None = None,
        fallback: EmbeddingProvider | None = None,
    ) -> None:
        self.primary = primary or GatewayEmbeddingProvider()
        self.fallback = fallback or DeterministicEmbeddingProvider()
        self.degraded = False

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            vectors = await self.primary.embed_texts(texts)
        except Exception as exc:
            self.degraded = True
            # ERROR, not warning: silently swapping to lexical-hash vectors
            # quietly destroys semantic retrieval quality, so operators need
            # this to be loud and alertable rather than buried at warning.
            logger.error(
                "embedding_provider_primary_failed_falling_back",
                error=str(exc),
                primary_provider=type(self.primary).__name__,
                fallback_provider=type(self.fallback).__name__,
                fallback_dimension=getattr(self.fallback, "dimension", None),
                impact="semantic retrieval degraded to lexical-hash vectors until the embedding backend recovers",
                layer="layer1_intelligence",
            )
            return await self.fallback.embed_texts(texts)
        if self.degraded:
            self.degraded = False
            logger.info(
                "embedding_provider_primary_recovered",
                primary_provider=type(self.primary).__name__,
                layer="layer1_intelligence",
            )
        return vectors


class DeterministicEmbeddingProvider:
    """
    Lightweight, deterministic embedding provider for tests and local dry-runs.

    It uses token hashing into a fixed-dimensional bag-of-words style vector.
    """

    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, text: str) -> list[float]:
        buckets = [0.0] * self.dimension
        tokens = _tokenize(text)
        features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        for token in features:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            buckets[bucket] += sign
        return _normalize_vector(buckets)


@dataclass
class _StoredVector:
    chunk: DocumentChunk
    vector: list[float]


_DIM_MISMATCH_WARNED = False


def _warn_dimension_mismatch(query_dim: int, stored_dim: int) -> None:
    """Warn once when query/stored embedding dimensions diverge."""
    global _DIM_MISMATCH_WARNED
    if _DIM_MISMATCH_WARNED:
        return
    _DIM_MISMATCH_WARNED = True
    logger.warning(
        "vector_store_dimension_mismatch",
        query_dim=query_dim,
        stored_dim=stored_dim,
        impact="embedding backend likely fell back mid-index; semantic signal dropped for mismatched chunks, lexical retrieval still active",
        layer="layer1_intelligence",
    )


class InMemoryVectorStore:
    """Simple cosine-similarity vector store for tests and local development."""

    def __init__(self) -> None:
        self._items_by_namespace: dict[str, list[_StoredVector]] = {}

    def upsert(
        self,
        items: Sequence[tuple[DocumentChunk, list[float]]],
        *,
        namespace: str = "default",
    ) -> None:
        existing_items = self._items_by_namespace.get(namespace, [])
        by_chunk_id = {item.chunk.chunk_id: item for item in existing_items}
        for chunk, vector in items:
            by_chunk_id[chunk.chunk_id] = _StoredVector(chunk=chunk, vector=list(vector))
        self._items_by_namespace[namespace] = list(by_chunk_id.values())

    def search(
        self,
        vector: Sequence[float],
        request: RetrievalQuery,
        *,
        namespace: str = "default",
    ) -> list[RetrievalResult]:
        candidate_items: list[_StoredVector] = []
        query_vector = _normalize_vector(vector)
        requested_drugs = detect_drug_names(request.query)
        for stored in self._items_by_namespace.get(namespace, []):
            chunk = stored.chunk
            if chunk.tenant_id != request.tenant_id:
                continue
            if request.domain and chunk.domain != request.domain:
                continue
            if requested_drugs and not _chunk_drug_matches(chunk, requested_drugs):
                continue
            candidate_items.append(stored)

        semantic_results: list[RetrievalResult] = []
        for stored in candidate_items:
            chunk = stored.chunk
            # Guard against embedder dimension skew: if a stored vector and the
            # query vector were produced by providers of different
            # dimensionality (e.g. the embedding backend fell back to the local
            # hash provider for one but not the other), cosine over a zip()
            # would silently truncate to the shorter vector and return a
            # meaningless score. Drop the semantic signal in that case and let
            # the lexical/BM25 signals carry the result.
            if len(stored.vector) != len(query_vector):
                _warn_dimension_mismatch(len(query_vector), len(stored.vector))
                semantic_score = 0.0
            else:
                semantic_score = self._cosine(query_vector, stored.vector)
            lexical_score, matched_terms = _lexical_feature_scores(request.query, chunk)
            if semantic_score <= 0 and lexical_score <= 0:
                continue
            blended_score = max(semantic_score, 0.0) * 0.58 + lexical_score * 0.42
            semantic_results.append(
                RetrievalResult(
                    chunk=chunk,
                    score=round(blended_score, 4),
                    matched_terms=matched_terms,
                )
            )

        semantic_results.sort(key=lambda item: item.score, reverse=True)
        bm25_results = self._bm25_search(request.query, candidate_items)
        fused_results = self._rrf_fuse(semantic_results, bm25_results)
        return fused_results[: request.top_k]

    def _cosine(self, left: Sequence[float], right: Sequence[float]) -> float:
        return sum(a * b for a, b in zip(left, right))

    def _bm25_search(
        self,
        query: str,
        items: Sequence[_StoredVector],
    ) -> list[RetrievalResult]:
        query_terms = _significant_terms(query) or _tokenize(query)
        if not query_terms or not items:
            return []

        documents = [_significant_terms(_build_retrieval_text(item.chunk)) for item in items]
        doc_count = len(documents)
        avg_doc_len = sum(len(document) for document in documents) / max(doc_count, 1)
        document_frequency: Counter[str] = Counter()
        for document in documents:
            document_frequency.update(set(document))

        query_counter = Counter(query_terms)
        results: list[RetrievalResult] = []
        k1 = 1.5
        b = 0.75
        for item, document in zip(items, documents):
            if not document:
                continue
            term_frequency = Counter(document)
            score = 0.0
            matched_terms: list[str] = []
            for term in query_counter:
                frequency = term_frequency.get(term, 0)
                if frequency <= 0:
                    continue
                matched_terms.append(term)
                idf = math.log(1 + (doc_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                denominator = frequency + k1 * (1 - b + b * len(document) / max(avg_doc_len, 1e-9))
                score += idf * (frequency * (k1 + 1) / denominator)
            if score <= 0:
                continue
            results.append(
                RetrievalResult(
                    chunk=item.chunk,
                    score=round(score, 4),
                    matched_terms=sorted(matched_terms),
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results

    def _rrf_fuse(
        self,
        semantic_results: Sequence[RetrievalResult],
        bm25_results: Sequence[RetrievalResult],
        *,
        k: int = 60,
    ) -> list[RetrievalResult]:
        by_chunk_id: dict[str, RetrievalResult] = {}
        fused_scores: dict[str, float] = {}

        for ranked_results in (semantic_results, bm25_results):
            for rank, result in enumerate(ranked_results, start=1):
                chunk_id = result.chunk.chunk_id
                fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
                existing = by_chunk_id.get(chunk_id)
                if existing is None or result.score > existing.score:
                    by_chunk_id[chunk_id] = result

        fused: list[RetrievalResult] = []
        for chunk_id, result in by_chunk_id.items():
            fused.append(
                result.model_copy(
                    update={
                        "score": round(fused_scores[chunk_id], 6),
                        "matched_terms": result.matched_terms,
                    }
                )
            )
        return sorted(fused, key=lambda item: item.score, reverse=True)

    def has_namespace(self, namespace: str) -> bool:
        return namespace in self._items_by_namespace


class QdrantVectorStore:
    """Qdrant-backed vector store adapter (opt-in production backend).

    One Qdrant collection per namespace ("<base>__<namespace>"), created lazily
    on first upsert using the *actual* embedding dimension (not the possibly
    stale settings.EMBEDDING_DIMENSION). Chunk ids are mapped to stable UUIDs
    because Qdrant point ids must be uint or UUID; the original chunk_id is kept
    in the payload for retrieval.
    """

    def __init__(
        self,
        collection_name: str | None = None,
        dimension: int | None = None,
        client: QdrantClient | None = None,
    ) -> None:
        if QdrantClient is None:
            raise RAGError("qdrant-client is not installed", error_code="QDRANT_UNAVAILABLE")

        self.collection_name = collection_name or settings.QDRANT_COLLECTION_NAME
        self._forced_dimension = dimension
        self.client = client or QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.QDRANT_API_KEY,
        )

    def _namespace_name(self, namespace: str) -> str:
        safe_namespace = namespace.replace("/", "_").replace("\\", "_").replace(":", "_")
        return f"{self.collection_name}__{safe_namespace}"

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        # Qdrant point ids must be uint or UUID, but chunk ids look like
        # "doc:p1:c0". Map deterministically to a UUID so re-upserts overwrite.
        return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

    def _collection_exists(self, collection_name: str) -> bool:
        existing = {collection.name for collection in self.client.get_collections().collections}
        return collection_name in existing

    def _ensure_collection(self, collection_name: str, dimension: int) -> None:
        if self._collection_exists(collection_name):
            return
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )

    def upsert(
        self,
        items: Sequence[tuple[DocumentChunk, list[float]]],
        *,
        namespace: str = "default",
    ) -> None:
        item_list = list(items)
        if not item_list:
            return
        collection_name = self._namespace_name(namespace)
        dimension = self._forced_dimension or len(item_list[0][1])
        self._ensure_collection(collection_name, dimension)
        points = [
            PointStruct(
                id=self._point_id(chunk.chunk_id),
                vector=list(vector),
                payload={
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "tenant_id": chunk.tenant_id,
                    "domain": chunk.domain,
                    "title": chunk.title,
                    "source_uri": chunk.source_uri,
                    "page_number": chunk.page_number,
                    "page_text": chunk.page_text,
                    "content": chunk.content,
                    "section_title": chunk.section_title,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "page_width": chunk.page_width,
                    "page_height": chunk.page_height,
                    "metadata": chunk.metadata,
                },
            )
            for chunk, vector in item_list
        ]
        # wait=True so points are searchable immediately (read-after-write):
        # without it Qdrant indexes asynchronously and a query right after
        # ingest can miss freshly-added chunks.
        self.client.upsert(collection_name=collection_name, points=points, wait=True)

    def search(
        self,
        vector: Sequence[float],
        request: RetrievalQuery,
        *,
        namespace: str = "default",
    ) -> list[RetrievalResult]:
        collection_name = self._namespace_name(namespace)
        if not self._collection_exists(collection_name):
            return []

        must = [FieldCondition(key="tenant_id", match=MatchValue(value=request.tenant_id))]
        if request.domain:
            must.append(FieldCondition(key="domain", match=MatchValue(value=request.domain)))

        response = self.client.query_points(
            collection_name=collection_name,
            query=list(_normalize_vector(vector)),
            limit=request.top_k,
            query_filter=Filter(must=must),
            with_payload=True,
        )

        results: list[RetrievalResult] = []
        for item in response.points:
            payload = item.payload or {}
            chunk = DocumentChunk(
                chunk_id=str(payload["chunk_id"]),
                document_id=str(payload["document_id"]),
                tenant_id=str(payload["tenant_id"]),
                domain=str(payload["domain"]),
                title=str(payload["title"]),
                source_uri=str(payload["source_uri"]),
                page_number=int(payload["page_number"]),
                page_text=str(payload["page_text"]),
                content=str(payload["content"]),
                section_title=payload.get("section_title"),
                start_char=int(payload.get("start_char", 0)),
                end_char=int(payload.get("end_char", 0)),
                page_width=float(payload.get("page_width", 0.0) or 0.0),
                page_height=float(payload.get("page_height", 0.0) or 0.0),
                metadata=dict(payload.get("metadata", {})),
            )
            results.append(
                RetrievalResult(
                    chunk=chunk,
                    score=round(float(item.score), 4),
                    matched_terms=[],
                )
            )
        return results

    def has_namespace(self, namespace: str) -> bool:
        return self._collection_exists(self._namespace_name(namespace))


class DocumentIndexService:
    """End-to-end indexing and semantic search service for ingested documents."""

    def __init__(
        self,
        embedder: EmbeddingProvider,
        vector_store: VectorStore,
        chunker: DocumentChunker | None = None,
        namespace: str = "default",
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.chunker = chunker or DocumentChunker()
        self.namespace = namespace

    async def index_documents(self, documents: Iterable[IngestedDocument]) -> list[DocumentChunk]:
        document_list = list(documents)
        chunks = self.chunker.chunk_many(document_list)
        if not chunks:
            return []

        embeddings = await self.embedder.embed_texts([_build_retrieval_text(chunk) for chunk in chunks])
        self.vector_store.upsert(list(zip(chunks, embeddings)), namespace=self.namespace)

        logger.info(
            "documents_indexed",
            document_count=len(document_list),
            chunk_count=len(chunks),
            layer="layer1_intelligence",
        )
        return chunks

    async def search(self, request: RetrievalQuery) -> list[RetrievalResult]:
        start = perf_counter()
        candidate_count = min(max(request.top_k * 5, 20), 100)
        expanded_request = request.model_copy(update={"top_k": candidate_count})
        query_vectors = await self.embedder.embed_texts([request.query])
        results = self.vector_store.search(query_vectors[0], expanded_request, namespace=self.namespace)
        log_rag_retrieval(
            logger=logger,
            query=request.query,
            num_results=len(results),
            top_score=results[0].score if results else 0.0,
            latency_ms=(perf_counter() - start) * 1000,
        )
        return results

    def has_index(self) -> bool:
        return self.vector_store.has_namespace(self.namespace)


def rerank_results(
    query: str,
    results: Sequence[RetrievalResult],
) -> list[RetrievalResult]:
    """
    Lightweight lexical rerank on top of vector recall.

    This is a practical interim strategy until we add a dedicated reranker model.
    """
    query_terms = Counter(_significant_terms(query) or _tokenize(query))
    query_numbers = _numeric_tokens(query)
    requested_article = extract_article_reference(query)
    rescored: list[RetrievalResult] = []
    for result in results:
        chunk_text = _build_retrieval_text(result.chunk)
        chunk_terms = Counter(_significant_terms(chunk_text) or _tokenize(chunk_text))
        overlap = sum(min(query_terms[token], chunk_terms[token]) for token in query_terms)
        coverage = len(set(query_terms).intersection(chunk_terms)) / max(len(set(query_terms)), 1)
        bonus = overlap / max(sum(query_terms.values()), 1)
        phrase_bonus = 0.0
        if _contains_normalized_phrase(result.chunk.content, query):
            phrase_bonus += 0.30
        elif result.chunk.section_title and _contains_normalized_phrase(result.chunk.section_title, query):
            phrase_bonus += 0.18
        lexical_score, matched_terms = _lexical_feature_scores(query, result.chunk)
        number_bonus = 0.0
        if query_numbers and query_numbers.intersection(
            _numeric_tokens(f"{result.chunk.content} {result.chunk.page_text}")
        ):
            number_bonus += 0.12
        article_bonus = _article_reference_bonus(query, result.chunk)
        if requested_article and article_bonus < 0:
            number_bonus -= 0.16
        dose_bonus = _dose_query_bonus(query, result.chunk)
        structural_bonus = 0.0
        if result.chunk.section_title:
            structural_bonus += 0.04
        if result.chunk.title and set(_significant_terms(result.chunk.title)).intersection(query_terms):
            structural_bonus += 0.04
        rescored.append(
            result.model_copy(
                update={
                    "score": round(
                        result.score * 0.45
                        + lexical_score * 0.4
                        + coverage * 0.12
                        + bonus * 0.1
                        + phrase_bonus
                        + structural_bonus
                        + number_bonus
                        + article_bonus
                        + dose_bonus,
                        4,
                    ),
                    "matched_terms": matched_terms or result.matched_terms,
                }
            )
        )
    rescored = sorted(rescored, key=lambda item: item.score, reverse=True)
    return _cross_encoder_rerank(query, rescored[:8]) + rescored[8:]


def _cross_encoder_rerank(
    query: str,
    results: Sequence[RetrievalResult],
) -> list[RetrievalResult]:
    """Optionally rerank top candidates with a local cross-encoder.

    Gated by ``settings.RAG_CROSS_ENCODER_ENABLED`` so it never surprise-loads a
    model onto the GPU. The ms-marco cross-encoder emits raw logits; we squash
    them with a sigmoid so the resulting score is a 0..1 relevance probability.
    Sigmoid is monotonic, so the rerank ORDER is identical to the raw logits,
    but the score now matches the 0..1 scale the grounding gate thresholds and
    the UI assume (a bare logit makes both meaningless).
    """
    global _CROSS_ENCODER, _CROSS_ENCODER_UNAVAILABLE
    if not settings.RAG_CROSS_ENCODER_ENABLED or _CROSS_ENCODER_UNAVAILABLE or not results:
        return list(results)
    if importlib.util.find_spec("sentence_transformers") is None:
        _CROSS_ENCODER_UNAVAILABLE = True
        return list(results)

    try:
        if _CROSS_ENCODER is None:
            from sentence_transformers import CrossEncoder

            logger.info(
                "cross_encoder_loading",
                model="cross-encoder/ms-marco-MiniLM-L-6-v2",
                note="first grounded query loads this onto the GPU; set RAG_CROSS_ENCODER_ENABLED=false to disable",
                layer="layer1_intelligence",
            )
            _CROSS_ENCODER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        pairs = [(query, _build_retrieval_text(result.chunk)) for result in results]
        scores = _CROSS_ENCODER.predict(pairs)
    except Exception as exc:  # pragma: no cover - optional model availability
        _CROSS_ENCODER_UNAVAILABLE = True
        logger.warning(
            "cross_encoder_rerank_unavailable",
            error=str(exc),
            layer="layer1_intelligence",
        )
        return list(results)

    reranked: list[RetrievalResult] = []
    for result, score in zip(results, scores):
        reranked.append(
            result.model_copy(
                update={
                    "score": round(_sigmoid(float(score)), 4),
                    "matched_terms": result.matched_terms,
                }
            )
        )
    return sorted(reranked, key=lambda item: item.score, reverse=True)
