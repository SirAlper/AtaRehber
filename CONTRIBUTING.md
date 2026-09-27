# 🤝 Contributing to OpenLocalRagAgents

Thank you for considering contributing to **OpenLocalRagAgents**! Every contribution matters — whether it's fixing a bug, improving documentation, or proposing a new feature.

---

## 📋 How to Contribute

### 1. Fork & Clone
```bash
git clone https://github.com/<your-username>/OpenLocalRagAgents.git
cd OpenLocalRagAgents
```

### 2. Create a Feature Branch
```bash
git checkout -b feature/your-feature-name
```

### 3. Set Up Development Environment
```bash
python -m venv .venv
.venv\Scripts\activate  # Linux/macOS: source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt
python download_model.py       # embedding + reranker models
ollama pull qwen2.5:7b         # the LLM, served by Ollama (https://ollama.com)
```
The tests stub the LLM and do not need Ollama. Running the app and the evaluation's routing and end-to-end stages do.

### 4. Make Your Changes
- Follow existing code style and conventions
- Add docstrings to all new functions and classes
- Update tests if you modify existing behavior
- Add new tests for new features

### 5. Run Tests & Linting
```bash
# Run the test suite:
pytest tests/ -v

# Check test coverage:
pytest --cov=src --cov-report=term-missing

# Check linting and formatting (same commands as CI; settings in ruff.toml):
ruff check src/ tests/ evals/ ui/
ruff format --check src/ tests/ evals/ ui/
```
Ensure all tests and lint/format checks pass before submitting. Run `ruff format src/ tests/ evals/ ui/` to fix formatting automatically.

`tests/data/test_db_integration.py` runs only when `TEST_POSTGRES_URL` / `TEST_MYSQL_URL` point at a database server; CI provides both.

### 6. Measure Retrieval & Answer Quality
If you change retrieval, chunking, prompts, routing, or an agent, run the evaluation harness before and after the change and include the comparison in your PR:
```bash
python -m evals.run_eval --stages all                                   # before (on master)
python -m evals.run_eval --stages all --compare evals/results/<before>.json   # after
```
The routing and end-to-end stages need Ollama with `OLLAMA_MODEL` pulled. Measure both runs with the same model and mention it in the PR (reports record it under `config.llm_model`). See the [Evaluation Guide](docs/evaluation.md) for details.

### 7. Submit a Pull Request
- Push your branch and open a PR against `master`
- Provide a clear description of what your changes do
- Reference any related issues

---

## 🧪 Testing Guidelines

- Tests go in the topic folder under `tests/` (`agents/`, `rag/`, `api/`, `security/`, `data/`, `frontend/`, `quality/`, `performance/`) with the naming convention `test_<topic>.py`
- Use `unittest.mock` for mocking external dependencies (LLM, database, etc.)
- `tests/conftest.py` points `DATA_DIR` at a temporary directory, so tests never read or modify your real `data/` folder. Do not rely on pre-existing users or documents.
- For workflow changes, add an end-to-end test that runs the real LangGraph graph with a stubbed chat model (see `tests/agents/test_orchestrator_e2e.py`). Mocking the whole orchestrator hides bugs such as state keys that LangGraph silently drops.
- Aim for meaningful test coverage, not just line coverage

---

## 📐 Code Style

- **Python 3.12+** compatibility
- Use type hints for function signatures
- Follow PEP 8 conventions
- Use descriptive variable and function names
- Keep functions focused and under 50 lines where practical

---

## 🔒 Security

If you discover a security vulnerability, please **do not** open a public issue. Instead, email the maintainers directly or use GitHub's private vulnerability reporting.

---

## 📜 Code of Conduct

### Our Pledge
We are committed to providing a welcoming and inclusive experience for everyone, regardless of background, identity, or experience level.

### Our Standards
- Use welcoming and inclusive language
- Be respectful of differing viewpoints and experiences
- Gracefully accept constructive criticism
- Focus on what is best for the community

### Enforcement
Instances of unacceptable behavior may be reported to the project maintainers. All complaints will be reviewed and investigated promptly and fairly.

---

## 📄 License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
