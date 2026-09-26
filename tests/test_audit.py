import os
import shutil
import tempfile
import unittest
from fastapi.testclient import TestClient

from src.api.main import app
from src.auth.jwt_handler import create_access_token
from src.core.audit import AuditLogger


class TestAuditLogger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, "test_audit.db")
        cls.logger = AuditLogger(db_path=cls.db_path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_log_and_query_events(self):
        """Test creating and filtering audit logs."""
        # 1. Log query event
        id1 = self.logger.log(
            username="analyst_1",
            role="viewer",
            action="query",
            detail="What is the travel expense policy?",
            sources=["travel_policy.pdf"],
            answer_preview="Employees are reimbursed for economy flights.",
            ip_address="192.168.1.50",
            duration_ms=450,
            status="success",
        )
        self.assertGreater(id1, 0)

        # 2. Log upload event
        id2 = self.logger.log(
            username="hr_admin",
            role="admin",
            action="upload",
            detail="Uploaded 'q3_report.pdf'",
            ip_address="192.168.1.10",
            status="success",
        )
        self.assertGreater(id2, 0)

        # 3. Log error event
        id3 = self.logger.log(
            username="bad_actor",
            role="unknown",
            action="login",
            detail="Invalid credentials",
            ip_address="10.0.0.99",
            status="denied",
        )
        self.assertGreater(id3, 0)

        # 4. Filter by username
        analyst_logs = self.logger.query_logs(username="analyst_1")
        self.assertEqual(len(analyst_logs), 1)
        self.assertEqual(analyst_logs[0]["action"], "query")
        self.assertEqual(analyst_logs[0]["sources_used"], ["travel_policy.pdf"])

        # 5. Filter by action
        upload_logs = self.logger.query_logs(action="upload")
        self.assertEqual(len(upload_logs), 1)
        self.assertEqual(upload_logs[0]["username"], "hr_admin")

        # 6. Filter by status
        denied_logs = self.logger.query_logs(status="denied")
        self.assertEqual(len(denied_logs), 1)
        self.assertEqual(denied_logs[0]["username"], "bad_actor")

        # 7. Count logs
        total = self.logger.count_logs()
        self.assertEqual(total, 3)
        self.assertEqual(self.logger.count_logs(action="query"), 1)
        self.assertEqual(self.logger.count_logs(status="denied"), 1)


class TestAdminAuditEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        from src.auth.user_store import user_store

        if not user_store.get_user("audit_viewer"):
            user_store.create_user("audit_viewer", "ViewerPass123!", "viewer")

        admin_token, _ = create_access_token("admin", "admin")
        cls.admin_headers = {"Authorization": f"Bearer {admin_token}"}

        viewer_token, _ = create_access_token("audit_viewer", "viewer")
        cls.viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    @classmethod
    def tearDownClass(cls):
        from src.auth.user_store import user_store

        if user_store.get_user("audit_viewer"):
            user_store.delete_user("audit_viewer")

    def test_audit_logs_rbac_protection(self):
        """Verify viewer is rejected (403) and admin can access audit logs."""
        # Viewer access -> 403 Forbidden
        viewer_resp = self.client.get("/api/v1/admin/audit-logs", headers=self.viewer_headers)
        self.assertEqual(viewer_resp.status_code, 403)

        # Admin access -> 200 OK
        admin_resp = self.client.get("/api/v1/admin/audit-logs", headers=self.admin_headers)
        self.assertEqual(admin_resp.status_code, 200)
        data = admin_resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("logs", data)
        self.assertIn("total", data)

    def test_audit_stats_endpoint(self):
        """Verify admin can retrieve audit metrics summary."""
        resp = self.client.get("/api/v1/admin/audit-stats", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("total_records", data)
        self.assertIn("queries_executed", data)
        self.assertIn("documents_uploaded", data)


if __name__ == "__main__":
    unittest.main()
