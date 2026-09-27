import bisect
import os
import re
from typing import List, Tuple

from pypdf import PdfReader
from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.core.config import CHUNK_SIZE, CHUNK_OVERLAP
from src.core.logger import get_logger

logger = get_logger("DocumentLoader")


class DocumentLoader:
    """Document loader and contextual chunker for enterprise PDF, DOCX, and TXT files."""

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

        for idx, split in enumerate(self.text_splitter.create_documents([content])):
            chunk = split.page_content
            # Inject document header into each chunk if not already present
            if doc_header and not (chunk.strip().startswith("[Document:") or chunk.strip().startswith("[Belge:")):
                contextualized_chunk = f"{doc_header}\n{chunk}"
            else:
                contextualized_chunk = chunk

            chunk_id = f"{filename}_chunk_{idx}"
            metadata = {"source": filename, "chunk_index": idx, "document_title": doc_header}
            if page_offsets:
                start = split.metadata.get("start_index", 0)
                metadata["page"] = self._page_at(start, page_offsets, page_numbers)
                page_end = self._page_at(start + len(chunk) - 1, page_offsets, page_numbers)
                if page_end != metadata["page"]:
                    metadata["page_end"] = page_end
            chunks.append(contextualized_chunk)
            ids.append(chunk_id)
            metadatas.append(metadata)

        return chunks, ids, metadatas

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
