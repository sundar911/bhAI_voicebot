"""
Tests for src/bhai/security/crypto.py — Fernet encryption.

The conftest autouse fixture sets BHAI_ENCRYPTION_KEY for every test,
so all calls using the default env_var work without extra setup.
"""

import pytest
from cryptography.fernet import Fernet

from bhai.security.crypto import (
    decrypt_file,
    decrypt_file_to_memory,
    decrypt_text,
    encrypt_file,
    encrypt_text,
    generate_key,
    get_fernet,
)


def test_generate_key_is_valid_fernet():
    """generate_key() produces a string that can initialize a Fernet instance."""
    key = generate_key()
    assert isinstance(key, str)
    # Should not raise
    Fernet(key.encode())


def test_encrypt_decrypt_string_round_trip():
    """encrypt_text / decrypt_text are inverses for arbitrary UTF-8 strings."""
    plaintext = "मेरी salary क्यों कटी? 50000 ₹ होनी चाहिए थी।"
    ciphertext = encrypt_text(plaintext)
    assert ciphertext != plaintext
    assert decrypt_text(ciphertext) == plaintext


def test_encrypt_produces_different_ciphertext_each_time():
    """Fernet uses random IVs — same plaintext → different ciphertext each call."""
    text = "hello"
    ct1 = encrypt_text(text)
    ct2 = encrypt_text(text)
    assert ct1 != ct2


def test_decrypt_wrong_key_raises(monkeypatch):
    """Decrypting with a different key raises ValueError."""
    ciphertext = encrypt_text("secret")

    # Swap in a different key
    other_key = Fernet.generate_key().decode()
    monkeypatch.setenv("BHAI_ENCRYPTION_KEY", other_key)

    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_text(ciphertext)


def test_missing_env_var_raises(monkeypatch):
    """get_fernet() raises RuntimeError when the env var is not set."""
    monkeypatch.delenv("BHAI_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="BHAI_ENCRYPTION_KEY not set"):
        get_fernet("BHAI_ENCRYPTION_KEY")


def test_encrypt_file_round_trip(tmp_path):
    """encrypt_file / decrypt_file preserve file contents."""
    src = tmp_path / "data.txt"
    src.write_text("Tiny Miracles payroll data")

    enc = encrypt_file(src, tmp_path / "data.txt.enc")
    assert enc.exists()
    assert enc.read_bytes() != src.read_bytes()

    dec = decrypt_file(enc, tmp_path / "data_out.txt")
    assert dec.read_text() == "Tiny Miracles payroll data"


def test_decrypt_file_to_memory(tmp_path):
    """decrypt_file_to_memory returns plaintext bytes without writing to disk."""
    src = tmp_path / "secret.bin"
    src.write_bytes(b"\x00\x01\x02binary data")

    enc = encrypt_file(src)
    result = decrypt_file_to_memory(enc)
    assert result == b"\x00\x01\x02binary data"
