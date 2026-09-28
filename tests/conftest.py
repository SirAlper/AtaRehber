"""Test session setup.

Runs before any test module imports `src`, so configuration read at import time
(data directory, user store, audit DB, rate limits) points at an isolated temp directory
instead of the developer's real data/ folder.
"""

import os
import shutil
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="olra_test_data_")

os.environ["DATA_DIR"] = _TEST_DATA_DIR
os.environ["LOG_FILE"] = os.path.join(_TEST_DATA_DIR, "test.log")
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["RATE_LIMIT_READS_PER_MINUTE"] = "100000"
# Tests run the same questions against different stand-in engines; tests of the cache turn it on
os.environ["ANSWER_CACHE_SIZE"] = "0"
# Suites log in as the seeded admin/admin123; enforcement itself is covered in test_security_hardening.py
os.environ["REQUIRE_DEFAULT_PASSWORD_CHANGE"] = "false"


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
