"""Tests for src/bhai/proactive/scrubbers/ — the privacy scrub layer that
stands between the proactive agent and any external API call (step 3 of
the v2 build).
"""

from __future__ import annotations

from src.bhai.proactive.dossier_loader import UserDossier
from src.bhai.proactive.scrubbers import (
    ContentScrubResult,
    PiiScrubResult,
    ScrubResult,
    extract_name_terms,
    scrub_content,
    scrub_for_external_api,
    scrub_pii,
)


def _dossier_with_name(name: str = "Manimala") -> UserDossier:
    return UserDossier(
        phone="tg_test",
        phone_hash="abc123def456",
        summary="",
        core_facts=[f"Naam: {name}"],
    )


# ── extract_name_terms ────────────────────────────────────────────────


class TestExtractNameTerms:
    def test_naam_colon_extracts(self):
        d = UserDossier(
            phone="tg_x",
            phone_hash="x" * 12,
            summary="",
            core_facts=["Naam: Manimala"],
        )
        assert "Manimala" in extract_name_terms(d)

    def test_name_with_devanagari_label(self):
        d = UserDossier(
            phone="tg_x",
            phone_hash="x" * 12,
            summary="",
            core_facts=["नाम: Sonal"],
        )
        assert "Sonal" in extract_name_terms(d)

    def test_short_name_skipped(self):
        # Avoid over-blocking 1-2 char tokens that would catch every "of"
        # or "to" in a brief.
        d = UserDossier(
            phone="tg_x",
            phone_hash="x" * 12,
            summary="",
            core_facts=["Naam: A"],
        )
        assert extract_name_terms(d) == []

    def test_no_name_fact_returns_empty(self):
        d = UserDossier(
            phone="tg_x",
            phone_hash="x" * 12,
            summary="",
            core_facts=["BC office mein kaam karti hain"],
        )
        assert extract_name_terms(d) == []


# ── scrub_pii ────────────────────────────────────────────────────────


class TestScrubPii:
    def test_clean_brief_passes(self):
        result = scrub_pii(
            "Logo for a saree wholesaler selling via WhatsApp groups",
            _dossier_with_name("Manimala"),
        )
        assert result.ok is True
        assert result.rejected_terms == []

    def test_user_name_blocks(self):
        # Manimala's name in the brief is blocked because the dossier
        # extracts it from "Naam: Manimala".
        result = scrub_pii(
            "Logo for Manimala's saree business",
            _dossier_with_name("Manimala"),
        )
        assert result.ok is False
        assert any("Manimala" in t for t in result.rejected_terms)

    def test_phone_number_blocks(self):
        result = scrub_pii(
            "Contact 9876543210 for orders",
            _dossier_with_name(),
        )
        assert result.ok is False
        assert "phone_number" in result.rejected_terms

    def test_BC_office_blocks(self):
        result = scrub_pii(
            "Logo for a wholesaler at BC office",
            _dossier_with_name(),
        )
        assert result.ok is False
        assert any("location" in t for t in result.rejected_terms)

    def test_MIDC_blocks(self):
        result = scrub_pii(
            "Logo for MIDC side seamstress",
            _dossier_with_name(),
        )
        assert result.ok is False
        assert any("location" in t for t in result.rejected_terms)

    def test_aarey_community_blocks(self):
        result = scrub_pii(
            "Saree business in Aarey",
            _dossier_with_name(),
        )
        assert result.ok is False
        assert any("internal_name" in t for t in result.rejected_terms)

    def test_pardhi_community_blocks(self):
        result = scrub_pii(
            "Wholesaler for Pardhi families",
            _dossier_with_name(),
        )
        assert result.ok is False

    def test_tiny_miracles_name_blocks(self):
        result = scrub_pii(
            "Logo for a Tiny Miracles artisan",
            _dossier_with_name(),
        )
        assert result.ok is False
        assert any(
            "Tiny" in t.lower() or "tiny" in t.lower() for t in result.rejected_terms
        )

    def test_staff_name_priti_blocks(self):
        result = scrub_pii(
            "Recommended by Priti for the business",
            _dossier_with_name(),
        )
        assert result.ok is False
        assert any("Priti" in t for t in result.rejected_terms)

    def test_multiple_violations_listed(self):
        result = scrub_pii(
            "Manimala's logo for her BC office business, contact 9876543210",
            _dossier_with_name("Manimala"),
        )
        assert result.ok is False
        # All three should be flagged.
        assert any("Manimala" in t for t in result.rejected_terms)
        assert any("location" in t for t in result.rejected_terms)
        assert "phone_number" in result.rejected_terms


# ── scrub_content ────────────────────────────────────────────────────


class TestScrubContent:
    def test_clean_brief_passes(self):
        result = scrub_content(
            "Logo for a saree wholesaler, warm earthy palette, traditional motifs"
        )
        assert result.ok is True

    def test_religion_hindu_blocks(self):
        result = scrub_content("Hindu festival saree designs")
        assert result.ok is False
        assert "religion" in result.rejected_categories

    def test_religion_muslim_blocks(self):
        result = scrub_content("Designs for muslim weddings")
        assert result.ok is False
        assert "religion" in result.rejected_categories

    def test_religion_devanagari_blocks(self):
        result = scrub_content("व्यापार के लिए धर्म जरूरी है")
        assert result.ok is False
        assert "religion" in result.rejected_categories

    def test_caste_dalit_blocks(self):
        result = scrub_content("Targeting Dalit weavers in Mumbai")
        assert result.ok is False
        assert "caste" in result.rejected_categories

    def test_caste_OBC_blocks(self):
        result = scrub_content("OBC scheme eligibility for women weavers")
        assert result.ok is False
        assert "caste" in result.rejected_categories

    def test_disability_personal_blocks(self):
        result = scrub_content("crush injury rehab program for user")
        assert result.ok is False
        assert "disability_personal" in result.rejected_categories

    def test_disability_udid_blocks(self):
        # UDID is a disability cert ID — should never leave the system.
        result = scrub_content("Help applying for UDID")
        assert result.ok is False
        assert "disability_personal" in result.rejected_categories

    def test_loan_default_blocks(self):
        result = scrub_content("loan default history for credit score check")
        assert result.ok is False
        assert "loan_personal" in result.rejected_categories

    def test_medical_cancer_blocks(self):
        result = scrub_content("cancer treatment cost in Mumbai")
        assert result.ok is False
        assert "medical_personal" in result.rejected_categories

    def test_general_loan_topic_not_blocked(self):
        # Loan as a general topic is fine — only personal-disclosure shapes
        # ("loan default", "credit score", "defaulter") are blocked.
        result = scrub_content(
            "Saree business owner exploring MFI loan options for working capital"
        )
        # "loan" alone is not in the forbidden list — only "loan default" etc.
        assert result.ok is True

    def test_general_physiotherapy_not_blocked(self):
        # Topical mention of rehab/physiotherapy is fine.
        result = scrub_content(
            "Looking for physiotherapy clinics in Mumbai with foot rehab"
        )
        assert result.ok is True

    def test_multiple_categories_listed(self):
        result = scrub_content("Hindu Dalit weaver with diabetes")
        assert result.ok is False
        assert "religion" in result.rejected_categories
        assert "caste" in result.rejected_categories
        assert "medical_personal" in result.rejected_categories


# ── scrub_for_external_api (combined) ────────────────────────────────


class TestScrubForExternalApi:
    def test_clean_brief_passes_both_layers(self):
        d = _dossier_with_name("Manimala")
        r = scrub_for_external_api(
            "Logo for a saree wholesaler, mid-income customers, warm earthy palette",
            d,
        )
        assert r.ok is True
        assert r.reason() == "ok"

    def test_pii_only_failure(self):
        d = _dossier_with_name("Manimala")
        r = scrub_for_external_api(
            "Logo for Manimala's saree wholesale business",
            d,
        )
        assert r.ok is False
        assert any("Manimala" in t for t in r.pii_rejected)
        assert r.content_rejected_categories == []
        assert "pii:" in r.reason()

    def test_content_only_failure(self):
        d = _dossier_with_name("X-User")
        r = scrub_for_external_api(
            "Logo with Hindu festival motifs",
            d,
        )
        assert r.ok is False
        assert "religion" in r.content_rejected_categories
        assert r.pii_rejected == []
        assert "content[religion]" in r.reason()

    def test_both_layers_fail(self):
        d = _dossier_with_name("Manimala")
        r = scrub_for_external_api(
            "Logo for Manimala's Hindu wedding saree business in BC office",
            d,
        )
        assert r.ok is False
        assert len(r.pii_rejected) >= 2  # name + location
        assert "religion" in r.content_rejected_categories
        # reason() lists both layers.
        reason = r.reason()
        assert "pii:" in reason
        assert "content" in reason

    def test_manimala_saree_logo_canonical_passes(self):
        """The kickoff's canonical example: a brief Manimala's agent could
        send to nanobanana for a saree-business logo. This must pass."""
        d = _dossier_with_name("Manimala")
        canonical_brief = (
            "Logo for a saree wholesaler who sells via WhatsApp groups to "
            "~10-15 regular customers. Target audience: mid-income women "
            "aged 30-50 buying for festivals and weddings. Warm earthy "
            "palette, traditional motifs, minimalist. Square format."
        )
        r = scrub_for_external_api(canonical_brief, d)
        assert r.ok is True, f"Canonical brief should pass: {r.reason()}"

    def test_manimala_saree_logo_personalized_blocked(self):
        """The kickoff's anti-pattern: a personalized version of the same
        brief. This must block on user name + community/medical leak."""
        d = _dossier_with_name("Manimala")
        leaky_brief = (
            "Logo for Manimala's saree business in BC community Mumbai, "
            "she's recovering from her daughter's accident debt"
        )
        r = scrub_for_external_api(leaky_brief, d)
        assert r.ok is False
        assert any("Manimala" in t for t in r.pii_rejected)
