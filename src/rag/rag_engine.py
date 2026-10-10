import math
import os
import re
import threading
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
from sentence_transformers import SentenceTransformer, CrossEncoder
import chromadb
from src.core.config import (
    EMBEDDING_MODEL_NAME,
    RERANKER_MODEL_NAME,
    VECTOR_DB_PATH,
    RERANKER_TOP_N,
    RAG_DEVICE,
    RAG_CANDIDATE_POOL,
    RAG_MIN_SIMILARITY,
    RAG_MIN_RERANKER_SCORE,
    RAG_LEXICAL_CANDIDATES,
    RAG_ARTICLE_GAP_FILL,
)
from src.auth.document_access import metadata_allowed, search_filter
from src.core.logger import get_logger

logger = get_logger("RAGEngine")


def _is_transitional(article: str) -> bool:
    """Transitional articles and footnotes of legislation (article labels from the document loader)."""
    return article.startswith(("Geçici Madde", "Dipnotlar"))


def distance_to_similarity(distance: float, space: str) -> float:
    """Convert a ChromaDB distance into cosine similarity for (normalized) embeddings.

    - cosine: d = 1 - cos
    - ip:     d = 1 - dot (dot == cos for normalized vectors)
    - l2:     d = squared euclidean = 2 - 2cos for normalized vectors
    """
    if space == "l2":
        return 1.0 - distance / 2.0
    return 1.0 - distance


def lexical_stems(text: str) -> List[str]:
    """Word stems for the word search: Turkish words carry suffixes ("gelmeyen", "gelmemek"), so the first five
    letters of words longer than three letters are compared."""
    words = re.findall(r"\w+", str(text).replace("İ", "i").replace("I", "ı").casefold())
    return [word[:5] for word in words if len(word) > 3]


class LexicalIndex:
    """BM25 over the word stems of every chunk: finds chunks by the words they share with a question."""

    K1, B = 1.5, 0.75

    def __init__(self, ids, documents, metadatas):
        self.ids: List[str] = []
        self.metadatas: List[dict] = []
        self.lengths: List[int] = []
        self.postings: Dict[str, List[Tuple[int, int]]] = {}
        for chunk_id, text, metadata in zip(ids, documents, metadatas):
            counts = Counter(lexical_stems(text))
            position = len(self.ids)
            self.ids.append(chunk_id)
            self.metadatas.append(metadata or {})
            self.lengths.append(sum(counts.values()))
            for stem, count in counts.items():
                self.postings.setdefault(stem, []).append((position, count))
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 1.0

    def top(self, query: str, count: int, groups: Optional[List[str]] = None) -> List[str]:
        """Ids of the `count` best-matching chunks the groups may search (see metadata_allowed)."""
        scores: Dict[int, float] = {}
        for stem in set(lexical_stems(query)):
            postings = self.postings.get(stem)
            if not postings:
                continue
            # Words of many chunks ("öğrenci", "hangi") count little, rare ones ("kesintisiz") a lot
            weight = math.log(1 + (len(self.ids) - len(postings) + 0.5) / (len(postings) + 0.5))
            for position, frequency in postings:
                length = 1 - self.B + self.B * self.lengths[position] / (self.average_length or 1.0)
                gain = frequency * (self.K1 + 1) / (frequency + self.K1 * length)
                scores[position] = scores.get(position, 0.0) + weight * gain
        picked = []
        for position in sorted(scores, key=scores.get, reverse=True):
            if metadata_allowed(self.metadatas[position], groups):
                picked.append(self.ids[position])
                if len(picked) >= count:
                    break
        return picked


def _chunk_key(metadata: Optional[dict]) -> tuple:
    metadata = metadata or {}
    return metadata.get("source"), metadata.get("chunk_index")


class RAGEngine:
    """Two-Stage Retrieval Engine combining Bi-Encoder vector search with Cross-Encoder reranking."""

    # Incremented on every index change; cached answers of an older version are not reused
    index_version: int = 0

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
            self.index_version += 1
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
                    self.index_version += 1
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
                # Access groups changed: answers cached for the old access must not be reused
                self.index_version += 1
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
        n_results: Optional[int] = None,
        min_similarity: Optional[float] = None,
        top_n: Optional[int] = None,
        min_reranker_score: Optional[float] = None,
        allowed_groups: Optional[List[str]] = None,
        lexical: Optional[int] = None,
        fill_gaps: Optional[int] = None,
    ) -> dict:
        """Retrieve most relevant document chunks and rerank them with Cross-Encoder.

        allowed_groups: None searches every document; a list (possibly empty) limits the search to public
        documents and documents shared with one of these groups (document-level access control).
        lexical / fill_gaps: number of word-search candidates and of article pieces added between chosen ones
        (defaults RAG_LEXICAL_CANDIDATES and RAG_ARTICLE_GAP_FILL; 0 turns either off).

        Retrieval Workflow:
        1. Query ChromaDB for candidate pool (n_results, default RAG_CANDIDATE_POOL) and add the chunks that share
           the most words with the question (marked "lexical").
        2. Filter out candidates below min_similarity (cosine, independent of the collection's metric).
        3. Score remaining candidates with Cross-Encoder [Query, Chunk] pairs and drop those below
           min_reranker_score (default RAG_MIN_RERANKER_SCORE), so off-topic questions get no context.
        4. Return top `top_n` (default RERANKER_TOP_N) chunks as verified context, plus the pieces of an article
           that lie between two chosen pieces of it (marked "neighbor").
        """
        if self.collection.count() == 0:
            return {"context": "", "sources": []}

        actual_n = min(n_results or RAG_CANDIDATE_POOL, self.collection.count())
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

        found = [
            {"doc_text": doc_text, "meta": meta, "distance": round(float(dist), 4) if dist is not None else None}
            for doc_text, meta, dist in zip(retrieved_docs, metadatas, distances)
        ]
        lexical_count = RAG_LEXICAL_CANDIDATES if lexical is None else lexical
        if lexical_count > 0:
            known = {_chunk_key(c["meta"]) for c in found}
            for candidate in self._lexical_candidates(query, lexical_count, allowed_groups, q_embedding):
                if _chunk_key(candidate["meta"]) not in known:
                    found.append({**candidate, "lexical": True})

        # 1. Similarity threshold filtering
        threshold = RAG_MIN_SIMILARITY if min_similarity is None else min_similarity
        candidates = [
            c
            for c in found
            if c["distance"] is None or distance_to_similarity(c["distance"], self.distance_space) >= threshold
        ]

        if not candidates:
            return {"context": "", "sources": []}

        # 2. Cross-Encoder reranking
        for candidate, score in zip(candidates, self._rerank(query, candidates)):
            candidate["reranker_score"] = round(score, 4)
            candidate["raw_score"] = score
        scored = {_chunk_key(c["meta"]): c for c in candidates}

        # Compare unrounded scores: relevant chunks for scenario-style questions can score close to the threshold
        min_score = RAG_MIN_RERANKER_SCORE if min_reranker_score is None else min_reranker_score
        candidates = [c for c in candidates if c["raw_score"] >= min_score]

        if not candidates:
            return {"context": "", "sources": []}

        # 3. Sort by reranker score and pick the top chunks
        candidates.sort(key=lambda x: x["reranker_score"], reverse=True)
        top_candidates = candidates[: RERANKER_TOP_N if top_n is None else top_n]

        # 4. Pieces of an article between two chosen pieces of it: a rule's item and what it leads to (the
        # penalty, the condition) are often split over neighbouring pieces
        gap_limit = RAG_ARTICLE_GAP_FILL if fill_gaps is None else fill_gaps
        neighbors = self._article_gap_chunks(query, top_candidates, gap_limit, scored, q_embedding)
        chosen = top_candidates + neighbors

        # Transitional articles and footnotes often hold superseded values; the model leans on what it reads first,
        # so they go after the provisions in force in the context. Sources keep the relevance order.
        in_force_first = sorted(chosen, key=lambda c: _is_transitional((c["meta"] or {}).get("article", "")))
        return {"context": "\n\n".join(c["doc_text"] for c in in_force_first), "sources": _sources(chosen)}

    def search_many(
        self,
        queries: List[str],
        allowed_groups: Optional[List[str]] = None,
        max_chunks: Optional[int] = None,
        initial: Optional[List[dict]] = None,
    ) -> dict:
        """One context from the searches for several queries (the rules a scenario involves).

        Every query contributes its best chunk before any query contributes a second one, up to max_chunks
        (default RERANKER_TOP_N + 2); scores of different queries are not compared with each other.
        initial: sources of a search already made (the scenario itself); they take part like a first query.
        """
        limit = max_chunks or RERANKER_TOP_N + 2
        results = ([initial] if initial else []) + [
            self.search(query, allowed_groups=allowed_groups)["sources"]
            for query in dict.fromkeys(q.strip() for q in queries if q and q.strip())
        ]
        picked: Dict[tuple, dict] = {}
        for rank in range(max((len(sources) for sources in results), default=0)):
            for sources in results:
                if rank < len(sources) and len(picked) < limit:
                    picked.setdefault((sources[rank]["source"], sources[rank]["chunk_index"]), sources[rank])
        chosen = list(picked.values())
        in_force_first = sorted(chosen, key=lambda s: _is_transitional(str(s.get("article") or "")))
        return {"context": "\n\n".join(s["content"] for s in in_force_first), "sources": chosen}

    def _rerank(self, query: str, candidates: List[dict]) -> List[float]:
        scores = self.reranker.predict([[query, c["doc_text"]] for c in candidates])
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if isinstance(scores, (int, float)):
            scores = [scores]
        return [float(score) for score in scores]

    def _lexical_index(self) -> LexicalIndex:
        """Word index of every chunk, rebuilt after the index changes."""
        cached = getattr(self, "_lexical_cache", None)
        if cached is None or cached[0] != self.index_version:
            data = self.collection.get(include=["documents", "metadatas"])
            index = LexicalIndex(data.get("ids") or [], data.get("documents") or [], data.get("metadatas") or [])
            cached = self._lexical_cache = (self.index_version, index)
        return cached[1]

    def _lexical_candidates(self, query: str, count: int, groups: Optional[List[str]], q_embedding) -> List[dict]:
        """Chunks sharing the most words with the query, with their distance to it; [] if the word search fails."""
        try:
            ids = self._lexical_index().top(query, count, groups)
            return self._fetch(ids, q_embedding) if ids else []
        except Exception as e:
            logger.warning(f"Word search skipped: {e}")
            return []

    def _fetch(self, ids: List[str], q_embedding) -> List[dict]:
        """Chunks by id as search candidates; the distance is computed from the stored (normalized) embedding."""
        data = self.collection.get(ids=ids, include=["documents", "metadatas", "embeddings"])
        embeddings = data.get("embeddings")
        fetched = []
        for position, text in enumerate(data.get("documents") or []):
            distance = None
            if embeddings is not None and embeddings[position] is not None:
                similarity = float(sum(a * b for a, b in zip(q_embedding, embeddings[position])))
                distance = round(2.0 - 2.0 * similarity if self.distance_space == "l2" else 1.0 - similarity, 4)
            fetched.append({"doc_text": text, "meta": data["metadatas"][position] or {}, "distance": distance})
        return fetched

    def _article_gap_chunks(self, query: str, chosen: List[dict], limit: int, scored: dict, q_embedding) -> List[dict]:
        """Pieces of an article that lie between two chosen pieces of it, at most `limit` in all; an article
        whose gap is larger is left as it is."""
        if limit <= 0:
            return []
        pieces: Dict[tuple, List[int]] = {}
        for candidate in chosen:
            meta = candidate["meta"] or {}
            if meta.get("article") and isinstance(meta.get("chunk_index"), int):
                pieces.setdefault((meta.get("source"), meta["article"]), []).append(meta["chunk_index"])
        wanted = []
        for (source, article), indexes in pieces.items():
            gap = [i for i in range(min(indexes) + 1, max(indexes)) if i not in indexes]
            if gap and len(wanted) + len(gap) <= limit:
                wanted += [(source, article, index) for index in gap]
        if not wanted:
            return []
        try:
            neighbors = [scored[(source, index)] for source, _, index in wanted if (source, index) in scored]
            missing = [(source, article, index) for source, article, index in wanted if (source, index) not in scored]
            if missing:
                articles = {(source, article) for source, article, _ in missing}
                fetched = [
                    c
                    for c in self._fetch([f"{source}_chunk_{index}" for source, _, index in missing], q_embedding)
                    if (c["meta"].get("source"), c["meta"].get("article")) in articles
                ]
                for candidate, score in zip(fetched, self._rerank(query, fetched) if fetched else []):
                    candidate["reranker_score"] = round(score, 4)
                neighbors += fetched
        except Exception as e:
            logger.warning(f"Neighbouring pieces of an article not added: {e}")
            return []
        neighbors.sort(key=lambda c: (c["meta"].get("source") or "", c["meta"].get("chunk_index") or 0))
        return [{**c, "neighbor": True} for c in neighbors]


def _sources(candidates: List[dict]) -> List[dict]:
    """Search candidates as the sources returned with a context."""
    sources = []
    for c in candidates:
        meta = c["meta"] or {}
        source = {
            "source": meta.get("source", "Unknown Document"),
            "chunk_index": meta.get("chunk_index", 0),
            "content": c["doc_text"],
            "distance": c["distance"],
            "reranker_score": c["reranker_score"],
        }
        # PDF chunks carry the page they start on (and end on, if different); chunks of laws and regulations
        # carry their article. Other files and older indexes have neither.
        for key in ("page", "page_end", "article"):
            if key in meta:
                source[key] = meta[key]
        # How the chunk was found, if not by the vector search and the reranker alone
        for key in ("lexical", "neighbor"):
            if c.get(key):
                source[key] = True
        sources.append(source)
    return sources
