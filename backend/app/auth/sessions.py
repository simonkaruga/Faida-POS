"""Counter sessions and the keypad lockout.

Both are kept in memory: the counter runs one backend process, and a restart simply
means everyone enters their PIN again, which they do after every send anyway.
"""

import math
import secrets
import threading
import time
import uuid
from dataclasses import dataclass


@dataclass
class CounterSession:
    staff_id: uuid.UUID
    business_id: uuid.UUID
    last_seen: float


class SessionStore:
    def __init__(self, idle_seconds: float, clock=time.monotonic):
        self._idle = idle_seconds
        self._clock = clock
        self._sessions: dict[str, CounterSession] = {}
        self._lock = threading.Lock()

    def start(self, staff_id: uuid.UUID, business_id: uuid.UUID) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = CounterSession(staff_id, business_id, self._clock())
        return token

    def touch(self, token: str) -> CounterSession | None:
        """Return the live session for this token and mark it used, or None."""
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if self._clock() - session.last_seen > self._idle:
                del self._sessions[token]
                return None
            session.last_seen = self._clock()
            return session

    def end(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)


class KeypadGuard:
    """After too many wrong PINs in a row, the keypad pauses for everyone.

    Staff log in with a PIN alone, so a wrong PIN can't be tied to one person; the
    pause is therefore per counter rather than per user. A correct PIN resets it.
    """

    def __init__(self, max_attempts: int, lockout_seconds: float, clock=time.monotonic):
        self._max = max_attempts
        self._lockout = lockout_seconds
        self._clock = clock
        self._failures = 0
        self._locked_until = 0.0
        self._lock = threading.Lock()

    def seconds_locked(self) -> int:
        with self._lock:
            return max(0, math.ceil(self._locked_until - self._clock()))

    def failed(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._max:
                self._failures = 0
                self._locked_until = self._clock() + self._lockout

    def succeeded(self) -> None:
        with self._lock:
            self._failures = 0
