"""Tests for src/bhai/proactive/dossier_loader.py — the SQLite-to-structured
dossier loader (step 1 of the v2 proactive build, see tmp/v2_proactive_design.md).
"""

from __future__ import annotations

import pytest

from src.bhai.memory.store import ConversationStore
from src.bhai.proactive.dossier_loader import (
    UserDossier,
    classify_fact,
    load_user_dossier,
)

# ── classify_fact: bucketing heuristic ────────────────────────────────


class TestClassifyFact:
    """Multi-label bucketing — a fact can land in 0+ domain buckets, plus
    optionally 'core' if identity-pattern matched, and falls through to
    'core' if no bucket matched.
    """

    def test_family_hindi_daughter(self):
        assert "family_context" in classify_fact(
            "बेटी का September 2024 में accident हुआ था"
        )

    def test_family_hindi_son_marathi_word(self):
        # Mixed script — "beta" colloquially used too, but the test fact uses
        # Devanagari which should hit the बेट[ाीे] pattern.
        assert "family_context" in classify_fact("बेटा सबसे शैतान है")

    def test_family_english_husband(self):
        assert "family_context" in classify_fact("Husband works at MIDC")

    def test_family_master_degree(self):
        assert "family_context" in classify_fact(
            "बेटी master's कर रही है, काम नहीं कर सकती"
        )

    def test_family_hospital(self):
        assert "family_context" in classify_fact("33 din hospital mein bhi rahna pada")

    def test_financial_loan_emi(self):
        b = classify_fact("नया loan 1 lakh का सोच रही हैं, EMI 8,000")
        assert "financial_threads" in b

    def test_financial_saree_business(self):
        assert "financial_threads" in classify_fact("saree business चला रही हैं")

    def test_financial_salary(self):
        assert "financial_threads" in classify_fact(
            "salary कितना jama hua hai is mahine"
        )

    def test_financial_rupee_symbol(self):
        assert "financial_threads" in classify_fact("EMI ₹5000 per month")

    def test_grievance_supervisor(self):
        assert "grievance_log" in classify_fact("supervisor irritate कर रही है हर रोज़")

    def test_grievance_piece_rate(self):
        assert "grievance_log" in classify_fact(
            "piece-rate की बात उठाई तब से tension बढ़ गया"
        )

    def test_grievance_folding_work(self):
        assert "grievance_log" in classify_fact(
            "Tiny Miracles mein folding ka kaam ek saal se"
        )

    def test_scheme_aadhaar(self):
        assert "scheme_status" in classify_fact("दोनों बच्चों का आधार बनवाना है")

    def test_scheme_ladki_bahin(self):
        assert "scheme_status" in classify_fact("लाड़की भाई बंद हो गया")

    def test_scheme_udid(self):
        assert "scheme_status" in classify_fact("UDID disability certificate चाहिए")

    def test_scheme_priti_mention(self):
        # Named impact-team contacts are scheme-adjacent (they handle docs).
        assert "scheme_status" in classify_fact("Priti दीदी मदद करती है documents में")

    def test_identity_naam_in_core(self):
        # "Naam: Sonal" should land in core (identity).
        buckets = classify_fact("Naam: Sonal")
        assert "core" in buckets

    def test_identity_work_location_in_core(self):
        buckets = classify_fact("BC office में accounts से बात की")
        assert "core" in buckets

    def test_catchall_to_core(self):
        # A fact matching no domain bucket falls through to core.
        buckets = classify_fact("User aksar 'koi hai kya' poochh kar shuru karta hai")
        assert "core" in buckets

    def test_multi_label_daughter_accident_debt(self):
        # Manimala's load-bearing fact — daughter + hospital + financial debt.
        # Should fan out to family_context AND financial_threads.
        buckets = classify_fact("बेटी के accident का कर्जा अभी भी बाकी है")
        assert "family_context" in buckets
        assert "financial_threads" in buckets

    def test_multi_label_loan_for_business(self):
        # Loan + business → financial only (no family, no grievance).
        buckets = classify_fact("saree business के लिए 1 lakh का loan")
        assert "financial_threads" in buckets
        # Should NOT bucket into family/grievance/scheme.
        assert "family_context" not in buckets
        assert "grievance_log" not in buckets
        assert "scheme_status" not in buckets

    def test_no_bucket_means_core(self):
        # If a fact hits no domain or identity pattern, it still ends up
        # somewhere — core, so the agent always sees it.
        buckets = classify_fact("मौसम बहुत अच्छा है आज")
        assert buckets == {"core"}

    # Romanized-Hindi family facts — regression for the gap surfaced on
    # web_test_user (Sonal) during step-1 sanity check. Her facts use Roman
    # script ("beta", "beti", "bachche", "pati") not Devanagari.
    def test_family_romanized_beta(self):
        assert "family_context" in classify_fact(
            "ek beta (sabse shaitan), ek beti (badi aur achi)"
        )

    def test_family_romanized_bachche(self):
        assert "family_context" in classify_fact("2 bachche hain ghar mein")

    def test_family_romanized_pati(self):
        assert "family_context" in classify_fact(
            "Pati bhi ghar mein teesre bachche ki tarah hain"
        )

    def test_bot_name_bhai_not_misread_as_family(self):
        # "bhAI" is the bot's own name (Roman script, homophone for "भाई").
        # We must NOT match it as the family word "brother", because that
        # would falsely tag every meta-fact about the bot ("BhAI ka naam …")
        # as family content.
        buckets = classify_fact("BhAI Tiny Miracles ki AI assistant hai")
        assert "family_context" not in buckets


# ── UserDossier markdown rendering ─────────────────────────────────────


class TestUserDossierMarkdown:
    def test_empty_dossier_renders_all_files_with_placeholders(self):
        d = UserDossier(phone="tg_123", phone_hash="abc123def456", summary="")
        files = d.markdown_map()
        # The full file set is always returned, even when empty.
        expected = {
            "core.md",
            "narrative.md",
            "family_context.md",
            "financial_threads.md",
            "grievance_log.md",
            "scheme_status.md",
            "outreach_history.md",
            "nudge_history.md",
            "open_threads.md",
        }
        assert set(files.keys()) == expected
        # Empty-state placeholders are present, not silent empties.
        assert "_no core facts yet_" in files["core.md"]
        assert "_no narrative yet_" in files["narrative.md"]
        assert "_no family facts yet_" in files["family_context.md"]

    def test_populated_dossier_renders_bullets(self):
        d = UserDossier(
            phone="tg_456",
            phone_hash="abc123def456",
            summary="Manimala saree business chala rahi hain.",
            family_facts=["बेटी master's कर रही है"],
            financial_facts=["EMI 5000 per month"],
        )
        files = d.markdown_map()
        assert "- बेटी master's कर रही है" in files["family_context.md"]
        assert "- EMI 5000 per month" in files["financial_threads.md"]
        assert "Manimala saree business chala rahi hain." in files["narrative.md"]
        # Domain not populated still gets a placeholder.
        assert "_no grievance facts yet_" in files["grievance_log.md"]

    def test_phone_hash_in_headers(self):
        d = UserDossier(phone="tg_789", phone_hash="hash12345678", summary="")
        files = d.markdown_map()
        for content in files.values():
            assert "hash12345678" in content

    def test_write_to_disk_creates_files(self, tmp_path):
        d = UserDossier(
            phone="tg_999",
            phone_hash="diskhash0001",
            summary="test summary",
            core_facts=["Naam: TestUser"],
        )
        out = d.write_to_disk(tmp_path)
        assert out == tmp_path / "diskhash0001"
        assert (out / "core.md").exists()
        assert "Naam: TestUser" in (out / "core.md").read_text(encoding="utf-8")
        assert "test summary" in (out / "narrative.md").read_text(encoding="utf-8")


# ── load_user_dossier: end-to-end against ConversationStore ───────────


class TestLoadUserDossier:
    def test_load_for_user_with_no_memory(self, tmp_db):
        store = ConversationStore(tmp_db)
        d = load_user_dossier(store, "tg_new_user")
        assert d.phone == "tg_new_user"
        # Hash is 12 hex chars.
        assert len(d.phone_hash) == 12
        assert d.summary == ""
        assert d.core_facts == []
        assert d.family_facts == []
        # markdown_map still works — placeholders.
        files = d.markdown_map()
        assert "_no narrative yet_" in files["narrative.md"]
        store.close()

    def test_load_buckets_facts_correctly(self, tmp_db):
        store = ConversationStore(tmp_db)
        store.save_memory(
            phone="tg_manimala",
            summary="Manimala saree business chala rahi hain. Beti ki tabiyat thik nahi.",
            facts=[
                "saree business चला रही हैं",
                "बेटी का September 2024 में accident हुआ था, 33 दिन hospital",
                "बेटी master's कर रही है, काम नहीं कर सकती",
                "नया loan 1 lakh का सोच रही हैं, EMI 8,000",
                "बेटी के accident का कर्जा अभी भी बाकी है",
                "Naam: Manimala",
                "Priti दीदी मदद करती है documents में",
            ],
        )
        d = load_user_dossier(store, "tg_manimala")

        # Financial: saree business, loan/EMI, daughter's accident debt.
        assert any("saree business" in f for f in d.financial_facts)
        assert any("loan" in f.lower() for f in d.financial_facts)
        assert any("accident का कर्जा" in f for f in d.financial_facts)

        # Family: accident, master's, daughter's debt (multi-labeled to family too).
        assert any("accident" in f for f in d.family_facts)
        assert any("master's" in f for f in d.family_facts)

        # Scheme: Priti mention.
        assert any("Priti" in f for f in d.scheme_facts)

        # Core: name.
        assert any("Manimala" in f for f in d.core_facts)

        # Summary lands in narrative.
        files = d.markdown_map()
        assert "Manimala saree business chala rahi hain" in files["narrative.md"]

        store.close()

    def test_load_handles_facts_that_only_match_identity(self, tmp_db):
        store = ConversationStore(tmp_db)
        store.save_memory(
            phone="tg_sonal",
            summary="",
            facts=["Naam: Sonal", "Kaam: Tiny Miracles mein folding ka kaam"],
        )
        d = load_user_dossier(store, "tg_sonal")
        # "Naam: Sonal" → core only.
        assert any("Sonal" in f for f in d.core_facts)
        # "Kaam: folding" → core (identity word "Kaam") AND grievance (folding work).
        assert any("folding" in f for f in d.core_facts)
        assert any("folding" in f for f in d.grievance_facts)
        store.close()

    def test_phone_hash_is_stable(self, tmp_db):
        store = ConversationStore(tmp_db)
        d1 = load_user_dossier(store, "tg_xyz")
        d2 = load_user_dossier(store, "tg_xyz")
        assert d1.phone_hash == d2.phone_hash
        # Different phone → different hash.
        d3 = load_user_dossier(store, "tg_abc")
        assert d3.phone_hash != d1.phone_hash
        store.close()
