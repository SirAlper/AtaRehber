import os
import tempfile
import unittest
from src.connectors.db_connector import DatabaseConnector, create_sample_sqlite_db
from src.connectors.db_loader import DatabaseTableLoader


class TestDatabaseSecurityAndConnector(unittest.TestCase):
    """Tests for DatabaseConnector read-only guards and DatabaseTableLoader whitelist."""

    def setUp(self):
        # Create a temporary SQLite database
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_enterprise.db")
        create_sample_sqlite_db(self.db_path)
        self.db_url = f"sqlite:///{self.db_path}"
        self.connector = DatabaseConnector(database_url=self.db_url)

    def tearDown(self):
        if self.connector.engine:
            self.connector.engine.dispose()
        self.temp_dir.cleanup()

    def test_connection_and_table_listing(self):
        res = self.connector.test_connection()
        self.assertEqual(res["status"], "connected")
        self.assertIn("urunler", res["tables"])
        self.assertIn("satislar", res["tables"])

    def test_safe_select_query(self):
        res = self.connector.execute_query("SELECT * FROM urunler LIMIT 2")
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["rows"]), 2)
        self.assertIn("urun_adi", res["columns"])

    def test_block_insert(self):
        res = self.connector.execute_query("INSERT INTO urunler (urun_adi) VALUES ('Hacked')")
        self.assertEqual(res["status"], "error")
        self.assertIn("Security Guard", res["message"])

    def test_block_delete(self):
        res = self.connector.execute_query("DELETE FROM urunler WHERE 1=1")
        self.assertEqual(res["status"], "error")
        self.assertIn("Security Guard", res["message"])

    def test_block_drop(self):
        res = self.connector.execute_query("DROP TABLE urunler")
        self.assertEqual(res["status"], "error")
        self.assertIn("Security Guard", res["message"])

    def test_block_update(self):
        res = self.connector.execute_query("UPDATE urunler SET birim_fiyat = 0")
        self.assertEqual(res["status"], "error")
        self.assertIn("Security Guard", res["message"])

    def test_allowed_tables_enforcement(self):
        # Connector restricted only to 'urunler'
        restricted_conn = DatabaseConnector(database_url=self.db_url, allowed_tables=["urunler"])
        # Querying allowed table should succeed
        res_ok = restricted_conn.execute_query("SELECT * FROM urunler")
        self.assertEqual(res_ok["status"], "success")

        # Querying unpermitted table should fail
        res_blocked = restricted_conn.execute_query("SELECT * FROM satislar")
        self.assertEqual(res_blocked["status"], "error")
        self.assertIn("Security Guard", res_blocked["message"])
        restricted_conn.engine.dispose()

    def test_table_loader_whitelist(self):
        loader = DatabaseTableLoader(self.connector)
        # Valid table should load chunks
        chunks, ids, metas = loader.load_table_as_chunks("urunler")
        self.assertGreater(len(chunks), 0)

        # Non-existent or malicious table name should be rejected
        bad_chunks, bad_ids, bad_metas = loader.load_table_as_chunks("non_existent_table")
        self.assertEqual(len(bad_chunks), 0)

        # SQL injection attempt in table_name
        inject_chunks, _, _ = loader.load_table_as_chunks("urunler; DROP TABLE satislar; --")
        self.assertEqual(len(inject_chunks), 0)


if __name__ == "__main__":
    unittest.main()
