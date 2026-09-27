import os
import sys

# Enable Hugging Face Hub online access for model downloading
os.environ["ALLOW_ONLINE_HF"] = "1"
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

from huggingface_hub import snapshot_download
from src.core.config import (
    MODELS_DIR,
    LOCAL_EMBEDDING_PATH,
    LOCAL_RERANKER_PATH,
    OLLAMA_MODEL,
)

os.makedirs(MODELS_DIR, exist_ok=True)

models = [
    {
        "name": "1/2 - Multilingual Embedding Model (BAAI/bge-m3)",
        "repo_id": "BAAI/bge-m3",
        "local_dir": LOCAL_EMBEDDING_PATH,
        "est_size": "~2.2 GB",
        "key_file": "config.json"
    },
    {
        "name": "2/2 - Cross-Encoder Reranker Model (BAAI/bge-reranker-v2-m3)",
        "repo_id": "BAAI/bge-reranker-v2-m3",
        "local_dir": LOCAL_RERANKER_PATH,
        "est_size": "~1.1 GB",
        "key_file": "config.json"
    },
]
# The LLM is not downloaded here: it is served by Ollama (`ollama pull <model>`)

force_download = os.getenv("FORCE_DOWNLOAD", "0") == "1"

if __name__ == "__main__":
    print("=" * 70)
    print("  Enterprise Local RAG — Model Downloader & Verification Utility")
    print(f"  Target Storage Directory: {os.path.abspath(MODELS_DIR)}")
    print("  Retrieval models only (~3.3 GB). The LLM is pulled with Ollama.")
    print("=" * 70)

    download_failures = []

    for item in models:
        key_file_path = os.path.join(item["local_dir"], item["key_file"])
        already_exists = os.path.exists(key_file_path)

        if already_exists and not force_download:
            print(f"\n[SKIP] {item['name']}")
            print(f"       Already verified at: {item['local_dir']}")
            print("       (Set FORCE_DOWNLOAD=1 environment variable to force re-download)")
            continue

        print(f"\n[DOWNLOADING] {item['name']} (Estimated size: {item['est_size']})")
        print(f"              Destination: {item['local_dir']}...")

        try:
            snapshot_download(
                repo_id=item["repo_id"],
                local_dir=item["local_dir"],
                resume_download=True,
                ignore_patterns=["*.onnx", "*.onnx_data", "onnx/*", "imgs/*", "*.jpg", "*.png"]
            )
            print(f"[SUCCESS] {item['name']} ready.")
        except KeyboardInterrupt:
            print("\n[CANCELLED] Download interrupted by user.")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Failed to download {item['repo_id']}: {e}")
            download_failures.append((item["name"], str(e)))

    print("\n" + "=" * 70)
    if download_failures:
        print(f"❌ {len(download_failures)} model(s) failed to download:")
        for name, err in download_failures:
            print(f"   - {name}: {err}")
        print("\nPlease check your internet connection or HuggingFace access and retry.")
        sys.exit(1)
    else:
        print("✅ Retrieval models verified and available in './models' directory!")
        print(f"   Next, pull the LLM with Ollama: ollama pull {OLLAMA_MODEL}")
    print("=" * 70)