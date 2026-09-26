import os

import pytest

from src.core.config import ALL_LOCAL_MODELS_EXIST, BASE_DIR

psutil = pytest.importorskip("psutil")

# Profiles the real BGE-M3 + reranker models; skipped where they have not been downloaded (e.g. CI)
pytestmark = pytest.mark.skipif(not ALL_LOCAL_MODELS_EXIST, reason="Local model weights not available")


def get_current_process_ram_mb() -> float:
    """Return Resident Set Size (RSS) in megabytes for the current process."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)


def get_drive_free_gb() -> float:
    """Return free disk space on project drive in gigabytes."""
    return psutil.disk_usage(BASE_DIR).free / (1024**3)


class TestMemoryAndResourceProfile:
    """
    Automated pytest test suite to profile RAM allocation,
    vector search overhead, and disk space stability.
    """

    def test_rag_engine_memory_footprint(self):
        """Verify RAG Engine (BGE-M3 + Reranker) loads within reasonable enterprise RAM budget (< 2.5 GB)."""
        ram_before = get_current_process_ram_mb()
        from src.rag.rag_engine import RAGEngine

        _engine = RAGEngine()  # keep loaded while measuring
        ram_after = get_current_process_ram_mb()
        delta_mb = ram_after - ram_before

        print(f"\n[RAM Profile] RAG Engine Delta: +{delta_mb:.1f} MB (Total: {ram_after:.1f} MB)")
        # Embedding + Reranker should stay under 2500 MB
        assert delta_mb < 2500, f"RAG Engine consumed excessive RAM: {delta_mb:.1f} MB"

    def test_search_and_reranking_memory_stability(self):
        """Verify vector search + cross-encoder reranking does not leak memory across repeated queries."""
        from src.rag.rag_engine import RAGEngine

        engine = RAGEngine()

        # Warmup query
        engine.search("Mühendislik dağıtım kuralları")
        ram_after_warmup = get_current_process_ram_mb()

        # 5 consecutive search queries
        for i in range(5):
            engine.search(f"Bilgi güvenliği parola kuralları sorgu {i}")

        ram_after_queries = get_current_process_ram_mb()
        growth_mb = ram_after_queries - ram_after_warmup

        print(f"\n[RAM Profile] Search Repetition Memory Growth: +{growth_mb:.1f} MB")
        # Search operations must not leak memory (> 200MB growth across 5 searches is a leak)
        assert growth_mb < 200, f"Memory leak detected during vector search: {growth_mb:.1f} MB growth"

    def test_disk_space_stability_during_operations(self):
        """Verify vector search and audit logging do not consume disproportionate disk space."""
        disk_before = get_drive_free_gb()
        from src.core.audit import audit_logger

        # Write 20 audit events
        for i in range(20):
            audit_logger.log(
                username="perf_tester",
                role="admin",
                action="query",
                detail=f"Automated test query {i}",
                status="success",
            )

        disk_after = get_drive_free_gb()
        # Free disk change should be negligible (< 0.05 GB)
        disk_diff_gb = abs(disk_before - disk_after)
        print(f"\n[Disk Profile] Disk difference after 20 audit events: {disk_diff_gb * 1024:.2f} MB")
        assert disk_diff_gb < 0.05, f"Excessive disk consumption: {disk_diff_gb:.2f} GB"
