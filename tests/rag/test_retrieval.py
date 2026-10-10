"""Two-stage retrieval: reranker relevance gate, similarity conversion, page numbers, telemetry off."""

import unittest
from unittest.mock import MagicMock, patch

from src.rag.rag_engine import LexicalIndex, RAGEngine, distance_to_similarity


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


class TestTransitionalArticlesLast(unittest.TestCase):
    def test_provisions_in_force_come_first_in_the_context(self):
        engine = make_engine(
            [("geçici 65 puan", 0.7, 0.99), ("madde 24 elli beş puan", 0.7, 0.98), ("dipnot", 0.6, 0.9)]
        )
        engine.collection.query.return_value["metadatas"] = [
            [
                {"source": "kanun.txt", "chunk_index": 1, "article": "Geçici Madde 47"},
                {"source": "kanun.txt", "chunk_index": 2, "article": "Madde 24 – Doçentlik"},
                {"source": "kanun.txt", "chunk_index": 3, "article": "Dipnotlar (değişiklik notları)"},
            ]
        ]
        result = engine.search("q", min_reranker_score=0.0)
        self.assertEqual(result["context"].split("\n\n"), ["madde 24 elli beş puan", "geçici 65 puan", "dipnot"])
        # Sources keep the relevance order and name the article
        self.assertEqual([s["article"] for s in result["sources"]][0], "Geçici Madde 47")


class TestNoTelemetry(unittest.TestCase):
    def test_chroma_client_disables_anonymized_telemetry(self):
        with (
            patch("src.rag.rag_engine.SentenceTransformer"),
            patch("src.rag.rag_engine.CrossEncoder"),
            patch("src.rag.rag_engine.chromadb.PersistentClient") as client,
        ):
            RAGEngine(vector_db_path="unused")
        self.assertFalse(client.call_args.kwargs["settings"].anonymized_telemetry)


class FakeCollection:
    """Vector store of chunks given as (source, chunk_index, text, similarity to any query, article)."""

    def __init__(self, chunks, dense):
        self.chunks = {
            f"{source}_chunk_{index}": {
                "text": text,
                "sim": sim,
                "meta": {"source": source, "chunk_index": index, **({"article": article} if article else {})},
            }
            for source, index, text, sim, article in chunks
        }
        # Ids the vector search returns, best first
        self.dense = dense

    def count(self):
        return len(self.chunks)

    def query(self, query_embeddings, n_results, include, **kwargs):
        rows = [self.chunks[chunk_id] for chunk_id in self.dense][:n_results]
        return {
            "documents": [[row["text"] for row in rows]],
            "metadatas": [[row["meta"] for row in rows]],
            "distances": [[1.0 - row["sim"] for row in rows]],
        }

    def get(self, ids=None, include=(), **kwargs):
        chosen = [chunk_id for chunk_id in (ids or self.chunks) if chunk_id in self.chunks]
        data = {
            "ids": chosen,
            "documents": [self.chunks[chunk_id]["text"] for chunk_id in chosen],
            "metadatas": [self.chunks[chunk_id]["meta"] for chunk_id in chosen],
        }
        if "embeddings" in include:
            # The query embedding of fake_engine is [1.0], so the dot product is the similarity
            data["embeddings"] = [[self.chunks[chunk_id]["sim"]] for chunk_id in chosen]
        return data


def fake_engine(chunks, dense, scores):
    """RAGEngine over a FakeCollection; scores: reranker score by chunk text (0.0 if not listed)."""
    engine = object.__new__(RAGEngine)
    engine.distance_space = "cosine"
    engine.embedding_model = MagicMock()
    engine.embedding_model.encode.return_value = MagicMock(tolist=lambda: [1.0])
    engine.collection = FakeCollection(chunks, dense)
    engine.reranker = MagicMock()
    engine.reranker.predict.side_effect = lambda pairs: [scores.get(pair[1], 0.0) for pair in pairs]
    return engine


class TestWordSearch(unittest.TestCase):
    ITEM = "m) Özürsüz ve kesintisiz 3 - 9 gün göreve gelmemek."

    def engine(self):
        chunks = [
            ("kanun.txt", 0, "Disiplin cezaları uyarma, kınama ve aylıktan kesmedir.", 0.7, "Madde 53"),
            ("kanun.txt", 5, self.ITEM, 0.5, "Madde 53"),
            ("kanun.txt", 9, "Rektör yardımcıları beş yıl için atanır.", 0.4, "Madde 13"),
        ]
        scores = {chunks[0][2]: 0.6, self.ITEM: 0.9}
        return fake_engine(chunks, dense=["kanun.txt_chunk_0"], scores=scores)

    def test_a_chunk_sharing_the_questions_words_joins_the_candidates(self):
        question = "Özürsüz olarak kesintisiz 4 gün göreve gelmeyen öğretim elemanına hangi ceza verilir?"
        sources = self.engine().search(question, min_reranker_score=0.05)["sources"]
        # The list item was not among the most similar chunks; the reranker puts it first once it is a candidate
        self.assertEqual([s["chunk_index"] for s in sources], [5, 0])
        self.assertTrue(sources[0]["lexical"])
        self.assertAlmostEqual(sources[0]["distance"], 0.5)
        self.assertNotIn("lexical", sources[1])

    def test_word_search_can_be_turned_off_and_respects_the_similarity_threshold(self):
        question = "Kesintisiz 4 gün göreve gelmeyen"
        self.assertEqual(len(self.engine().search(question, min_reranker_score=0.05, lexical=0)["sources"]), 1)
        strict = self.engine().search(question, min_reranker_score=0.05, min_similarity=0.6)["sources"]
        self.assertEqual([s["chunk_index"] for s in strict], [0])

    def test_index_matches_stems_and_document_access(self):
        index = LexicalIndex(
            ["a", "b"],
            ["Sınavlarda kopya çekmek veya çektirmek", "Sınavlarda kopya çekmek"],
            [{"acl_public": False, "acl_idari": True}, {}],
        )
        self.assertEqual(index.top("kopya çeken öğrenci", 5), ["b", "a"])
        self.assertEqual(index.top("kopya çeken öğrenci", 5, groups=[]), ["b"])
        self.assertEqual(index.top("kopya çeken öğrenci", 5, groups=["idari"]), ["b", "a"])
        self.assertEqual(index.top("emeklilik yaşı", 5), [])


class TestArticleGapFill(unittest.TestCase):
    def engine(self, dense):
        chunks = [("kanun.txt", index, f"parça {index}", 0.7, "Madde 54") for index in range(1, 8)]
        scores = {f"parça {index}": 0.9 - index / 100 for index in range(1, 8)}
        return fake_engine(chunks, dense=[f"kanun.txt_chunk_{index}" for index in dense], scores=scores)

    def test_pieces_between_two_chosen_pieces_of_an_article_are_added(self):
        result = self.engine(dense=[1, 2, 5]).search("q", min_reranker_score=0.0, lexical=0)
        sources = result["sources"]
        # 3 and 4 lie between the chosen 2 and 5; the chosen pieces keep their order, the added ones follow
        self.assertEqual([s["chunk_index"] for s in sources], [1, 2, 5, 3, 4])
        self.assertEqual([bool(s.get("neighbor")) for s in sources], [False, False, False, True, True])
        self.assertIn("parça 3", result["context"])
        self.assertIsNotNone(sources[3]["reranker_score"])

    def test_larger_gaps_and_single_pieces_are_left_alone(self):
        engine = self.engine(dense=[1, 6])
        self.assertEqual(len(engine.search("q", min_reranker_score=0.0, lexical=0)["sources"]), 2)
        self.assertEqual(len(self.engine(dense=[3]).search("q", min_reranker_score=0.0, lexical=0)["sources"]), 1)
        off = self.engine(dense=[1, 3]).search("q", min_reranker_score=0.0, lexical=0, fill_gaps=0)
        self.assertEqual(len(off["sources"]), 2)


class TestSearchMany(unittest.TestCase):
    def test_every_query_contributes_its_best_chunk_first(self):
        engine = object.__new__(RAGEngine)
        results = {
            "devam": [{"source": "y.txt", "chunk_index": 37, "content": "en az %80"}],
            "sınav": [
                {"source": "y.txt", "chunk_index": 41, "content": "devam şartını yerine getirenler girer"},
                {"source": "y.txt", "chunk_index": 37, "content": "en az %80"},
                {"source": "y.txt", "chunk_index": 50, "content": "ilan", "article": "Geçici Madde 1"},
            ],
        }
        engine.search = lambda query, allowed_groups=None: {"sources": results[query]}
        merged = engine.search_many(["sınav", "devam", "sınav"], max_chunks=3)
        self.assertEqual([s["chunk_index"] for s in merged["sources"]], [41, 37, 50])
        self.assertEqual(merged["context"].split("\n\n")[0], "devam şartını yerine getirenler girer")
        self.assertEqual(len(engine.search_many(["sınav", "devam"], max_chunks=2)["sources"]), 2)
        # Sources of a search already made (the scenario) count like a first query
        scenario = [{"source": "y.txt", "chunk_index": 39, "content": "sınavların etkisi"}]
        merged = engine.search_many(["devam"], initial=scenario)
        self.assertEqual([s["chunk_index"] for s in merged["sources"]], [39, 37])
