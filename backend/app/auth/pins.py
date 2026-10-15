"""Staff PINs.

Staff log in by typing their PIN alone (no name to pick), so the backend must find the
person from the PIN. We store a keyed hash (HMAC-SHA256 with `pin_secret`) rather than
the PIN: it can be looked up directly, and without the secret key, which is kept out of
the database, a copied database or backup reveals no PINs.
"""

import hashlib
import hmac
import uuid

PIN_LENGTHS = range(4, 7)


class WeakPin(ValueError):
    pass


def pin_lookup(secret: str, business_id: uuid.UUID, pin: str) -> str:
    message = f"{business_id}:{pin}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def check_new_pin(pin: str) -> None:
    """Rules for a PIN the owner sets. Raises WeakPin with a message for the screen."""
    if not pin.isdigit() or len(pin) not in PIN_LENGTHS:
        raise WeakPin("A PIN must be 4 to 6 digits.")
    if len(set(pin)) == 1:
        raise WeakPin("A PIN can't be the same digit repeated.")
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    if steps in ({1}, {-1}):
        raise WeakPin("A PIN can't be a run of digits like 1234.")
