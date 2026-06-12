"""Tests for src/bhai/proactive/tools/ — the tool wrappers the proactive
thinking agent uses (step 4a of the v2 build).

External-API wrappers (nanobanana) are tested with a mocked HTTP transport
so the suite never burns API quota or needs network. The wrapper structure
under test is: scrub → call → save → audit. Every code path writes one
audit row.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from src.bhai.proactive.dossier_loader import UserDossier
from src.bhai.proactive.tools import ToolAuditEntry, ToolResult, append_audit_entry
from src.bhai.proactive.tools.kb_read import read_kb_file
from src.bhai.proactive.tools.nanobanana import generate_image


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
    """Build a fake httpx.Response with the minimum interface our code uses."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.text = text
    return resp


# ── Audit log ─────────────────────────────────────────────────────────


class TestAuditLog:
    def test_append_creates_dir_and_file(self, tmp_path: Path):
        entry = ToolAuditEntry(
            phone_hash="hashtest0001",
            tool="nanobanana",
            brief="test brief",
            scrubbed_ok=True,
            api_status="ok",
        )
        log_path = append_audit_entry(tmp_path, entry)
        assert log_path == tmp_path / "hashtest0001" / "tool_audit.jsonl"
        assert log_path.exists()

    def test_append_writes_jsonl_line(self, tmp_path: Path):
        entry = ToolAuditEntry(
            phone_hash="hashtest0002",
            tool="nanobanana",
            brief="logo for saree wholesaler",
            scrubbed_ok=True,
            api_status="ok",
            artifact_path="/some/path.png",
        )
        log_path = append_audit_entry(tmp_path, entry)
        line = log_path.read_text().strip()
        parsed = json.loads(line)
        assert parsed["tool"] == "nanobanana"
        assert parsed["brief"] == "logo for saree wholesaler"
        assert parsed["artifact_path"] == "/some/path.png"
        assert parsed["api_status"] == "ok"
        # Timestamp auto-populated.
        assert parsed["timestamp"]

    def test_multiple_entries_append(self, tmp_path: Path):
        for i in range(3):
            append_audit_entry(
                tmp_path,
                ToolAuditEntry(
                    phone_hash="hashtest0003",
                    tool="kb_read",
                    brief=f"file_{i}",
                ),
            )
        log_path = tmp_path / "hashtest0003" / "tool_audit.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 3


# ── nanobanana ────────────────────────────────────────────────────────


class TestNanobananaScrub:
    def test_scrub_block_no_http_call_made(self, tmp_path: Path):
        """The leaky Manimala brief from the kickoff must be scrub-blocked
        without any HTTP call being attempted."""
        mock_post = MagicMock()
        result = generate_image(
            brief="Logo for Manimala's saree business in BC office",
            dossier=_dossier("Manimala"),
            api_key="fake_key",
            model="gemini-2.5-flash-image-preview",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        assert result.ok is False
        assert "scrub_blocked" in (result.error or "")
        mock_post.assert_not_called()  # critical: no network egress

    def test_scrub_block_writes_audit_row(self, tmp_path: Path):
        mock_post = MagicMock()
        generate_image(
            brief="Logo for Manimala's saree business",
            dossier=_dossier("Manimala"),
            api_key="fake_key",
            model="m",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        # Audit row exists with scrub block reason.
        log_path = tmp_path / "proactive" / "abc123def456" / "tool_audit.jsonl"
        line = log_path.read_text().strip()
        parsed = json.loads(line)
        assert parsed["scrubbed_ok"] is False
        assert parsed["api_status"] == "blocked"
        assert "Manimala" in parsed["scrub_reason"]


class TestNanobananaApiCall:
    def _build_inline_image_response(self) -> Dict[str, Any]:
        # 1x1 transparent PNG as base64 — enough to verify byte handling.
        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"inline_data": {"mime_type": "image/png", "data": png_b64}}
                        ]
                    }
                }
            ]
        }

    def test_happy_path_saves_image_and_returns_path(self, tmp_path: Path):
        mock_post = MagicMock(
            return_value=_mock_response(body=self._build_inline_image_response())
        )
        result = generate_image(
            brief="Logo for a saree wholesaler, warm earthy palette",
            dossier=_dossier("Manimala"),
            api_key="fake_key",
            model="gemini-2.5-flash-image-preview",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        assert result.ok is True
        assert result.artifact_path is not None
        assert result.artifact_path.exists()
        # Saved bytes are decodable as PNG (the magic bytes).
        assert result.artifact_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        # HTTP call shape: api_key in URL.
        call_args = mock_post.call_args
        assert "fake_key" in call_args[0][0]
        assert "gemini-2.5-flash-image-preview" in call_args[0][0]

    def test_happy_path_writes_audit_row_with_artifact_path(self, tmp_path: Path):
        mock_post = MagicMock(
            return_value=_mock_response(body=self._build_inline_image_response())
        )
        result = generate_image(
            brief="Logo for a saree wholesaler",
            dossier=_dossier("Manimala"),
            api_key="fake_key",
            model="m",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        log_path = tmp_path / "proactive" / "abc123def456" / "tool_audit.jsonl"
        parsed = json.loads(log_path.read_text().strip())
        assert parsed["api_status"] == "ok"
        assert parsed["scrubbed_ok"] is True
        assert parsed["artifact_path"] == str(result.artifact_path)

    def test_alternate_inlineData_camelCase_also_handled(self, tmp_path: Path):
        """Some Gemini API responses use camelCase 'inlineData' instead of
        'inline_data' — both must parse."""
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"inlineData": {"mimeType": "image/png", "data": png_b64}}
                        ]
                    }
                }
            ]
        }
        mock_post = MagicMock(return_value=_mock_response(body=body))
        result = generate_image(
            brief="Logo brief",
            dossier=_dossier("X"),
            api_key="fake_key",
            model="m",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        assert result.ok is True

    def test_missing_api_key_is_explicit_error(self, tmp_path: Path):
        mock_post = MagicMock()
        result = generate_image(
            brief="Logo brief",
            dossier=_dossier("X"),
            api_key="",  # missing
            model="m",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        assert result.ok is False
        assert "api_key_missing" in (result.error or "")
        mock_post.assert_not_called()

    def test_http_error_status_handled(self, tmp_path: Path):
        mock_post = MagicMock(
            return_value=_mock_response(status_code=429, text="quota exceeded")
        )
        result = generate_image(
            brief="Logo brief",
            dossier=_dossier("X"),
            api_key="fake_key",
            model="m",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        assert result.ok is False
        assert "429" in (result.error or "")
        # Audit row records the error.
        log_path = (
            tmp_path / "proactive" / _dossier("X").phone_hash / "tool_audit.jsonl"
        )
        parsed = json.loads(log_path.read_text().strip())
        assert "http_429" in parsed["api_status"]

    def test_network_exception_handled(self, tmp_path: Path):
        mock_post = MagicMock(side_effect=ConnectionError("DNS failure"))
        result = generate_image(
            brief="Logo brief",
            dossier=_dossier("X"),
            api_key="fake_key",
            model="m",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        assert result.ok is False
        assert "http_error" in (result.error or "")

    def test_malformed_response_handled(self, tmp_path: Path):
        # 200 OK but no inline_data in the parts.
        body = {"candidates": [{"content": {"parts": [{"text": "no image here"}]}}]}
        mock_post = MagicMock(return_value=_mock_response(body=body))
        result = generate_image(
            brief="Logo brief",
            dossier=_dossier("X"),
            api_key="fake_key",
            model="m",
            endpoint="https://example.com/v1",
            artifacts_dir=tmp_path / "artifacts",
            audit_base_dir=tmp_path / "proactive",
            http_post=mock_post,
        )
        assert result.ok is False
        assert "response_parse_error" in (result.error or "")


# ── kb_read ───────────────────────────────────────────────────────────


class TestKbRead:
    def test_reads_helpdesk_file(self, tmp_path: Path):
        kb = tmp_path / "knowledge_base"
        (kb / "helpdesk").mkdir(parents=True)
        (kb / "helpdesk" / "aadhaar.md").write_text(
            "# Aadhaar\n\nApply at the nearest Seva Kendra.\n"
        )
        result = read_kb_file(
            "aadhaar",
            _dossier(),
            kb_dir=kb,
            audit_base_dir=tmp_path / "proactive",
        )
        assert result.ok is True
        assert "Apply at the nearest Seva Kendra" in result.payload

    def test_reads_shared_file_fallback(self, tmp_path: Path):
        kb = tmp_path / "knowledge_base"
        (kb / "shared").mkdir(parents=True)
        (kb / "shared" / "company.md").write_text("Tiny Miracles is a nonprofit.")
        result = read_kb_file(
            "company",
            _dossier(),
            kb_dir=kb,
            audit_base_dir=tmp_path / "proactive",
        )
        assert result.ok is True
        assert "nonprofit" in result.payload

    def test_not_found_returns_error(self, tmp_path: Path):
        kb = tmp_path / "knowledge_base"
        (kb / "helpdesk").mkdir(parents=True)
        result = read_kb_file(
            "nonexistent",
            _dossier(),
            kb_dir=kb,
            audit_base_dir=tmp_path / "proactive",
        )
        assert result.ok is False
        assert "kb_file_not_found" in (result.error or "")

    @pytest.mark.parametrize(
        "bad_slug",
        ["../etc/passwd", "../../secrets", "subdir/file", "/abs/path"],
    )
    def test_path_traversal_rejected(self, tmp_path: Path, bad_slug: str):
        result = read_kb_file(
            bad_slug,
            _dossier(),
            kb_dir=tmp_path / "knowledge_base",
            audit_base_dir=tmp_path / "proactive",
        )
        assert result.ok is False
        assert "invalid_slug" in (result.error or "")

    def test_writes_audit_row(self, tmp_path: Path):
        kb = tmp_path / "knowledge_base"
        (kb / "helpdesk").mkdir(parents=True)
        (kb / "helpdesk" / "test.md").write_text("hello")
        d = _dossier()
        read_kb_file("test", d, kb_dir=kb, audit_base_dir=tmp_path / "proactive")
        log_path = tmp_path / "proactive" / d.phone_hash / "tool_audit.jsonl"
        parsed = json.loads(log_path.read_text().strip())
        assert parsed["tool"] == "kb_read"
        assert parsed["brief"] == "test"
        assert parsed["api_status"] == "ok"
