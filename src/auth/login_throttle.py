import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from src.core.config import LOGIN_MAX_FAILED_ATTEMPTS, LOGIN_LOCKOUT_WINDOW_SECONDS


class LoginThrottle:
    """Per-username failed login tracker that temporarily locks accounts under brute-force attempts.

    Keyed by username rather than IP so that users sharing a gateway (e.g. a company proxy or the web UI's
    nginx container) do not lock each other out.
    """

    def __init__(
        self,
        max_failures: int = LOGIN_MAX_FAILED_ATTEMPTS,
        window_seconds: int = LOGIN_LOCKOUT_WINDOW_SECONDS,
    ):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        attempts = self._failures[key]
        while attempts and now - attempts[0] >= self.window_seconds:
            attempts.popleft()
        if not attempts:
            del self._failures[key]
            return deque()
        return attempts

    def retry_after(self, username: str) -> int:
        """Return seconds until the account unlocks, or 0 if login attempts are allowed."""
        key = username.lower()
        now = time.time()
        with self._lock:
            attempts = self._prune(key, now)
            if len(attempts) < self.max_failures:
                return 0
            return max(1, int(self.window_seconds - (now - attempts[0])))

    def record_failure(self, username: str) -> None:
        with self._lock:
            self._failures[username.lower()].append(time.time())

    def reset(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username.lower(), None)


login_throttle = LoginThrottle()
