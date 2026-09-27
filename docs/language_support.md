# 🌍 Language Support

Language support has three layers, and a language counts as supported only when all three work:

1. **Search:** finding the right passage. The embedding (`bge-m3`) and reranker (`bge-reranker-v2-m3`) models are multilingual, so questions and documents do not need to be in the same language.
2. **Answer:** the LLM writes the answer in the language of the question and passes the Self-RAG grounding check.
3. **Fixed texts:** messages that do not come from the LLM, such as "not found in the organization's documents", the greeting, error messages, and the compliance report headings.

---

## ✅ Supported Languages

| Language | Detection | Answers | Fixed texts & report headings | Evaluated |
| :--- | :---: | :---: | :---: | :--- |
| **Turkish** | ✅ | ✅ | ✅ | ✅ 51-question [evaluation set](evaluation.md): 95% correct answers, 100% written in Turkish |
| **English** | ✅ | ✅ | ✅ | ⚠️ Unit tests and spot checks; not yet part of the evaluation set |

The response language follows each question, so a user can switch languages within a session. A question without language cues, such as a bare ticket code (`SR-2026-103?`), inherits the language of the session's earlier questions; English is the default.

Compliance verdict labels (`[COMPLIANT]`, `[VIOLATION / PROHIBITED]`, …) stay in English in every language so they remain machine-readable. The web UI (Streamlit) is in English.

---

## 🧪 Other Languages (Best Effort)

Questions in other languages are detected as "other". The LLM is told to answer in the language of the question, but fixed texts, the greeting, and the compliance report headings are in English, and none of these languages is evaluated.

A spot check with `qwen2.5:7b` asked the same question ("How many days of annual leave does an employee with 8 years of seniority get?") in five languages over the Turkish evaluation documents:

| Question language | Answer |
| :--- | :--- |
| English | ✅ Correct (20 days), in English |
| Spanish | ✅ Correct, in Spanish |
| German | ✅ Correct, in German |
| Mandarin Chinese | ❌ Retrieval returned a passage, but the answer failed the Self-RAG check: the fixed English text "cannot be fully verified" was returned |
| Hindi | ❌ Same as Mandarin Chinese |

One question per language is an indication, not a measurement. Before relying on a language, add questions in it to an evaluation set (see below).

---

## 🔜 Coming Soon

The three most spoken languages after English, ranked by total number of speakers (native and second-language, Ethnologue):

| Language | Status today | Work needed |
| :--- | :--- | :--- |
| **Mandarin Chinese** | ❌ Answers fail the Self-RAG check | Find out whether the grader or the answer is the problem (grader and refine prompts in Chinese, or a model with stronger Chinese); fixed texts, report headings, greeting words; evaluation set |
| **Hindi** | ❌ Answers fail the Self-RAG check | Same as Mandarin Chinese; also check whether `qwen2.5:7b` is good enough in Hindi or another Ollama model is needed |
| **Spanish** | ⚠️ Correct answers in Spanish (best effort) | Detection as its own language, fixed texts, report headings, greeting words; evaluation set |

---

## 🛠️ Adding a Language

Everything language-specific lives in a few places:

1. **Detection** (`src/agent/language.py`): add the code to `LANGUAGE_NAMES` and a detection signal. Chinese and Hindi can be recognized by their script (Han, Devanagari); Latin-script languages such as Spanish need their own function-word list (today's Spanish, Portuguese, French, Italian, and German words in `_OTHER_WORDS` only mark a question as "other").
2. **Fixed texts** (`_MESSAGES` in `src/agent/language.py`): add a translation for every key. `message(key, language)` falls back to English for missing translations.
3. **Compliance report headings** (`REPORT_HEADINGS` in `src/agent/multi_agent/sub_agents/compliance_agent.py`). Models copy template headings verbatim, so the template is localized instead of asking the model to translate.
4. **Greeting fast path** (`GREETING_TOKENS` in `src/agent/multi_agent/supervisor.py`): greeting words that are answered without calling the LLM.
5. **Evaluation**: add questions in the new language, with expected facts in that language, and run `python -m evals.run_eval --stages all --dataset <your file>`. Check `answer_accuracy` and `language_match_rate`, and include questions over documents written in another language to test cross-lingual search.
6. **Model check**: if answers fail the Self-RAG check, compare Ollama models with the evaluation harness before changing prompts.

Custom agents should use the same helpers; see the [Custom Agents Guide](custom_agents_guide.md#-best-practices).
