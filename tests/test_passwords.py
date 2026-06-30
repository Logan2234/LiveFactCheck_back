"""Tests for argon2 password hashing (core/passwords.py)."""

from app.core.passwords import hash_password, verify_password


def test_hash_is_not_plaintext_and_is_argon2() -> None:
    h = hash_password("hunter2pass")
    assert h != "hunter2pass"
    assert h.startswith("$argon2")


def test_verify_accepts_correct_and_rejects_wrong() -> None:
    h = hash_password("hunter2pass")
    assert verify_password(h, "hunter2pass") is True
    assert verify_password(h, "wrong-password") is False


def test_verify_rejects_malformed_hash() -> None:
    # A garbage stored value must not raise, just fail to verify.
    assert verify_password("not-a-real-hash", "whatever") is False


def test_same_password_hashes_differ_due_to_salt() -> None:
    assert hash_password("samepassword") != hash_password("samepassword")
