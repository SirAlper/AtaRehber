"""Enterprise Local RAG API Entry Point.

Backward compatibility bridge and Uvicorn launch target:
    uvicorn src.main:app --reload
or directly via the modular path:
    uvicorn src.api.main:app --reload
"""

from src.api.main import app  # noqa: F401  Re-exported as the `uvicorn src.main:app` launch target

if __name__ == "__main__":
    import uvicorn

    # Use reload=False to avoid re-loading LLM weights into memory on file uploads
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
