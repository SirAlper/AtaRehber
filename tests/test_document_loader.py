import os
import tempfile
import unittest
import unittest.mock
from src.rag.document_loader import DocumentLoader


class TestDocumentLoader(unittest.TestCase):
    """Tests for document loading, header extraction, and chunking."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.loader = DocumentLoader(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extract_document_header_english(self):
        content = """DOCUMENT: Information Security Policy
CODE: SEC-POL-04
Date: 2026-01-01

All employees must follow the security guidelines."""
        header = DocumentLoader._extract_document_header(content)
        self.assertEqual(header, "[Document: Information Security Policy | CODE: SEC-POL-04]")

    def test_extract_document_header_turkish(self):
        content = """DOKÜMAN: Yıllık İzin Prosedürü
KOD: IK-PRO-12
Tarih: 2026-01-01

Tüm personelin izin talepleri İK portalı üzerinden alınır."""
        header = DocumentLoader._extract_document_header(content)
        self.assertEqual(header, "[Document: Yıllık İzin Prosedürü | CODE: IK-PRO-12]")

    def test_extract_document_header_title_only(self):
        content = """DOCUMENT: Code of Conduct
Some other text here."""
        header = DocumentLoader._extract_document_header(content)
        self.assertEqual(header, "[Document: Code of Conduct]")

    def test_extract_document_header_none(self):
        content = "Just plain text without document keyword."
        header = DocumentLoader._extract_document_header(content)
        self.assertEqual(header, "")

    def test_load_and_chunk_txt_file(self):
        sample_file = os.path.join(self.temp_dir.name, "sample_policy.txt")
        with open(sample_file, "w", encoding="utf-8") as f:
            f.write("""DOCUMENT: Enterprise Data Retention
CODE: DTR-01

Employees must retain records for a minimum period of 5 years.
Archived documents must be encrypted at rest and in transit.""")

        chunks, ids, metas = self.loader.load_and_chunk_file(sample_file)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertIn("[Document: Enterprise Data Retention | CODE: DTR-01]", chunks[0])
        self.assertEqual(metas[0]["source"], "sample_policy.txt")

    def test_unsupported_file_extension(self):
        bad_file = os.path.join(self.temp_dir.name, "script.sh")
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\necho hello")

        chunks, ids, metas = self.loader.load_and_chunk_file(bad_file)
        self.assertEqual(len(chunks), 0)


if __name__ == "__main__":
    unittest.main()


class TestPdfPageNumbers(unittest.TestCase):
    """PDF chunks record the page they start on (and end on, if it differs)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.loader = DocumentLoader(self.temp_dir.name)
        self.pdf = os.path.join(self.temp_dir.name, "regulation.pdf")
        open(self.pdf, "wb").close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_chunks_carry_start_and_end_pages(self):
        # Short pages: the first chunk holds pages 1 and 2. Page 3 has no extractable text (e.g. a scan).
        pages = [(1, "Madde 1 " + "a " * 120), (2, "Madde 2 " + "b " * 120), (4, "Madde 4 " + "c " * 50)]
        with unittest.mock.patch.object(self.loader, "_read_pdf_pages", return_value=pages):
            chunks, _, metas = self.loader.load_and_chunk_file(self.pdf)

        self.assertEqual((metas[0]["page"], metas[0]["page_end"]), (1, 2))
        self.assertTrue(chunks[0].startswith("Madde 1") and "Madde 2" in chunks[0])
        self.assertEqual(metas[-1]["page"], 4)
        self.assertNotIn("page_end", metas[-1])
        self.assertTrue(chunks[-1].startswith("Madde 4"))

    def test_long_pages_split_within_the_page(self):
        pages = [(1, "A" * 700), (2, "B" * 700)]
        with unittest.mock.patch.object(self.loader, "_read_pdf_pages", return_value=pages):
            chunks, _, metas = self.loader.load_and_chunk_file(self.pdf)
        for chunk, meta in zip(chunks, metas):
            self.assertEqual(meta["page"], 1 if chunk[0] == "A" else 2)

    def test_non_pdf_files_have_no_page(self):
        txt = os.path.join(self.temp_dir.name, "notes.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write("Plain text without pages.")
        _, _, metas = self.loader.load_and_chunk_file(txt)
        self.assertNotIn("page", metas[0])
