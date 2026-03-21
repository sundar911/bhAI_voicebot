"""
Shared pytest fixtures for the bhAI test suite.
"""

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def set_test_encryption_key(monkeypatch):
    """
    Set a fresh Fernet encryption key for every test.

    Ensures tests that touch crypto or ConversationStore never need a real
    BHAI_ENCRYPTION_KEY in the environment — and each test gets an isolated key.
    """
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("BHAI_ENCRYPTION_KEY", key)
    return key


@pytest.fixture
def tmp_knowledge_base(tmp_path):
    """
    Minimal knowledge base directory for LLM and FAQ tests.

    Creates the shared/ and hr_admin/ folders with stub content files
    so BaseLLM and FAQCache don't raise on missing dirs.
    """
    kb = tmp_path / "knowledge_base"
    (kb / "shared").mkdir(parents=True)
    (kb / "hr_admin").mkdir(parents=True)

    (kb / "shared" / "company_overview.md").write_text(
        "Tiny Miracles is a nonprofit in Mumbai supporting artisans."
    )
    (kb / "shared" / "escalation_policy.md").write_text(
        "Escalate health emergencies and salary disputes to HR."
    )
    (kb / "shared" / "style_guide.md").write_text(
        "Be warm, brief, and direct. No corporate language."
    )
    return kb


@pytest.fixture
def tmp_db(tmp_path):
    """Temp path for a SQLite database (ConversationStore tests)."""
    return tmp_path / "test_conversations.db"
