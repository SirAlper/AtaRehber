"""Two-stage retrieval: reranker relevance gate, similarity conversion, page numbers, telemetry off."""

import unittest
from unittest.mock import MagicMock, patch

from src.rag.rag_engine import RAGEngine, distance_to_similarity


def make_engine(chunks):
    """RAGEngine with fake models: chunks is a list of (text, cosine_similarity, reranker_score)."""
    engine = object.__new__(RAGEngine)
    engine.distance_space = "cosine"
    engine.embedding_model = MagicMock()
    engine.embedding_model.encode.return_value = MagicMock(tolist=lambda: [0.0])
    engine.collection = MagicMock()
    engine.collection.count.return_value = len(chunks)
    engine.collection.query.return_value = {
        "documents": [[text for text, _, _ in chunks]],
        "metadatas": [[{"source": f"doc{i}.txt", "chunk_index": 0} for i in range(len(chunks))]],
        "distances": [[1.0 - sim for _, sim, _ in chunks]],
    }
    engine.reranker = MagicMock()
    engine.reranker.predict.side_effect = lambda pairs: [
        next(score for text, _, score in chunks if text == pair[1]) for pair in pairs
    ]
    return engine


class TestRerankerGate(unittest.TestCase):
    def test_chunks_below_reranker_threshold_are_dropped(self):
        engine = make_engine([("relevant", 0.6, 0.9), ("weak", 0.55, 0.001)])
        result = engine.search("q", min_reranker_score=0.005)
        self.assertEqual([s["content"] for s in result["sources"]], ["relevant"])
        self.assertEqual(result["context"], "relevant")

    def test_off_topic_question_gets_no_context(self):
        # High bi-encoder similarity is not enough: the cross-encoder decides relevance
        engine = make_engine([("parking rules?", 0.59, 0.0036), ("other", 0.5, 0.0003)])
        self.assertEqual(engine.search("q", min_reranker_score=0.005), {"context": "", "sources": []})

    def test_default_threshold_comes_from_config(self):
        engine = make_engine([("a", 0.6, 0.02), ("b", 0.6, 0.004)])
        with patch("src.rag.rag_engine.RAG_MIN_RERANKER_SCORE", 0.01):
            self.assertEqual([s["content"] for s in engine.search("q")["sources"]], ["a"])
        with patch("src.rag.rag_engine.RAG_MIN_RERANKER_SCORE", 0.0):
            self.assertEqual(len(engine.search("q")["sources"]), 2)


class TestSimilarityConversion(unittest.TestCase):
    def test_threshold_equivalent_across_metrics(self):
        # Legacy default (L2 distance 1.35) corresponds to cosine similarity 0.325
        self.assertAlmostEqual(distance_to_similarity(1.35, "l2"), 0.325)
        self.assertAlmostEqual(distance_to_similarity(0.675, "cosine"), 0.325)
        self.assertAlmostEqual(distance_to_similarity(0.0, "cosine"), 1.0)


class TestSourcePages(unittest.TestCase):
    def test_page_numbers_are_passed_through_to_sources(self):
        engine = make_engine([("madde 12", 0.7, 0.9), ("madde 13", 0.6, 0.8)])
        engine.collection.query.return_value["metadatas"] = [
            [
                {"source": "yonetmelik.pdf", "chunk_index": 0, "page": 4},
                {"source": "yonetmelik.pdf", "chunk_index": 1, "page": 4, "page_end": 5},
            ]
        ]
        sources = engine.search("q", min_reranker_score=0.0)["sources"]
        self.assertEqual(sources[0]["page"], 4)
        self.assertNotIn("page_end", sources[0])
        self.assertEqual((sources[1]["page"], sources[1]["page_end"]), (4, 5))


class TestNoTelemetry(unittest.TestCase):
    def test_chroma_client_disables_anonymized_telemetry(self):
        with (
            patch("src.rag.rag_engine.SentenceTransformer"),
            patch("src.rag.rag_engine.CrossEncoder"),
            patch("src.rag.rag_engine.chromadb.PersistentClient") as client,
        ):
            RAGEngine(vector_db_path="unused")
        self.assertFalse(client.call_args.kwargs["settings"].anonymized_telemetry)
