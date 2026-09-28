"""Tools that custom agents can be given (see custom_agents.py).

Every tool is local: no tool reaches the internet. Tools are built per question, so a document search runs with
the asking user's access groups and the results a tool returns are collected for the answer check.
"""

import ast
import calendar
import json
import math
import operator
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import StructuredTool

from src.core.logger import get_logger

logger = get_logger("MultiAgent.Tools")

# ── Calculator ──

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {"round": round, "abs": abs, "min": min, "max": max, "sqrt": math.sqrt}
MAX_EXPRESSION_LENGTH = 200
MAX_EXPONENT = 100


def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression without running code: numbers, + - * / // % **, parentheses, and
    round/abs/min/max/sqrt. Without functions, a comma between digits is a decimal separator ('2,5' is 2.5);
    in function calls it separates the arguments."""
    text = str(expression).strip()
    if not text or len(text) > MAX_EXPRESSION_LENGTH:
        raise ValueError("Expression is empty or too long.")
    source = text if re.search(r"[a-z]", text, re.IGNORECASE) else re.sub(r"(?<=\d),(?=\d)", ".", text)
    tree = ast.parse(source, mode="eval")

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > MAX_EXPONENT or abs(left) > 10**6):
                raise ValueError("Exponent too large.")
            return _BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](evaluate(node.operand))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS
            and not node.keywords
        ):
            return _FUNCTIONS[node.func.id](*[evaluate(arg) for arg in node.args])
        raise ValueError(f"Not allowed in an expression: {type(node).__name__}")

    result = evaluate(tree)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    elif isinstance(result, float):
        result = round(result, 6)
    return f"{text} = {result}"


# ── Dates ──


def _parse_date(text: str) -> date:
    """'2026-09-28', '28.09.2026', '28/09/2026', or 'today' / 'bugün'."""
    value = str(text).strip().lower()
    if value in ("today", "bugün", "bugun", ""):
        return date.today()
    for separator in (".", "/"):
        if separator in value:
            day, month, year = (int(part) for part in value.split(separator))
            return date(year, month, day)
    return date.fromisoformat(value)


def _add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def date_calculation(start_date: str, days: int = 0, months: int = 0, years: int = 0, end_date: str = "") -> str:
    """With end_date: the number of days between the two dates. Otherwise: start_date plus (or minus) days,
    months, and years. Dates as YYYY-MM-DD or DD.MM.YYYY; 'today' for the current date."""
    start = _parse_date(start_date)
    if end_date:
        end = _parse_date(end_date)
        return f"{start.isoformat()} → {end.isoformat()}: {(end - start).days} days"
    result = _add_months(start, int(months) + 12 * int(years)) + timedelta(days=int(days))
    weekday = calendar.day_name[result.weekday()]
    return f"{start.isoformat()} + {years} years {months} months {days} days = {result.isoformat()} ({weekday})"


# ── Catalog ──


@dataclass
class ToolRun:
    """What the tools of one question returned: text for the answer check and the document sources."""

    outputs: List[str] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    documents_used: bool = False

    def context(self) -> str:
        return "\n\n".join(self.outputs)


@dataclass
class ToolSpec:
    name: str
    labels: Dict[str, str]
    descriptions: Dict[str, str]
    # Builds the LangChain tool for one question: build(run, state) -> StructuredTool
    build: Callable[[ToolRun, Dict[str, Any]], StructuredTool]
    # Whether the tool can work right now (e.g. a database is connected)
    available: Callable[[], bool] = lambda: True


def _record(run: ToolRun, name: str, text: str) -> str:
    run.outputs.append(f"[{name}] {text}")
    return text


def _calculator_tool(run: ToolRun, state: Dict[str, Any]) -> StructuredTool:
    def calculator(expression: str) -> str:
        """Evaluate an arithmetic expression such as '(40 * 0.3) + (70 * 0.7)' or '2020 + 5'."""
        try:
            return _record(run, "calculator", calculate(expression))
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError, OverflowError) as e:
            return f"Error: {e}"

    return StructuredTool.from_function(calculator)


def _dates_tool(run: ToolRun, state: Dict[str, Any]) -> StructuredTool:
    def date_calculator(start_date: str, days: int = 0, months: int = 0, years: int = 0, end_date: str = "") -> str:
        """Date arithmetic. With end_date: days between start_date and end_date. Otherwise: start_date plus days,
        months, and years (negative values go back). Dates as YYYY-MM-DD or DD.MM.YYYY; 'today' for today."""
        try:
            return _record(run, "dates", date_calculation(start_date, days, months, years, end_date))
        except (ValueError, TypeError, OverflowError) as e:
            return f"Error: {e}"

    return StructuredTool.from_function(date_calculator)


def _documents_tool(run: ToolRun, state: Dict[str, Any]) -> StructuredTool:
    from src.agent.multi_agent.base import BaseSubAgent

    def search_documents(query: str) -> str:
        """Search the organization's documents (laws, regulations, policies) and return the most relevant
        passages with their document and article. Use a short, specific query."""
        from src.api.state import get_rag_engine

        run.documents_used = True
        try:
            result = get_rag_engine().search(query, allowed_groups=BaseSubAgent.search_groups(state))
        except Exception as e:
            logger.error(f"Document search failed: {e}")
            return "Error: the document search is unavailable."
        known = {(s.get("source"), s.get("chunk_index")) for s in run.sources}
        run.sources.extend(s for s in result.get("sources", []) if (s.get("source"), s.get("chunk_index")) not in known)
        context = result.get("context", "").strip()
        if not context:
            return "No relevant passage found in the documents."
        return _record(run, "documents", context)

    return StructuredTool.from_function(search_documents)


def _database_available() -> bool:
    from src.api.state import get_db_connector

    try:
        return bool(get_db_connector().is_connected)
    except Exception:
        return False


def _database_tool(run: ToolRun, state: Dict[str, Any]) -> StructuredTool:
    from src.api.state import get_db_connector

    connector = get_db_connector()

    def query_database(sql: str) -> str:
        """Run one read-only SQL SELECT query on the connected database and return the rows as JSON."""
        result = connector.execute_query(sql)
        if result.get("status") != "success":
            # The reason can reveal schema details; it stays in the server log
            logger.warning(f"Database tool query rejected or failed: {result.get('message')}")
            return "Error: the query was rejected or failed. Use a single SELECT on the tables listed."
        rows = json.dumps(result.get("rows", []), ensure_ascii=False, default=str)
        return _record(run, "database", f"{result.get('row_count', 0)} rows: {rows}")

    tool = StructuredTool.from_function(query_database)
    try:
        tool.description += f"\nTables:\n{connector.get_schema_summary()}"
    except Exception as e:
        logger.warning(f"Schema summary unavailable: {e}")
    return tool


TOOLS: Dict[str, ToolSpec] = {
    "documents": ToolSpec(
        name="documents",
        labels={"tr": "📄 Belge arama", "en": "📄 Document search"},
        descriptions={
            "tr": "Kurum belgelerinde (yönetmelik, kanun, prosedür) arar; kullanıcının erişebildiği belgelerle "
            "sınırlıdır. Belgeden gelen cevaplar alıntı denetiminden geçer.",
            "en": "Searches the organization's documents (regulations, laws, procedures) the user may see. "
            "Answers based on documents are checked against quotes.",
        },
        build=_documents_tool,
    ),
    "calculator": ToolSpec(
        name="calculator",
        labels={"tr": "🧮 Hesap makinesi", "en": "🧮 Calculator"},
        descriptions={
            "tr": "Dört işlem, yüzde, üs, yuvarlama (ör. not ortalaması, ücret hesabı). Kod çalıştırmaz.",
            "en": "Arithmetic, percentages, powers, rounding (e.g. grade averages, fees). Runs no code.",
        },
        build=_calculator_tool,
    ),
    "dates": ToolSpec(
        name="dates",
        labels={"tr": "📅 Tarih hesaplama", "en": "📅 Date calculation"},
        descriptions={
            "tr": "Tarihe gün/ay/yıl ekler veya iki tarih arasındaki günü bulur (ör. itiraz süresinin son günü).",
            "en": "Adds days/months/years to a date or counts the days between two dates (e.g. a deadline).",
        },
        build=_dates_tool,
    ),
    "database": ToolSpec(
        name="database",
        labels={"tr": "🗄️ Veritabanı (salt okunur)", "en": "🗄️ Database (read-only)"},
        descriptions={
            "tr": "Bağlı veritabanında salt okunur SELECT sorguları çalıştırır; yalnızca izinli tablolar. "
            "Kişisel veri içeren tablolar için kullanıcı bazlı filtre yoktur.",
            "en": "Runs read-only SELECT queries on the connected database, allowed tables only. There is no "
            "per-user row filter for tables with personal data.",
        },
        build=_database_tool,
        available=_database_available,
    ),
}


def tool_catalog(language: str = "tr") -> List[Dict[str, Any]]:
    """Tools for the admin UI: name, label, description, and whether they can work right now."""
    return [
        {
            "name": spec.name,
            "label": spec.labels.get(language, spec.labels["en"]),
            "description": spec.descriptions.get(language, spec.descriptions["en"]),
            "available": spec.available(),
        }
        for spec in TOOLS.values()
    ]


def available_tools(names: List[str]) -> List[str]:
    return [name for name in names if name in TOOLS and TOOLS[name].available()]


def build_tools(names: List[str], run: ToolRun, state: Dict[str, Any]) -> List[StructuredTool]:
    return [TOOLS[name].build(run, state) for name in available_tools(names)]


def tool_description(name: str) -> Optional[str]:
    spec = TOOLS.get(name)
    return spec.descriptions["en"] if spec else None
