import os
import io
import unittest
from fastapi.testclient import TestClient
from src.api.main import app, get_rag_engine
from src.core.config import DOCS_PATH


class TestAPISecurityAndEndpoints(unittest.TestCase):
    """Tests for API upload security validation and endpoint guards."""

    @classmethod
    def setUpClass(cls):
        # We don't start the entire LLM model pipeline in tests to keep execution fast
        cls.client = TestClient(app, raise_server_exceptions=False)
        from src.auth.jwt_handler import create_access_token

        token, _ = create_access_token("admin", "admin")
        cls.auth_headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def tearDownClass(cls):
        # Clean up any test files created in data/
        test_file = os.path.join(DOCS_PATH, "safe_note.txt")
        if os.path.exists(test_file):
            try:
                os.remove(test_file)
            except Exception:
                pass
        try:
            get_rag_engine().delete_document("safe_note.txt")
        except Exception:
            pass

    def test_upload_rejected_for_unsupported_extension(self):
        fake_exe = io.BytesIO(b"MZ...fake executable content")
        response = self.client.post(
            "/api/v1/upload-file",
            headers=self.auth_headers,
            files={"file": ("malicious.exe", fake_exe, "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file extension", response.json()["detail"])

    def test_upload_rejected_for_script(self):
        fake_sh = io.BytesIO(b"#!/bin/bash\nrm -rf /")
        response = self.client.post(
            "/api/v1/upload-file",
            headers=self.auth_headers,
            files={"file": ("exploit.sh", fake_sh, "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file extension", response.json()["detail"])

    def test_upload_path_traversal_sanitized(self):
        fake_txt = io.BytesIO(b"DOCUMENT: Safe File\nSome safe content.")
        response = self.client.post(
            "/api/v1/upload-file",
            headers=self.auth_headers,
            files={"file": ("../../etc/safe_note.txt", fake_txt, "text/plain")},
        )
        # Should succeed because os.path.basename stripped ../../etc/ -> safe_note.txt
        # Or return 200/400 without creating outside DOCS_PATH
        if response.status_code == 200:
            self.assertEqual(response.json()["filename"], "safe_note.txt")

    def test_delete_document_path_traversal_rejected(self):
        response = self.client.delete(
            "/api/v1/documents/..%2F..%2Fetc%2Fpasswd",
            headers=self.auth_headers,
        )
        # Should reject invalid path traversal
        self.assertIn(response.status_code, [400, 404])


if __name__ == "__main__":
    unittest.main()
