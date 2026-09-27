import os
import sys
import time
import psutil

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch
from src.core.config import BASE_DIR


def get_ram_mb():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)


def get_vram_mb():
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated() / (1024 * 1024), torch.cuda.memory_reserved() / (1024 * 1024)
    return 0.0, 0.0


def get_free_disk_gb():
    usage = psutil.disk_usage(BASE_DIR)
    return usage.free / (1024**3)


def main():
    print("=" * 60)
    print("🔍 OPENLOCALRAGAGENTS MEMORY & DISK BENCHMARK")
    print("=" * 60)

    start_disk = get_free_disk_gb()
    print(f"📊 Initial Free Disk Space: {start_disk:.2f} GB")

    base_ram = get_ram_mb()
    print(f"🧠 Base Python RAM: {base_ram:.1f} MB")

    # 1. RAG Engine (Embedding + Reranker + ChromaDB)
    print("\n[1/3] Loading RAGEngine (Embedding + Reranker + ChromaDB)...")
    t0 = time.time()
    from src.rag.rag_engine import RAGEngine

    engine = RAGEngine()
    rag_ram = get_ram_mb()
    rag_vram_alloc, rag_vram_res = get_vram_mb()
    print(f"  ✓ RAG Engine RAM: {rag_ram:.1f} MB (Delta: +{rag_ram - base_ram:.1f} MB) in {time.time()-t0:.2f}s")
    if torch.cuda.is_available():
        print(f"  ✓ RAG Engine VRAM: {rag_vram_alloc:.1f} MB allocated, {rag_vram_res:.1f} MB reserved")

    # 2. Vector Search Test
    print("\n[2/3] Performing Vector Search & Reranking...")
    t0 = time.time()
    res = engine.search("DevOps ve canlı dağıtım yönergeleri")
    search_ram = get_ram_mb()
    print(f"  ✓ Search Completed in {time.time()-t0:.2f}s | Context Length: {len(res.get('context', ''))} chars")
    print(f"  ✓ RAM after Search: {search_ram:.1f} MB (Delta: +{search_ram - rag_ram:.1f} MB)")

    # 3. LLM (served by Ollama in a separate process, so its memory does not show up here)
    print("\n[3/3] Checking LLM (Ollama)...")
    from src.agent.llm import check_ollama, create_chat_model
    from src.core.config import OLLAMA_MODEL

    problem = check_ollama()
    if problem:
        print(f"  ✗ {problem}")
        return
    t0 = time.time()
    create_chat_model().invoke("Merhaba")
    llm_ram = get_ram_mb()
    print(f"  ✓ First answer from '{OLLAMA_MODEL}' in {time.time()-t0:.2f}s (includes model load if it was idle)")
    print(f"  ✓ RAM after LLM call: {llm_ram:.1f} MB (Delta: +{llm_ram - search_ram:.1f} MB)")

    # 4. Agent State & Query Test
    print("\n[4/4] Executing Complete LangGraph Self-RAG Query...")
    from src.agent.agent_graph import EnterpriseRAGAgent

    agent = EnterpriseRAGAgent(rag_engine=engine)
    t0 = time.time()
    query_result = agent.query("DevOps dağıtım kuralları nelerdir?")
    final_ram = get_ram_mb()
    print(f"  ✓ Query Answered in {time.time()-t0:.2f}s")
    print(f"  ✓ Answer preview: {query_result.get('answer', '')[:100]}...")
    print(f"  ✓ Peak RAM: {final_ram:.1f} MB")

    end_disk = get_free_disk_gb()
    disk_diff_mb = (start_disk - end_disk) * 1024
    print("\n" + "=" * 60)
    print("📈 SUMMARY REPORT:")
    print(f"  • Baseline RAM (Process start):     {base_ram:.1f} MB")
    print(f"  • RAG Models RAM (Embedding+Rerank): {rag_ram:.1f} MB")
    print(f"  • Total Working Set (LLM in Ollama): {final_ram:.1f} MB (~{final_ram/1024:.2f} GB)")
    print(f"  • Disk Consumption During Run:       {disk_diff_mb:.2f} MB (Change in free space)")
    print("=" * 60)


if __name__ == "__main__":
    main()
