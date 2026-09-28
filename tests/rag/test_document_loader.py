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


REGULATION = """ÖRNEK ÜNİVERSİTESİ ÖNLİSANS VE LİSANS YÖNETMELİĞİ

BİRİNCİ BÖLÜM

Amaç

MADDE 1 – (1) Bu Yönetmeliğin amacı eğitim-öğretim esaslarını düzenlemektir.

Devam zorunluluğu

MADDE 2 – (1) Öğrenciler teorik derslerin en az %70'ine devam etmek zorundadır.

Disiplin

MADDE 3 – (1) Kınama cezasını gerektiren eylemler şunlardır:

{acts}

GEÇİCİ MADDE 1 – (1) Bu Yönetmelik yayımı tarihinde yürürlüğe girer.

YÖNETMELİĞE EK VE DEĞİŞİKLİK GETİREN MEVZUATIN LİSTESİ

Resmi Gazete 12/3/2017 30005

[1] Bu bent 1/1/2020 tarihinde değiştirilmiştir.
"""


class TestLegislationChunking(unittest.TestCase):
    """Laws and regulations are split by article and every chunk names its article."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.loader = DocumentLoader(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _chunk(self, text):
        path = os.path.join(self.temp_dir.name, "yonetmelik.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        chunks, _, metas = self.loader.load_and_chunk_file(path)
        return chunks, metas

    def test_each_article_is_its_own_chunk_with_label(self):
        chunks, metas = self._chunk(REGULATION.format(acts="a) Sınavlarda kopyaya teşebbüs etmek."))
        by_article = {meta.get("article"): chunk for chunk, meta in zip(chunks, metas)}
        self.assertIn("Madde 2 – Devam zorunluluğu", by_article)
        attendance = by_article["Madde 2 – Devam zorunluluğu"]
        self.assertTrue(attendance.startswith("[ÖRNEK ÜNİVERSİTESİ ÖNLİSANS VE LİSANS YÖNETMELİĞİ | Madde 2"))
        self.assertIn("%70", attendance)
        self.assertNotIn("Madde 1", attendance.split("\n", 1)[1])
        self.assertIn("Geçici Madde 1", by_article)
        self.assertIn("Dipnotlar (değişiklik notları)", by_article)
        # Tables after the last article are not part of it
        self.assertNotIn("Resmi Gazete", by_article["Geçici Madde 1"])

    def test_numbers_in_words_get_digits_and_footnote_markers_leave_titles(self):
        text = "KANUN\n\nYaş haddi:[3]\nMadde 1 – Yaş haddi yetmiş beş yaştır.\n\nMadde 2 – İki.\n\nMadde 3 – Üç.\n"
        chunks, metas = self._chunk(text)
        # The first chunk is the document title before the first article
        self.assertEqual(metas[1]["article"], "Madde 1 – Yaş haddi")
        self.assertIn("yetmiş beş (75) yaştır", chunks[1])

    def test_upper_case_title_is_not_an_article_title(self):
        _, metas = self._chunk("BAŞLIK\n\nMadde 1- Birinci.\n\nMadde 2- İkinci.\n\nMadde 3- Üçüncü.\n")
        self.assertEqual([meta.get("article") for meta in metas][-3:], ["Madde 1", "Madde 2", "Madde 3"])

    def test_pieces_of_a_long_list_keep_its_introduction(self):
        acts = "\n\n".join(f"{i}) Eylem numarası {i} olan uzun bir davranış açıklaması." * 3 for i in range(1, 40))
        chunks, metas = self._chunk(REGULATION.format(acts=acts))
        pieces = [chunk for chunk, meta in zip(chunks, metas) if meta.get("article") == "Madde 3 – Disiplin"]
        self.assertGreater(len(pieces), 2)
        for piece in pieces[1:]:
            self.assertIn("(MADDE 3 – (1) Kınama cezasını gerektiren eylemler şunlardır:)", piece)

    def test_documents_without_articles_use_plain_chunks(self):
        chunks, metas = self._chunk("DOKÜMAN: İzin Prosedürü\n\nİzinler portal üzerinden alınır. Madde 1 bkz.")
        self.assertNotIn("article", metas[0])
        self.assertTrue(chunks[0].startswith("[Document: İzin Prosedürü]"))
