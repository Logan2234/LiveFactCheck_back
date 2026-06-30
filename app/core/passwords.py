"""Password hashing with argon2id (OWASP first-choice KDF).

Pure logic — no FastAPI, no I/O. ``argon2-cffi`` generates a random salt and encodes it,
together with the algorithm and cost parameters, inside the returned hash string; there
is no separate salt to store. Verification is constant-time and tolerant of a malformed
stored value (returns ``False`` instead of raising).
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2id hash string (salt + params embedded)."""
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """True if ``password`` matches ``stored_hash``; False on mismatch or bad hash."""
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False
