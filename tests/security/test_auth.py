import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from fastapi.testclient import TestClient

from src.api.main import app
from src.auth.jwt_handler import create_access_token, decode_access_token
from src.auth.user_store import UserStore, hash_password, verify_password


class TestEnterpriseAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.test_users_file = os.path.join(cls.test_dir, "test_users.json")
        cls.custom_store = UserStore(file_path=cls.test_users_file)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_bcrypt_hashing_and_verification(self):
        """Verify bcrypt password hashing, salting and verification."""
        password = "EnterpriseSecurePassword!99"
        hashed = hash_password(password)
        self.assertNotEqual(password, hashed)
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("WrongPassword", hashed))

    def test_default_admin_seeded(self):
        """Verify that default admin account is seeded if user store is initialized empty."""
        admin_user = self.custom_store.get_user("admin")
        self.assertIsNotNone(admin_user)
        self.assertEqual(admin_user.role, "admin")
        self.assertFalse(admin_user.disabled)
        self.assertTrue(verify_password("admin123", admin_user.hashed_password))

    def test_user_crud_operations(self):
        """Test user creation, retrieval, duplicate check, update, and deletion."""
        # Create
        user = self.custom_store.create_user("analyst1", "AnalystSecret123!", "editor")
        self.assertEqual(user.username, "analyst1")
        self.assertEqual(user.role, "editor")

        # Duplicate rejection
        with self.assertRaises(ValueError):
            self.custom_store.create_user("analyst1", "AnotherPass123!", "viewer")

        # Retrieval
        fetched = self.custom_store.get_user("analyst1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.role, "editor")

        # Update role & status
        updated = self.custom_store.update_user("analyst1", role="viewer", disabled=True)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.role, "viewer")
        self.assertTrue(updated.disabled)

        # Authenticate disabled user returns None
        auth_disabled = self.custom_store.authenticate_user("analyst1", "AnalystSecret123!")
        self.assertIsNone(auth_disabled)

        # Re-enable user
        self.custom_store.update_user("analyst1", disabled=False)
        auth_ok = self.custom_store.authenticate_user("analyst1", "AnalystSecret123!")
        self.assertIsNotNone(auth_ok)

        # Delete user
        deleted = self.custom_store.delete_user("analyst1")
        self.assertTrue(deleted)
        self.assertIsNone(self.custom_store.get_user("analyst1"))

    def test_prevent_primary_admin_deletion(self):
        """Verify that the primary admin user cannot be deleted."""
        with self.assertRaises(ValueError):
            self.custom_store.delete_user("admin")

    def test_jwt_token_generation_and_decoding(self):
        """Verify JWT token creation, decoding, and tamper resistance."""
        token, expires_in = create_access_token("test_user", "editor")
        self.assertIsInstance(token, str)
        self.assertGreater(expires_in, 0)

        data = decode_access_token(token)
        self.assertIsNotNone(data)
        self.assertEqual(data.username, "test_user")
        self.assertEqual(data.role, "editor")

        # Tampered token check
        tampered_token = token[:-5] + "XXXXX"
        self.assertIsNone(decode_access_token(tampered_token))

    def test_jwt_token_expiration(self):
        """Verify that expired JWT token is rejected."""
        expired_token, _ = create_access_token("old_user", "viewer", expires_delta=timedelta(seconds=-10))
        data = decode_access_token(expired_token)
        self.assertIsNone(data)


class TestAuthAPIEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        from src.auth.user_store import user_store

        # Ensure admin exists
        if not user_store.get_user("admin"):
            user_store.create_user("admin", "admin123", "admin")

        # Create test editor
        if not user_store.get_user("test_editor"):
            user_store.create_user("test_editor", "EditorPass123", "editor")

        # Create test viewer
        if not user_store.get_user("test_viewer"):
            user_store.create_user("test_viewer", "ViewerPass123", "viewer")

    def _get_token(self, username, password):
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["access_token"]

    def test_browser_clients_keep_the_refresh_token_in_an_httponly_cookie(self):
        client = TestClient(app)
        cookie = {"X-Token-Transport": "cookie"}
        login = client.post(
            "/api/v1/auth/login", json={"username": "test_viewer", "password": "ViewerPass123"}, headers=cookie
        )
        self.assertEqual(login.status_code, 200, login.text)
        # Not in the body, where a page script could read it
        self.assertIsNone(login.json()["refresh_token"])
        set_cookie = login.headers["set-cookie"]
        for attribute in ("olr_refresh=", "HttpOnly", "SameSite=strict", "Path=/api/v1/auth"):
            self.assertIn(attribute.lower(), set_cookie.lower())

        # The browser sends the cookie back; no body needed
        refreshed = client.post("/api/v1/auth/refresh", headers=cookie)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["username"], "test_viewer")
        self.assertIsNone(refreshed.json()["refresh_token"])

        self.assertEqual(client.post("/api/v1/auth/logout").status_code, 200)
        self.assertEqual(client.post("/api/v1/auth/refresh", headers=cookie).status_code, 401)

    def test_other_clients_still_get_the_refresh_token_in_the_body(self):
        client = TestClient(app)
        login = client.post("/api/v1/auth/login", json={"username": "test_viewer", "password": "ViewerPass123"})
        refresh_token = login.json()["refresh_token"]
        self.assertTrue(refresh_token)
        self.assertNotIn("set-cookie", login.headers)
        refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        self.assertEqual(refreshed.status_code, 200)
        self.assertTrue(refreshed.json()["refresh_token"])

    def test_login_success_and_failure(self):
        """Test login endpoint with valid and invalid credentials."""
        # Success
        token = self._get_token("admin", "admin123")
        self.assertTrue(len(token) > 20)

        # Invalid password
        fail_resp = self.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "WrongPassword!"},
        )
        self.assertEqual(fail_resp.status_code, 401)

        # Non-existent user
        fail_resp2 = self.client.post(
            "/api/v1/auth/login",
            json={"username": "ghost_user", "password": "anypassword"},
        )
        self.assertEqual(fail_resp2.status_code, 401)

    def test_unauthorized_access_rejected(self):
        """Verify that protected endpoints reject requests without token."""
        resp = self.client.get("/api/v1/auth/me")
        self.assertEqual(resp.status_code, 401)

        stats_resp = self.client.get("/api/v1/stats")
        self.assertEqual(stats_resp.status_code, 401)

        docs_resp = self.client.get("/api/v1/documents")
        self.assertEqual(docs_resp.status_code, 401)

    def test_get_current_user_profile(self):
        """Verify /api/v1/auth/me returns current user data."""
        token = self._get_token("test_viewer", "ViewerPass123")
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["username"], "test_viewer")
        self.assertEqual(data["role"], "viewer")

    def test_rbac_admin_can_register_users(self):
        """Verify only admin can create new users via /api/v1/auth/register."""
        from src.auth.user_store import user_store

        # Ensure user doesn't exist from prior runs
        test_username = "new_sub_user_test"
        if user_store.get_user(test_username):
            user_store.delete_user(test_username)

        admin_token = self._get_token("admin", "admin123")
        viewer_token = self._get_token("test_viewer", "ViewerPass123")

        try:
            # Viewer attempt -> 403 Forbidden
            viewer_resp = self.client.post(
                "/api/v1/auth/register",
                headers={"Authorization": f"Bearer {viewer_token}"},
                json={
                    "username": test_username,
                    "password": "Password123!",
                    "role": "viewer",
                },
            )
            self.assertEqual(viewer_resp.status_code, 403)

            # Admin attempt -> 201 Created
            admin_resp = self.client.post(
                "/api/v1/auth/register",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "username": test_username,
                    "password": "Password123!",
                    "role": "viewer",
                },
            )
            self.assertEqual(admin_resp.status_code, 201)
            self.assertEqual(admin_resp.json()["username"], test_username)
        finally:
            if user_store.get_user(test_username):
                user_store.delete_user(test_username)

    def test_rbac_document_deletion_permissions(self):
        """Verify viewers cannot delete documents while editors and admins can."""
        viewer_token = self._get_token("test_viewer", "ViewerPass123")

        # Viewer attempt -> 403 Forbidden
        resp = self.client.delete(
            "/api/v1/documents/non_existent.txt",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
