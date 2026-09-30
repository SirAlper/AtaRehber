"""Build the answer-check dataset: correct answers from an evaluation report and wrong copies of them.

For every document question the report answered correctly (all expected facts present), the dataset gets
* the answer as it was ("original", must be accepted),
* the answer with one of its numbers changed ("number", must be rejected),
* the answer with an invented sentence appended ("addition", must be rejected).

    python -m evals.build_grader_dataset --report evals/results/report_XXX.json

The `grader` stage of run_eval.py then measures how many correct answers the check accepts and how many wrong
ones it rejects, for the grader's first verdict alone and for the full check (second opinion, code checks).
"""

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals import metrics  # noqa: E402

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(EVALS_DIR, "dataset_university.jsonl")
DEFAULT_OUT = os.path.join(EVALS_DIR, "grader_dataset_university.jsonl")
ADDITIONS = {
    "tr": "Ayrıca rektörlük onayıyla bu konuda 45 günlük ek süre tanınabilir.",
    "en": "In addition, the rector may grant an extra 45 days on request.",
}
# Numbers that are references, not facts: "Madde 30", "54 üncü madde", "2547 sayılı"
_REFERENCE = re.compile(
    r"(?i)(madde|article)\s*$|^\s*['’]?\s*(inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü|\.)?\s*(madde|sayılı)"
)


def changed_number(value: int) -> int:
    """A plausible but wrong value: 2 -> 3, 15 -> 18, 67 -> 80."""
    return value + 1 if value < 10 else value + max(1, round(value * 0.2))


def change_a_number(answer: str) -> Optional[str]:
    """The answer with its first fact number changed, or None if it has none.

    References ("Madde 17(1)", "3. fıkra", "54/5") are skipped with the same rules as the answer check: a changed
    citation is no wrong fact.
    """
    from src.agent.verification import _REFERENCES

    references = [m.span() for m in _REFERENCES.finditer(answer)]
    for match in re.finditer(r"(?<![\d.,])\d+(?![\d.,]\d)", answer):
        if any(start <= match.start() < end for start, end in references):
            continue
        before, after = answer[max(0, match.start() - 12) : match.start()], answer[match.end() : match.end() + 12]
        if _REFERENCE.search(before) or _REFERENCE.search(after):
            continue
        value = int(match.group(0))
        if 1900 <= value <= 2100:  # years usually come from the question
            continue
        return answer[: match.start()] + str(changed_number(value)) + answer[match.end() :]
    return None


def build(report: Dict[str, Any], cases: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for case in report["details"]["e2e"]["cases"]:
        expected = cases.get(case["id"])
        if not expected or expected["category"] != "document" or not expected.get("expected_facts"):
            continue
        answer = case.get("answer", "")
        if metrics.fact_recall(answer, expected["expected_facts"]) != 1.0 or metrics.is_refusal(answer):
            continue
        base = {"case_id": case["id"], "question": case["question"]}
        items.append({**base, "id": f"{case['id']}-original", "kind": "original", "answer": answer})
        changed = change_a_number(answer)
        if changed:
            items.append({**base, "id": f"{case['id']}-number", "kind": "number", "answer": changed})
        language = "en" if case["id"].endswith(("-en-01", "-en-02")) or "-en-" in case["id"] else "tr"
        items.append(
            {**base, "id": f"{case['id']}-addition", "kind": "addition", "answer": f"{answer} {ADDITIONS[language]}"}
        )
    return items


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--report", required=True, help="Evaluation report (JSON) with an e2e section.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)
    cases = {case["id"]: case for case in metrics.load_dataset(args.dataset)}
    items = build(report, cases)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Answer-check dataset built by evals/build_grader_dataset.py; see its docstring.\n")
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    kinds = {kind: sum(1 for i in items if i["kind"] == kind) for kind in ("original", "number", "addition")}
    print(f"{len(items)} items written to {os.path.relpath(args.out)}: {kinds}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
