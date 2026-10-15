"""The owner's phone login on the cloud (masterplan 10): email, a strong password and a
one-time code from an authenticator app (TOTP, RFC 6238), so a stolen password alone
is not enough. Phone access is read-only in Version 1."""

import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from urllib.parse import quote

PASSWORD_MIN = 10
TOKEN_HOURS = 12
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(test.hex(), digest)


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, at: float | None = None, step: int = 30) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def check_totp(secret: str, code: str, at: float | None = None) -> bool:
    """Accepts the current code and the ones either side, for phones a little off time."""
    now = time.time() if at is None else at
    return any(hmac.compare_digest(totp(secret, now + d * 30), code.strip()) for d in (-1, 0, 1))


def totp_uri(secret: str, email: str, issuer: str = "Faida POS") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}"


@dataclass
class OwnerToken:
    owner_id: uuid.UUID
    business_id: uuid.UUID


def _sign(key: str, data: bytes) -> str:
    return hmac.new(f"owner-token:{key}".encode(), data, hashlib.sha256).hexdigest()


def issue_token(key: str, owner_id: uuid.UUID, business_id: uuid.UUID) -> str:
    body = json.dumps({"o": str(owner_id), "b": str(business_id), "exp": int(time.time()) + TOKEN_HOURS * 3600})
    data = base64.urlsafe_b64encode(body.encode())
    return f"{data.decode()}.{_sign(key, data)}"


def read_token(key: str, token: str) -> OwnerToken | None:
    try:
        data, sig = token.split(".")
        if not hmac.compare_digest(_sign(key, data.encode()), sig):
            return None
        body = json.loads(base64.urlsafe_b64decode(data))
        if body["exp"] < time.time():
            return None
        return OwnerToken(uuid.UUID(body["o"]), uuid.UUID(body["b"]))
    except (ValueError, KeyError):
        return None


class LoginGuard:
    """Repeated failed logins for one email lock it for a few minutes."""

    def __init__(self):
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def locked(self, email: str) -> bool:
        with self._lock:
            recent = [t for t in self._fails.get(email, []) if time.time() - t < LOCKOUT_SECONDS]
            self._fails[email] = recent
            return len(recent) >= MAX_FAILURES

    def failed(self, email: str) -> None:
        with self._lock:
            self._fails.setdefault(email, []).append(time.time())

    def succeeded(self, email: str) -> None:
        with self._lock:
            self._fails.pop(email, None)
