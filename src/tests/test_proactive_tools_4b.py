"""Tests for the second batch of proactive tool wrappers — web_search and
tts_draft (step 4b of the v2 build).

External-API wrappers (web_search) use a mocked httpx transport. The TTS
wrapper takes a duck-typed TTS instance so tests inject a fake without
touching the Sarvam client at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

from src.bhai.proactive.dossier_loader import UserDossier
from src.bhai.proactive.tools.tts_draft import synthesize
from src.bhai.proactive.tools.web_search import search


def _dossier(name: str = "Manimala", phone_hash: str = "abc123def456") -> UserDossier:
    return UserDossier(
        phone=f"tg_{name.lower()}",
        phone_hash=phone_hash,
        summary="",
        core_facts=[f"Naam: {name}"],
    )


def _mock_response(
    *,
    status_code: int = 200,
    body: Optional[Dict[str, Any]] = None,
    text: str = "",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.text = text
    return resp


def _items_body(n: int = 3) -> Dict[str, Any]:
    return {
        "items": [
            {
                "title": f"Result {i}",
                "link": f"https://example.com/{i}",
                "snippet": f"Snippet for result {i}",
                "displayLink": "example.com",
            }
            for i in range(n)
        ]
    }


# ── web_search ────────────────────────────────────────────────────────


class TestWebSearchScrub:
    def test_scrub_block_no_http_call(self, tmp_path: Path):
        mock_get = MagicMock()
        result = search(
            "physiotherapy near BC office for Manimala",  # PII + location
            _dossier("Manimala"),
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        assert result.ok is False
        assert "scrub_blocked" in (result.error or "")
        mock_get.assert_not_called()

    def test_scrub_block_writes_audit_with_reason(self, tmp_path: Path):
        mock_get = MagicMock()
        search(
            "rehab for Manimala's daughter foot crush injury",
            _dossier("Manimala"),
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        log = (tmp_path / "proactive" / "abc123def456" / "tool_audit.jsonl").read_text()
        parsed = json.loads(log.strip())
        assert parsed["scrubbed_ok"] is False
        assert parsed["api_status"] == "blocked"
        # Reason mentions both the PII name and the content category.
        assert "Manimala" in parsed["scrub_reason"]


class TestWebSearchConfig:
    def test_missing_api_key_explicit_error(self, tmp_path: Path):
        mock_get = MagicMock()
        result = search(
            "saree wholesale market trends Mumbai",
            _dossier(),
            api_key="",
            cse_id="cse_id",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        assert result.ok is False
        assert "api_key_missing" in (result.error or "")
        mock_get.assert_not_called()

    def test_missing_cse_id_explicit_error(self, tmp_path: Path):
        mock_get = MagicMock()
        result = search(
            "saree wholesale market trends Mumbai",
            _dossier(),
            api_key="fake_key",
            cse_id="",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        assert result.ok is False
        assert "cse_id_missing" in (result.error or "")
        mock_get.assert_not_called()


class TestWebSearchHappyPath:
    def test_returns_list_of_results(self, tmp_path: Path):
        mock_get = MagicMock(return_value=_mock_response(body=_items_body(3)))
        result = search(
            "saree wholesale market trends Mumbai",
            _dossier(),
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        assert result.ok is True
        assert isinstance(result.payload, list)
        assert len(result.payload) == 3
        assert result.payload[0]["title"] == "Result 0"
        assert result.payload[0]["link"] == "https://example.com/0"
        assert result.payload[0]["snippet"] == "Snippet for result 0"

    def test_request_params_shape(self, tmp_path: Path):
        mock_get = MagicMock(return_value=_mock_response(body=_items_body(1)))
        search(
            "physiotherapy clinics Mumbai foot rehab",
            _dossier(),
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        call = mock_get.call_args
        params = call.kwargs.get("params", {})
        assert params["key"] == "fake_key"
        assert params["cx"] == "fake_cse"
        assert params["q"] == "physiotherapy clinics Mumbai foot rehab"
        # num is clamped to [1, 10].
        assert 1 <= params["num"] <= 10

    def test_max_results_clamped(self, tmp_path: Path):
        # Google caps at 10 — we should clamp at the wrapper layer too so a
        # buggy agent prompt that asks for 50 doesn't blow up downstream.
        # Use a scrub-safe query so we actually reach the HTTP call layer.
        mock_get = MagicMock(return_value=_mock_response(body=_items_body(10)))
        search(
            "Mumbai physiotherapy clinics affordable",
            _dossier(),
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            max_results=50,
            http_get=mock_get,
        )
        params = mock_get.call_args.kwargs["params"]
        assert params["num"] == 10

    def test_audit_row_records_result_count(self, tmp_path: Path):
        mock_get = MagicMock(return_value=_mock_response(body=_items_body(5)))
        d = _dossier()
        search(
            "test query",
            d,
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        log = (tmp_path / "proactive" / d.phone_hash / "tool_audit.jsonl").read_text()
        parsed = json.loads(log.strip())
        assert parsed["api_status"] == "ok"
        assert parsed["extra"]["result_count"] == 5

    def test_empty_results_still_ok(self, tmp_path: Path):
        # No `items` key in response = zero results, still a successful call.
        mock_get = MagicMock(return_value=_mock_response(body={}))
        result = search(
            "obscure query with no matches",
            _dossier(),
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        assert result.ok is True
        assert result.payload == []


class TestWebSearchErrors:
    def test_http_429_handled(self, tmp_path: Path):
        mock_get = MagicMock(
            return_value=_mock_response(status_code=429, text="quota exceeded")
        )
        result = search(
            "test",
            _dossier(),
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        assert result.ok is False
        assert "429" in (result.error or "")

    def test_network_exception_handled(self, tmp_path: Path):
        mock_get = MagicMock(side_effect=ConnectionError("DNS failure"))
        result = search(
            "test",
            _dossier(),
            api_key="fake_key",
            cse_id="fake_cse",
            audit_base_dir=tmp_path / "proactive",
            http_get=mock_get,
        )
        assert result.ok is False
        assert "http_error" in (result.error or "")


# ── tts_draft ─────────────────────────────────────────────────────────


class FakeTTS:
    """Minimal duck-typed TTS for tests. Writes a stub byte sequence so the
    output file actually exists (the wrapper checks for it)."""

    def __init__(
        self, *, raise_exc: Optional[Exception] = None, write_file: bool = True
    ):
        self.calls = []
        self.raise_exc = raise_exc
        self.write_file = write_file

    def synthesize(self, text: str, output_path: Path) -> Dict[str, Any]:
        self.calls.append((text, output_path))
        if self.raise_exc:
            raise self.raise_exc
        if self.write_file:
            output_path.write_bytes(b"FAKE_AUDIO_BYTES")
        return {"audio_path": str(output_path)}


class TestTtsDraftHappyPath:
    def test_synthesizes_and_returns_path(self, tmp_path: Path):
        tts = FakeTTS()
        result = synthesize(
            "Namaste Manimala, kaise ho aaj?",
            _dossier(),
            tts=tts,
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
        )
        assert result.ok is True
        assert result.artifact_path is not None
        assert result.artifact_path.exists()
        assert result.artifact_path.read_bytes() == b"FAKE_AUDIO_BYTES"
        # The TTS instance got the text.
        assert tts.calls[0][0] == "Namaste Manimala, kaise ho aaj?"

    def test_audit_row_includes_text_length(self, tmp_path: Path):
        d = _dossier()
        text = "अरे मणीमाला, कैसी हो आज? आज loom कैसा चला?"
        synthesize(
            text,
            d,
            tts=FakeTTS(),
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
        )
        log = (tmp_path / "proactive" / d.phone_hash / "tool_audit.jsonl").read_text()
        parsed = json.loads(log.strip())
        assert parsed["api_status"] == "ok"
        assert parsed["extra"]["text_len_chars"] == len(text)
        # Brief in audit log truncated for long texts.
        assert parsed["brief"].startswith("अरे मणीमाला")

    def test_long_text_brief_truncated(self, tmp_path: Path):
        long_text = "क " * 200  # 400+ chars
        synthesize(
            long_text,
            _dossier(),
            tts=FakeTTS(),
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
        )
        log_path = tmp_path / "proactive" / _dossier().phone_hash / "tool_audit.jsonl"
        parsed = json.loads(log_path.read_text().strip())
        # Brief ends with ellipsis indicating truncation.
        assert parsed["brief"].endswith("…")


class TestTtsDraftErrors:
    def test_tts_exception_handled(self, tmp_path: Path):
        tts = FakeTTS(raise_exc=RuntimeError("Sarvam 500"))
        result = synthesize(
            "test text",
            _dossier(),
            tts=tts,
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
        )
        assert result.ok is False
        assert "tts_error" in (result.error or "")
        assert "Sarvam 500" in (result.error or "")

    def test_no_output_file_treated_as_failure(self, tmp_path: Path):
        # TTS returned without raising but didn't actually write a file.
        tts = FakeTTS(write_file=False)
        result = synthesize(
            "test text",
            _dossier(),
            tts=tts,
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
        )
        assert result.ok is False
        assert "tts_no_output_file" in (result.error or "")

    def test_error_writes_audit_row(self, tmp_path: Path):
        tts = FakeTTS(raise_exc=ValueError("bad text"))
        d = _dossier()
        synthesize(
            "x",
            d,
            tts=tts,
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
        )
        log = (tmp_path / "proactive" / d.phone_hash / "tool_audit.jsonl").read_text()
        parsed = json.loads(log.strip())
        assert "ValueError" in parsed["api_status"]
        assert "bad text" in parsed["api_status"]
