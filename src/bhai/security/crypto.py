"""
Fernet symmetric encryption for PII data at rest.
Encrypts user profiles, conversation content, and audio files.

Keys are loaded from environment variables — never hardcoded.
"""

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


def _get_key(env_var: str) -> bytes:
    """Load encryption key from environment variable."""
    key = os.getenv(env_var)
    if not key:
        raise RuntimeError(
            f"{env_var} not set. Generate one with: "
            f'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return key.encode()


def get_fernet(env_var: str = "BHAI_ENCRYPTION_KEY") -> Fernet:
    """Get a Fernet instance using the key from the given env var."""
    return Fernet(_get_key(env_var))


def encrypt_text(plaintext: str, env_var: str = "BHAI_ENCRYPTION_KEY") -> str:
    """Encrypt a string, returning base64-encoded ciphertext."""
    f = get_fernet(env_var)
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(ciphertext: str, env_var: str = "BHAI_ENCRYPTION_KEY") -> str:
    """Decrypt base64-encoded ciphertext back to string."""
    f = get_fernet(env_var)
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Decryption failed — wrong key or corrupted data.")


def encrypt_file(
    input_path: Path,
    output_path: Optional[Path] = None,
    env_var: str = "BHAI_ENCRYPTION_KEY",
) -> Path:
    """Encrypt a file. If output_path is None, encrypts in-place with .enc suffix."""
    if output_path is None:
        output_path = input_path.with_suffix(input_path.suffix + ".enc")
    f = get_fernet(env_var)
    plaintext = input_path.read_bytes()
    output_path.write_bytes(f.encrypt(plaintext))
    return output_path


def decrypt_file(
    input_path: Path,
    output_path: Optional[Path] = None,
    env_var: str = "BHAI_ENCRYPTION_KEY",
) -> Path:
    """Decrypt a file. If output_path is None, strips .enc suffix."""
    if output_path is None:
        name = input_path.name
        if name.endswith(".enc"):
            output_path = input_path.with_name(name[:-4])
        else:
            output_path = input_path.with_suffix(".dec")
    f = get_fernet(env_var)
    ciphertext = input_path.read_bytes()
    try:
        output_path.write_bytes(f.decrypt(ciphertext))
    except InvalidToken:
        raise ValueError(f"Decryption failed for {input_path}")
    return output_path


def decrypt_file_to_memory(
    input_path: Path, env_var: str = "BHAI_ENCRYPTION_KEY"
) -> bytes:
    """Decrypt a file and return contents in memory (no disk write)."""
    f = get_fernet(env_var)
    try:
        return f.decrypt(input_path.read_bytes())
    except InvalidToken:
        raise ValueError(f"Decryption failed for {input_path}")


def generate_key() -> str:
    """Generate a new Fernet key. Use this to create BHAI_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode()
