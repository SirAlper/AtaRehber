import bisect
import os
import re
from typing import List, Optional, Tuple

from pypdf import PdfReader
from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.core.config import ARTICLE_CHUNK_SIZE, CHUNK_OVERLAP, CHUNK_SIZE
from src.core.logger import get_logger
from src.rag.turkish_numbers import annotate_numbers

logger = get_logger("DocumentLoader")

# Article headings of laws and regulations: "Madde 30 –", "MADDE 1 –", "Ek Madde 5 –", "Geçici Madde 47 –",
# "Madde 53/A-" (the law also contains the typo "Maddde")
_ARTICLE_RE = re.compile(
    r"^[ \t]*(?:(?P<kind>Geçici|GEÇİCİ|Ek|EK)[ \t]+)?(?:Madd+e|MADDE)[ \t]*(?P<num>\d+(?:/[A-ZÇĞİÖŞÜ])?)?[ \t]*[-–—]",
    re.MULTILINE,
)
# Footnotes of consolidated legislation ("[12] 17/2/2011 tarihli ... değiştirilmiştir") hold superseded wording
_FOOTNOTE_RE = re.compile(r"^\[\d+\][ \t]", re.MULTILINE)
# Upper-case heading line of an appendix (at least 20 characters, no lower-case letters)
_APPENDIX_RE = re.compile(r"^[ \t]*[^\sa-zçğıöşü][^a-zçğıöşü\n]{19,}$", re.MULTILINE)
# A document is treated as legislation when it has at least this many article headings
MIN_ARTICLES = 3
# Longest line accepted as an article title ("Emeklilik yaş haddi:") or as a list introduction
_MAX_TITLE_LEN = 100
_MAX_INTRO_LEN = 400
# List markers of legislation from the outside in: paragraph "(1)", item "a)" / "ğ)" / "A-", sub-item "1)"
_LIST_LEVELS = (
    re.compile(r"^\(\d+\)"),
    re.compile(r"^\(?[a-zçğıöşüA-ZÇĞİÖŞÜ]{1,2}[).-]\s"),
    re.compile(r"^\d+[).-]\s"),
)


def _list_level(text: str) -> Optional[int]:
    """List level of the first non-empty line (0 paragraph, 1 item, 2 sub-item), or None for plain text."""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return next((level for level, marker in enumerate(_LIST_LEVELS) if marker.match(first)), None)


class DocumentLoader:
    """Document loader and contextual chunker for PDF, DOCX, and TXT files.

    Laws and regulations are split by article: every chunk carries the document and article label, and pieces of
    long articles also carry the sentence that introduces their list (e.g. which penalty the listed acts get).
    Other documents are split into CHUNK_SIZE pieces with an optional DOKÜMAN/KOD header.
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        # Configurable via CHUNK_SIZE and CHUNK_OVERLAP environment variables
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
            # Each chunk records its offset in the text, which maps PDF chunks to page numbers
            add_start_index=True,
        )
        self.article_splitter = RecursiveCharacterTextSplitter(
            chunk_size=ARTICLE_CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
            # Sentences keep their full stop instead of passing it to the next piece
            keep_separator="end",
            add_start_index=True,
        )

    @staticmethod
    def _extract_document_header(content: str) -> str:
        """Extract DOCUMENT / DOKÜMAN and CODE / KOD from the first lines to construct a contextual header.

        Example output: '[Document: NovaTech Information Security Policy | CODE: SEC-POL-04]'
        """
        lines = content.strip().split("\n")[:5]

        doc_title = ""
        doc_code = ""

        for line in lines:
            stripped = line.strip()
            # Match "DOCUMENT:" or "DOKÜMAN:"
            if re.match(r"^(DOCUMENT|DOKÜMAN)\s*:", stripped, re.IGNORECASE):
                doc_title = re.sub(r"^(DOCUMENT|DOKÜMAN)\s*:\s*", "", stripped, flags=re.IGNORECASE).strip()
            # Match "CODE:" or "KOD:"
            elif re.match(r"^(CODE|KOD)\s*:", stripped, re.IGNORECASE):
                doc_code = re.sub(r"^(CODE|KOD)\s*:\s*", "", stripped, flags=re.IGNORECASE).strip()

        if doc_title and doc_code:
            return f"[Document: {doc_title} | CODE: {doc_code}]"
        elif doc_title:
            return f"[Document: {doc_title}]"

        return ""

    def _read_pdf_pages(self, file_path: str) -> List[Tuple[int, str]]:
        """Return (page number, text) for every PDF page with extractable text; page numbers start at 1."""
        try:
            reader = PdfReader(file_path)
            pages = []
            for number, page in enumerate(reader.pages, start=1):
                content = page.extract_text()
                if content:
                    pages.append((number, content))
            return pages
        except Exception as e:
            logger.error(f"PDF read error ({os.path.basename(file_path)}): {e}")
            return []

    def _read_pdf(self, file_path: str) -> str:
        return "".join(f"{text}\n" for _, text in self._read_pdf_pages(file_path))

    def _read_docx(self, file_path: str) -> str:
        try:
            doc = Document(file_path)
            return "\n".join([p.text for p in doc.paragraphs if p.text])
        except Exception as e:
            logger.error(f"DOCX read error ({os.path.basename(file_path)}): {e}")
            return ""

    def _read_txt(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, "r", encoding="cp1254", errors="replace") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"TXT read error ({os.path.basename(file_path)}): {e}")
                return ""
        except Exception as e:
            logger.error(f"TXT read error ({os.path.basename(file_path)}): {e}")
            return ""

    def load_and_chunk_file(self, file_path: str):
        """Read a single file, inject contextual header, and generate chunks."""
        chunks = []
        ids = []
        metadatas = []

        if not os.path.isfile(file_path):
            return chunks, ids, metadatas

        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()

        content = ""
        # Offsets in `content` where each PDF page starts, and the matching page numbers
        page_offsets: List[int] = []
        page_numbers: List[int] = []
        if ext == ".pdf":
            for number, text in self._read_pdf_pages(file_path):
                page_offsets.append(len(content))
                page_numbers.append(number)
                content += f"{text}\n"
        elif ext == ".docx":
            content = self._read_docx(file_path)
        elif ext == ".txt":
            content = self._read_txt(file_path)
        else:
            logger.warning(f"Skipping unsupported file format: {filename}")
            return chunks, ids, metadatas

        if not content.strip():
            return chunks, ids, metadatas

        # Extract contextual header (Contextual Chunking)
        doc_header = self._extract_document_header(content)
        pieces = self._legislation_pieces(content) or self._plain_pieces(content, doc_header)

        for idx, (start, chunk, article) in enumerate(pieces):
            chunk_id = f"{filename}_chunk_{idx}"
            metadata = {"source": filename, "chunk_index": idx, "document_title": doc_header}
            if article:
                metadata["article"] = article
            if page_offsets:
                metadata["page"] = self._page_at(start, page_offsets, page_numbers)
                page_end = self._page_at(start + max(len(chunk) - 1, 0), page_offsets, page_numbers)
                if page_end != metadata["page"]:
                    metadata["page_end"] = page_end
            chunks.append(chunk)
            ids.append(chunk_id)
            metadatas.append(metadata)

        return chunks, ids, metadatas

    def _plain_pieces(self, content: str, doc_header: str) -> List[Tuple[int, str, str]]:
        """(offset, chunk text, article label) for documents without article structure."""
        pieces = []
        for split in self.text_splitter.create_documents([content]):
            chunk = split.page_content
            # Inject document header into each chunk if not already present
            if doc_header and not (chunk.strip().startswith("[Document:") or chunk.strip().startswith("[Belge:")):
                chunk = f"{doc_header}\n{chunk}"
            pieces.append((split.metadata.get("start_index", 0), chunk, ""))
        return pieces

    def _legislation_pieces(self, content: str) -> List[Tuple[int, str, str]]:
        """(offset, chunk text, article label) split by article, or [] if the text is not structured by articles."""
        headings = list(_ARTICLE_RE.finditer(content))
        if len(headings) < MIN_ARTICLES:
            return []
        title = self._legislation_title(content)
        footnote = next((m for m in _FOOTNOTE_RE.finditer(content) if m.start() > headings[-1].start()), None)
        notes_start = footnote.start() if footnote else len(content)
        # Tables after the last article ("2547 SAYILI KANUNA EK VE DEĞİŞİKLİK GETİREN MEVZUATIN ...") start with an
        # upper-case heading line
        appendix = _APPENDIX_RE.search(content, headings[-1].end(), notes_start)
        body_end = appendix.start() if appendix else notes_start

        segments = []  # (start, end, label)
        starts = [self._article_start(content, m) for m in headings]
        if content[: starts[0]].strip():
            segments.append((0, starts[0], ""))
        for i, match in enumerate(headings):
            end = starts[i + 1] if i + 1 < len(headings) else body_end
            segments.append((starts[i], end, self._article_label(content, match)))
        if appendix:
            segments.append((body_end, notes_start, appendix.group(0).strip()[:_MAX_TITLE_LEN]))
        if footnote:
            segments.append((notes_start, len(content), "Dipnotlar (değişiklik notları)"))

        pieces = []
        for start, end, label in segments:
            text = content[start:end].strip("\n")
            if not text.strip():
                continue
            header = f"[{title} | {label}]" if label else f"[{title}]"
            intros = self._list_introductions(text)
            for split in self.article_splitter.create_documents([text]):
                offset = split.metadata.get("start_index", 0)
                # The introduction of a piece's list sits above its first item: a piece starting with "ğ)" gets
                # "(6) Sınavlara ilişkin esaslar şunlardır:", not its sibling "d) Tek ders sınavı:"
                level = _list_level(split.page_content)
                intro = next(
                    (
                        line
                        for pos, line, line_level in reversed(intros)
                        if pos < offset and (level is None or line_level is None or line_level < level)
                    ),
                    "",
                )
                lead = f"({intro})\n" if intro else ""
                body = annotate_numbers(f"{lead}{split.page_content}")
                pieces.append((start + offset, f"{header}\n{body}", label))
        return pieces

    @staticmethod
    def _legislation_title(content: str) -> str:
        """Upper-case title lines at the start, e.g. 'YÜKSEKÖĞRETİM KANUNU'; a title that wraps onto a second line
        after a blank line ('... ÖN LİSANS VE LİSANS' / 'EĞİTİM-ÖĞRETİM VE SINAV YÖNETMELİĞİ') is joined."""
        lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
        title = []
        for line in lines[:3]:
            is_upper = line == line.upper() and any(c.isalpha() for c in line)
            if title and (not is_upper or re.search(r"\b(BÖLÜM|KISIM)\b", line)):
                break
            title.append(line)
            if not is_upper:
                break
        return " ".join(title)[:150] or "Document"

    @staticmethod
    def _title_line_before(content: str, position: int) -> Tuple[int, str]:
        """(offset, text) of the article title on the line before `position`, or (position, '')."""
        before = content[:position].rstrip()
        line_start = before.rfind("\n") + 1
        line = before[line_start:].strip()
        is_title = (
            line
            and len(line) <= _MAX_TITLE_LEN
            and not line.endswith((".", ";", ","))
            and not line.startswith(("(", "["))
            and not re.match(r"^[a-zçğıöşü\d]{1,2}[).]", line)
            and not _ARTICLE_RE.match(line)
            # Upper-case lines are document or section titles ("BİRİNCİ BÖLÜM"), not article titles
            and line != line.upper()
        )
        return (line_start, line.rstrip(":")) if is_title else (position, "")

    def _article_start(self, content: str, match) -> int:
        return self._title_line_before(content, match.start())[0]

    def _article_label(self, content: str, match) -> str:
        """'Madde 30 – Emeklilik yaş haddi', 'Geçici Madde 47', 'Ek Madde 5 – ...'."""
        kind = (match.group("kind") or "")[:1].upper()
        kind = {"G": "Geçici Madde", "E": "Ek Madde"}.get(kind, "Madde")
        label = f"{kind} {match.group('num')}" if match.group("num") else kind
        # Footnote markers of consolidated texts: "Doçentlik ve atama:[21]"
        title = re.sub(r"\s*\[\d+\]", "", self._title_line_before(content, match.start())[1]).rstrip(":").strip()
        return f"{label} – {title}" if title else label

    @staticmethod
    def _list_introductions(text: str) -> List[Tuple[int, str, Optional[int]]]:
        """Lines that introduce a list ('... cezasını gerektiren eylemler şunlardır:') with offsets and list levels.

        Lines before the article heading (the article title, e.g. 'Emeklilik yaş haddi:') are skipped.
        """
        intros, offset, in_body = [], 0, False
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            in_body = in_body or bool(_ARTICLE_RE.match(line))
            if in_body and stripped.endswith(":") and 10 <= len(stripped) <= _MAX_INTRO_LEN:
                intros.append((offset, stripped, _list_level(stripped)))
            offset += len(line)
        return intros

    @staticmethod
    def _page_at(offset: int, page_offsets: List[int], page_numbers: List[int]) -> int:
        """Page number of the character at `offset` in the concatenated PDF text."""
        return page_numbers[max(0, bisect.bisect_right(page_offsets, offset) - 1)]

    def load_and_chunk_all(self):
        """Read and chunk all valid enterprise documents in data/ directory."""
        all_chunks = []
        all_ids = []
        metadatas = []

        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            return all_chunks, all_ids, metadatas

        for filename in os.listdir(self.data_dir):
            file_path = os.path.join(self.data_dir, filename)
            if not os.path.isfile(file_path):
                continue

            chunks, ids, metas = self.load_and_chunk_file(file_path)
            all_chunks.extend(chunks)
            all_ids.extend(ids)
            metadatas.extend(metas)

        return all_chunks, all_ids, metadatas
