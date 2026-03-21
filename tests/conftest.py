"""
Shared fixtures for bhAI test suite.

Sets up encryption keys, temp databases, and knowledge base fixtures
so tests can run without any external services.
"""

import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# Ensure project root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A single Fernet key used across the whole test session
_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.fixture(scope="session", autouse=True)
def set_test_encryption_key():
    """Inject a fresh Fernet key so crypto calls work in all tests."""
    os.environ["BHAI_ENCRYPTION_KEY"] = _TEST_ENCRYPTION_KEY
    yield


@pytest.fixture
def tmp_store(tmp_path):
    """Fresh ConversationStore backed by an isolated temp SQLite DB."""
    from src.bhai.memory.store import ConversationStore

    store = ConversationStore(tmp_path / "test_conversations.db")
    yield store
    store.close()


@pytest.fixture
def tmp_kb_dir(tmp_path):
    """Temp knowledge base directory with a few HR FAQ entries."""
    kb_dir = tmp_path / "knowledge_base"
    hr_dir = kb_dir / "hr_admin"
    hr_dir.mkdir(parents=True)

    faq_md = """# HR Admin Knowledge Base

## Common Questions

### "Salary kyun kata?"
→ Teen absence ki wajah se kata. HR se confirm karo ki kitni absence thi.

### "Leave kaise apply karte hain?"
→ Leave ke liye HR ko WhatsApp pe message karo ya directly HR office visit karo.

### "Overtime kab milega?"
→ Overtime ka paisa har mahine ke end mein milta hai regular salary ke saath.
"""
    (hr_dir / "faq.md").write_text(faq_md, encoding="utf-8")
    return kb_dir


@pytest.fixture
def fake_config():
    """Config with dummy API keys — no real external calls will be made."""
    from src.bhai.config import Config

    return Config(
        llm_backend="sarvam",
        sarvam_api_key="test_sarvam_key",
        twilio_account_sid="ACtest123456",
        twilio_auth_token="test_auth_token_32chars_long_pad",
        twilio_whatsapp_number="whatsapp:+14155238886",
        base_url="https://test.ngrok.app",
        ack_enabled=False,
        faq_cache_threshold=0.6,
    )
