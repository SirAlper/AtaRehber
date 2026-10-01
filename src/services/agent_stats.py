"""How each agent performs, from the audit log: questions, speed, unverified and failed answers, user ratings."""

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from src.core.audit import audit_logger

# "[doc_agent] question" (answers) and "[POSITIVE] [doc_agent] Q: question" (feedback)
_AGENT = re.compile(r"^\[([a-z0-9_]{1,64})\]")
_FEEDBACK = re.compile(r"^\[(POSITIVE|NEGATIVE)\]\s*\[([a-z0-9_]{1,64})\]")
# Rows read per action; enough for a pilot, and the newest rows count when there are more
MAX_ROWS = 20000


def _percentile(values: List[int], share: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


async def agent_stats(days: int) -> Dict[str, Any]:
    """Per agent: questions answered, median and slow (90th percentile) duration, answers that could not be fully
    verified or found, errors, and thumbs up/down."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"questions": 0, "warnings": 0, "errors": 0, "positive": 0, "negative": 0, "durations": []}
    )
    for action in ("query", "query_stream"):
        for entry in await audit_logger.aquery_logs(action=action, start_date=since, limit=MAX_ROWS):
            match = _AGENT.match(str(entry.get("detail") or ""))
            # Failed questions are recorded before an agent is known
            row = rows[match.group(1) if match else "unknown"]
            row["questions"] += 1
            if entry.get("status") == "warning":
                row["warnings"] += 1
            elif entry.get("status") == "error":
                row["errors"] += 1
            if entry.get("duration_ms"):
                row["durations"].append(int(entry["duration_ms"]))
    for entry in await audit_logger.aquery_logs(action="feedback", start_date=since, limit=MAX_ROWS):
        match = _FEEDBACK.match(str(entry.get("detail") or ""))
        if match:
            rows[match.group(2)]["positive" if match.group(1) == "POSITIVE" else "negative"] += 1

    agents = []
    for name, row in rows.items():
        durations = row.pop("durations")
        questions = row["questions"]
        agents.append(
            {
                "agent": name,
                **row,
                "median_ms": _percentile(durations, 0.5),
                "p90_ms": _percentile(durations, 0.9),
                "warning_rate": row["warnings"] / questions if questions else 0.0,
                "error_rate": row["errors"] / questions if questions else 0.0,
            }
        )
    agents.sort(key=lambda a: a["questions"], reverse=True)
    return {"days": days, "since": since, "agents": agents}
