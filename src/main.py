"""API launch target: `uvicorn src.main:app` or `python -m src.main`."""

from src.api.main import app  # noqa: F401  (uvicorn loads `app` from this module)

if __name__ == "__main__":
    import uvicorn

    # reload=False: reloading would load the embedding and reranker models again on every file change
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
