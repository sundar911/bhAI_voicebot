"""
Tests for src/bhai/config.py — config loading from environment variables.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from bhai.config import Config, load_config


def test_defaults(monkeypatch):
    """With no relevant env vars set, config returns expected defaults."""
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("SARVAM_STT_MODEL", raising=False)
    monkeypatch.delenv("TTS_BACKEND", raising=False)
    monkeypatch.delenv("SARVAM_TTS_VOICE", raising=False)
    monkeypatch.delenv("SARVAM_TTS_MODEL", raising=False)

    # Pass a non-existent path so load_dotenv doesn't re-read the local .env
    cfg = load_config(env_path=Path("/nonexistent/.env"))

    assert cfg.llm_backend == "sarvam"
    assert cfg.openai_model == "gpt-4o-mini"
    assert cfg.sarvam_stt_model == "saaras:v3"
    assert cfg.tts_backend == "sarvam"
    assert cfg.sarvam_tts_voice == "suhani"
    assert cfg.sarvam_tts_model == "bulbul:v3"


def test_llm_backend_override(monkeypatch):
    """LLM_BACKEND env var is read correctly."""
    monkeypatch.setenv("LLM_BACKEND", "openai")
    cfg = load_config()
    assert cfg.llm_backend == "openai"


def test_int_coercion(monkeypatch):
    """Integer env vars are coerced to int."""
    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("QUEUE_MAX_ATTEMPTS", "10")
    cfg = load_config()
    assert cfg.retry_max_attempts == 5
    assert cfg.queue_max_attempts == 10


def test_float_coercion(monkeypatch):
    """Float env vars are coerced to float."""
    monkeypatch.setenv("FAQ_CACHE_THRESHOLD", "0.75")
    monkeypatch.setenv("ELEVENLABS_STABILITY", "0.8")
    cfg = load_config()
    assert cfg.faq_cache_threshold == 0.75
    assert cfg.elevenlabs_stability == 0.8


def test_bool_coercion_true(monkeypatch):
    """ACK_ENABLED=true → True."""
    monkeypatch.setenv("ACK_ENABLED", "true")
    cfg = load_config()
    assert cfg.ack_enabled is True


def test_bool_coercion_false(monkeypatch):
    """ACK_ENABLED=false → False."""
    monkeypatch.setenv("ACK_ENABLED", "false")
    cfg = load_config()
    assert cfg.ack_enabled is False


def test_optional_tts_sample_rate_none(monkeypatch):
    """SARVAM_TTS_SAMPLE_RATE unset → None."""
    monkeypatch.delenv("SARVAM_TTS_SAMPLE_RATE", raising=False)
    cfg = load_config()
    assert cfg.sarvam_tts_sample_rate is None


def test_optional_tts_sample_rate_set(monkeypatch):
    """SARVAM_TTS_SAMPLE_RATE set → int."""
    monkeypatch.setenv("SARVAM_TTS_SAMPLE_RATE", "22050")
    cfg = load_config()
    assert cfg.sarvam_tts_sample_rate == 22050
