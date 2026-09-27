import os
import threading
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer, CrossEncoder
import chromadb
from src.core.config import (
    EMBEDDING_MODEL_NAME,
    RERANKER_MODEL_NAME,
    VECTOR_DB_PATH,
    RERANKER_TOP_N,
    RAG_DEVICE,
    RAG_MIN_SIMILARITY,
    RAG_MIN_RERANKER_SCORE,
)
from src.auth.document_access import search_filter
from src.core.logger import get_logger

logger = get_logger("RAGEngine")


def distance_to_similarity(distance: float, space: str) -> float:
    """Convert a ChromaDB distance into cosine similarity for (normalized) embeddings.

    - cosine: d = 1 - cos
    - ip:     d = 1 - dot (dot == cos for normalized vectors)
    - l2:     d = squared euclidean = 2 - 2cos for normalized vectors
    """
    if space == "l2":
        return 1.0 - distance / 2.0
    return 1.0 - distance


class RAGEngine:
    """Two-Stage Retrieval Engine combining Bi-Encoder vector search with Cross-Encoder reranking."""

    def __init__(self, vector_db_path: Optional[str] = None):
        device = RAG_DEVICE
        logger.info(f"Running Embedding and Reranker on '{device}'...")

        # Multilingual Embedding Model (BAAI/bge-m3)
        is_local_embed = os.path.exists(EMBEDDING_MODEL_NAME)
        logger.info(f"Loading Embedding Model ({EMBEDDING_MODEL_NAME.split(os.sep)[-1]})...")
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device, local_files_only=is_local_embed)

        # Cross-Encoder Reranker Model (BAAI/bge-reranker-v2-m3)
        is_local_reranker = os.path.exists(RERANKER_MODEL_NAME)
        logger.info(f"Loading Reranker Model ({RERANKER_MODEL_NAME.split(os.sep)[-1]})...")
        self.reranker = CrossEncoder(
            RERANKER_MODEL_NAME,
            max_length=512,
            device=device,
            local_files_only=is_local_reranker,
        )

        logger.info("Initializing local vector store (ChromaDB)...")
        # vector_db_path lets tools such as the evaluation harness use an isolated store
        # anonymized_telemetry=False: ChromaDB otherwise sends usage events to an external analytics service
        self.client = chromadb.PersistentClient(
            path=vector_db_path or VECTOR_DB_PATH,
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        # New collections use cosine distance; existing collections keep the metric they were created with
        self.collection = self.client.get_or_create_collection(
            name="enterprise_docs",
            metadata={"hnsw:space": "cosine"},
        )
        self.distance_space = (self.collection.metadata or {}).get("hnsw:space", "l2")

        # Serializes index writes (and backups) and guards the cached per-document stats
        self.write_lock = threading.RLock()
        self._stats_cache: Optional[dict] = None

    def add_documents(
        self,
        documents: List[str],
        ids: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ):
        """Vectorize new document chunks and store them in ChromaDB."""
        if not documents:
            logger.warning("No documents to add.")
            return

        embeddings = self.embedding_model.encode(documents, show_progress_bar=True, normalize_embeddings=True).tolist()

        with self.write_lock:
            self.collection.upsert(documents=documents, embeddings=embeddings, ids=ids, metadatas=metadatas)
            self._stats_cache = None
        logger.info(f"Successfully indexed {len(documents)} chunks.")

    def delete_document(self, filename: str) -> int:
        """Delete all chunks belonging to the specified file from ChromaDB."""
        try:
            with self.write_lock:
                results = self.collection.get(where={"source": filename})
                ids = results.get("ids", [])
                if ids:
                    self.collection.delete(ids=ids)
                    self._stats_cache = None
            if ids:
                logger.info(f"Deleted {len(ids)} chunks belonging to '{filename}'.")
                return len(ids)
            return 0
        except Exception as e:
            logger.error(f"Error during chunk deletion: {e}")
            return 0

    def update_document_metadata(self, filename: str, metadata: Dict[str, Any]) -> int:
        """Merge `metadata` into every chunk of a document (e.g. access groups); returns the chunk count."""
        with self.write_lock:
            ids = self.collection.get(where={"source": filename}).get("ids", [])
            if ids:
                self.collection.update(ids=ids, metadatas=[dict(metadata) for _ in ids])
        return len(ids)

    def get_stats(self) -> dict:
        """Return general index statistics from the vector store.

        The per-document scan is cached and only recomputed after the index changes.
        """
        with self.write_lock:
            if self._stats_cache is None:
                all_data = self.collection.get(include=["metadatas"])
                metadatas = all_data.get("metadatas", []) or []

                doc_counts: Dict[str, int] = {}
                for meta in metadatas:
                    if meta and "source" in meta:
                        src = meta["source"]
                        doc_counts[src] = doc_counts.get(src, 0) + 1

                self._stats_cache = {
                    "total_chunks": len(metadatas),
                    "total_documents": len(doc_counts),
                    "document_chunks": doc_counts,
                }
            return {
                **self._stats_cache,
                "document_chunks": dict(self._stats_cache["document_chunks"]),
            }

    def search(
        self,
        query: str,
        n_results: int = 10,
        min_similarity: Optional[float] = None,
        top_n: Optional[int] = None,
        min_reranker_score: Optional[float] = None,
        allowed_groups: Optional[List[str]] = None,
    ) -> dict:
        """Retrieve most relevant document chunks and rerank them with Cross-Encoder.

        allowed_groups: None searches every document; a list (possibly empty) limits the search to public
        documents and documents shared with one of these groups (document-level access control).

        Retrieval Workflow:
        1. Query ChromaDB for candidate pool (n_results=10).
        2. Filter out candidates below min_similarity (cosine, independent of the collection's metric).
        3. Score remaining candidates with Cross-Encoder [Query, Chunk] pairs and drop those below
           min_reranker_score (default RAG_MIN_RERANKER_SCORE), so off-topic questions get no context.
        4. Return top `top_n` (default RERANKER_TOP_N) chunks as verified context.
        """
        if self.collection.count() == 0:
            return {"context": "", "sources": []}

        actual_n = min(n_results, self.collection.count())
        q_embedding = self.embedding_model.encode(query, normalize_embeddings=True).tolist()
        query_args = {}
        if allowed_groups is not None:
            query_args["where"] = search_filter(allowed_groups)
        results = self.collection.query(
            query_embeddings=[q_embedding],
            n_results=actual_n,
            include=["documents", "metadatas", "distances"],
            **query_args,
        )

        docs_list = results.get("documents") or []
        metas_list = results.get("metadatas") or []
        dists_list = results.get("distances") or []

        retrieved_docs = docs_list[0] if docs_list else []
        metadatas = metas_list[0] if metas_list else []
        distances = dists_list[0] if dists_list else []

        # 1. Similarity threshold filtering
        threshold = RAG_MIN_SIMILARITY if min_similarity is None else min_similarity
        candidates = []
        for doc_text, meta, dist in zip(retrieved_docs, metadatas, distances):
            dist_val = round(float(dist), 4) if dist is not None else None

            if dist_val is not None and distance_to_similarity(dist_val, self.distance_space) < threshold:
                continue

            candidates.append({"doc_text": doc_text, "meta": meta, "distance": dist_val})

        if not candidates:
            return {"context": "", "sources": []}

        # 2. Cross-Encoder reranking
        pairs = [[query, c["doc_text"]] for c in candidates]
        reranker_scores = self.reranker.predict(pairs)
        if hasattr(reranker_scores, "tolist"):
            reranker_scores = reranker_scores.tolist()
        if isinstance(reranker_scores, (int, float)):
            reranker_scores = [reranker_scores]

        # Compare unrounded scores: relevant chunks for scenario-style questions can score close to the threshold
        min_score = RAG_MIN_RERANKER_SCORE if min_reranker_score is None else min_reranker_score
        scored = []
        for candidate, score in zip(candidates, reranker_scores):
            if float(score) < min_score:
                continue
            candidate["reranker_score"] = round(float(score), 4)
            scored.append(candidate)
        candidates = scored

        if not candidates:
            return {"context": "", "sources": []}

        # 3. Sort by reranker score and pick the top chunks
        candidates.sort(key=lambda x: x["reranker_score"], reverse=True)
        top_candidates = candidates[: RERANKER_TOP_N if top_n is None else top_n]

        filtered_docs = []
        sources = []
        for c in top_candidates:
            filtered_docs.append(c["doc_text"])
            meta = c["meta"] or {}
            source = {
                "source": meta.get("source", "Unknown Document"),
                "chunk_index": meta.get("chunk_index", 0),
                "content": c["doc_text"],
                "distance": c["distance"],
                "reranker_score": c["reranker_score"],
            }
            # PDF chunks carry the page they start on (and end on, if different). DOCX/TXT files and
            # indexes built before page tracking have no page information.
            for key in ("page", "page_end"):
                if key in meta:
                    source[key] = meta[key]
            sources.append(source)

        return {"context": "\n\n".join(filtered_docs), "sources": sources}
