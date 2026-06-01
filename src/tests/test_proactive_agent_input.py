"""Tests for src/bhai/proactive/agent_input.py — the AgentInput object that
combines a structured dossier with recent conversation for the proactive
thinking agent (step 2 of the v2 build).
"""

from __future__ import annotations

from src.bhai.memory.store import ConversationStore
from src.bhai.proactive.agent_input import AgentInput, build_agent_input
from src.bhai.proactive.dossier_loader import UserDossier


class TestAgentInputRendering:
    def test_system_prompt_context_includes_all_dossier_files(self):
        d = UserDossier(
            phone="tg_x",
            phone_hash="hash00000001",
            summary="Test summary line.",
            core_facts=["Naam: Tester"],
            family_facts=["beti exam de rahi hai"],
        )
        ai = AgentInput(dossier=d, recent_messages=[])
        rendered = ai.as_system_prompt_context()
        # All nine files appear as ### headers.
        for filename in [
            "core.md",
            "narrative.md",
            "family_context.md",
            "financial_threads.md",
            "grievance_log.md",
            "scheme_status.md",
            "outreach_history.md",
            "nudge_history.md",
            "open_threads.md",
        ]:
            assert f"### {filename}" in rendered
        # Populated content is present.
        assert "Naam: Tester" in rendered
        assert "Test summary line." in rendered
        assert "beti exam de rahi hai" in rendered
        # Empty placeholders are present for empty domains.
        assert "_no financial facts yet_" in rendered

    def test_system_prompt_files_in_stable_order(self):
        # Order matters for prompt caching — same input must produce the
        # same string every time, with core/narrative first and history at
        # the bottom.
        d = UserDossier(phone="tg_y", phone_hash="hash00000002", summary="x")
        rendered = AgentInput(dossier=d, recent_messages=[]).as_system_prompt_context()
        # core.md appears before family_context.md, which appears before
        # nudge_history.md (the documented order).
        assert rendered.index("### core.md") < rendered.index("### family_context.md")
        assert rendered.index("### family_context.md") < rendered.index(
            "### nudge_history.md"
        )

    def test_user_message_context_empty_when_no_recent(self):
        d = UserDossier(phone="tg_z", phone_hash="hash00000003", summary="")
        ai = AgentInput(dossier=d, recent_messages=[])
        assert "(no recent conversation)" in ai.as_user_message_context()

    def test_user_message_context_role_tagged(self):
        d = UserDossier(phone="tg_a", phone_hash="hash00000004", summary="")
        ai = AgentInput(
            dossier=d,
            recent_messages=[
                {"role": "user", "content": "kaise ho?", "timestamp": "2026-06-01"},
                {
                    "role": "assistant",
                    "content": "main theek hoon",
                    "timestamp": "2026-06-01",
                },
            ],
        )
        rendered = ai.as_user_message_context()
        assert "User" in rendered
        assert "bhAI" in rendered
        assert "kaise ho?" in rendered
        assert "main theek hoon" in rendered

    def test_phone_and_hash_passthrough(self):
        d = UserDossier(phone="tg_b", phone_hash="hash00000005", summary="")
        ai = AgentInput(dossier=d, recent_messages=[])
        assert ai.phone == "tg_b"
        assert ai.phone_hash == "hash00000005"


class TestBuildAgentInput:
    def test_build_for_user_with_full_history(self, tmp_db):
        store = ConversationStore(tmp_db)
        session_id, _ = store.get_or_create_session("tg_real_user")
        store.save_message("tg_real_user", "user", "kaise ho bhAI?", session_id)
        store.save_message("tg_real_user", "assistant", "main theek hoon", session_id)
        store.save_memory(
            phone="tg_real_user",
            summary="User asked how bhAI is doing.",
            facts=["Naam: TestUser", "beti exam de rahi hai"],
        )

        ai = build_agent_input(store, "tg_real_user", recent_turns=8)

        # Dossier populated.
        assert "TestUser" in " ".join(ai.dossier.core_facts)
        assert any("beti" in f for f in ai.dossier.family_facts)
        # Recent messages pulled.
        assert len(ai.recent_messages) == 2
        assert ai.recent_messages[0]["content"] == "kaise ho bhAI?"
        # System prompt context combines them.
        sys_ctx = ai.as_system_prompt_context()
        assert "TestUser" in sys_ctx
        assert "User asked how bhAI is doing." in sys_ctx
        # User message context has the conversation.
        user_ctx = ai.as_user_message_context()
        assert "kaise ho bhAI?" in user_ctx
        assert "main theek hoon" in user_ctx

        store.close()

    def test_build_for_new_user_returns_empty_but_well_formed(self, tmp_db):
        store = ConversationStore(tmp_db)
        ai = build_agent_input(store, "tg_brand_new")
        assert ai.dossier.summary == ""
        assert ai.recent_messages == []
        # System prompt still renders with placeholders.
        assert "_no core facts yet_" in ai.as_system_prompt_context()
        assert "(no recent conversation)" in ai.as_user_message_context()
        store.close()

    def test_recent_turns_limit_respected(self, tmp_db):
        store = ConversationStore(tmp_db)
        session_id, _ = store.get_or_create_session("tg_chatty")
        for i in range(30):
            store.save_message("tg_chatty", "user", f"msg {i}", session_id)
        ai = build_agent_input(store, "tg_chatty", recent_turns=5)
        assert len(ai.recent_messages) == 5
        store.close()
