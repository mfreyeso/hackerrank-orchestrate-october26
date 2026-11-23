"""Comprehensive unit and regression tests for request_text intent classification."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

import pytest

from deletion_audit.config import AuditSettings
from deletion_audit.llm.client import FakeLLM, LLMGateway
from deletion_audit.llm.prompts import load_prompt
from deletion_audit.llm.usage import UsageTracker


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def llm_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LLMGateway]:
    isolated_cache = (tmp_path / "cache").resolve()
    monkeypatch.setenv("AUDIT_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AUDIT_CACHE_DIR", str(isolated_cache))
    settings = AuditSettings()
    tracker = UsageTracker(settings)
    gw = LLMGateway(settings, usage_tracker=tracker)
    yield gw
    gw.close()


class TestSampleDeletionRequests:
    """Verify that all 32 public sample requests authorize deletion."""

    def test_all_sample_requests_authorized(self, fake_llm: FakeLLM) -> None:
        sample_path = Path("dataset/sample_deletion_requests.csv")
        assert sample_path.exists(), "sample_deletion_requests.csv missing"
        with sample_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 32
        failures: list[tuple[str, str]] = []
        for row in rows:
            res = fake_llm.classify_intent(row["request_text"])
            if not res.authorizes_deletion:
                failures.append((row["case_id"], row["request_text"]))

        assert not failures, f"Sample requests failed classification: {failures}"


class TestEvaluationDatasetRequests:
    """Verify that all 518 evaluation requests in deletion_requests.csv are partitioned correctly."""

    def test_evaluation_dataset_partitioning(self, fake_llm: FakeLLM) -> None:
        eval_path = Path("dataset/deletion_requests.csv")
        assert eval_path.exists(), "deletion_requests.csv missing"
        with eval_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 518
        expected_non_deletion = {f"case_{i}" for i in range(533, 543)}

        actual_non_deletion: set[str] = set()
        for row in rows:
            res = fake_llm.classify_intent(row["request_text"])
            if not res.authorizes_deletion:
                actual_non_deletion.add(row["case_id"])

        assert actual_non_deletion == expected_non_deletion, (
            f"Non-deletion mismatch: extra={actual_non_deletion - expected_non_deletion}, "
            f"missing={expected_non_deletion - actual_non_deletion}"
        )


class TestIndirectDeletionExpressions:
    """Verify classification of indirect phrasings, audit requests, and tombstones."""

    @pytest.mark.parametrize(
        ("case_desc", "text"),
        [
            (
                "case_04_tombstone_analytics",
                "I\u2019m deleting my account. You can keep anonymous statistics, but nothing in analytics should still point back to me.",
            ),
            (
                "case_12_prior_email_change",
                "I changed the email on this account before deleting it. Please check that nothing tied to the old address was left behind.",
            ),
            (
                "case_15_integration_closure",
                "I disconnected my account last week, but one of the integrations still seems active. Close the account completely and make sure it can no longer send my data to other systems.",
            ),
            (
                "case_26_profile_gone_verification",
                "I found an old report saying my account still existed. Please check the latest state and confirm that the profile is gone and that remaining records cannot identify me.",
            ),
            (
                "case_27_audit_deletion",
                "Please audit the deletion as it stood when my request was reviewed. I want confirmation that the account was fully removed at that point.",
            ),
            (
                "case_28_verification_with_decoy_warning",
                "Can you verify that my account was deleted? A search result with a similar email belongs to someone else, so please do not treat that record as mine.",
            ),
            (
                "case_31_tombstone_reference",
                "I no longer need this account. Please remove my name and contact details, but keeping an internal deleted-account reference is fine if other required records still depend on it.",
            ),
            (
                "case_32_tombstone_cleanup",
                "The account itself is gone, but an internal deleted-account record still shows my personal details. Please keep only the reference needed for retained records and remove the rest.",
            ),
            (
                "case_19_support_cleanup",
                "Please remove my profile and clean my personal details out of earlier support conversations.",
            ),
        ],
    )
    def test_indirect_deletion_phrasings(
        self, fake_llm: FakeLLM, case_desc: str, text: str
    ) -> None:
        res = fake_llm.classify_intent(text)
        assert res.authorizes_deletion, f"Failed for {case_desc}: {res.rationale}"
        assert res.intent_category == "DELETION"
        assert res.confidence >= 0.95


class TestMultilingualDeletionExpressions:
    """Verify classification across diverse supported languages."""

    @pytest.mark.parametrize(
        ("lang", "text"),
        [
            (
                "French",
                "Je demande la suppression définitive du compte associé à cette adresse e-mail. Veuillez examiner les identifiants actuels et antérieurs.",
            ),
            (
                "Spanish",
                "Intenté eliminar mi cuenta ayer, pero la página terminó mostrando un error. ¿Pueden comprobar si todavía queda algún dato y completar la eliminación?",
            ),
            (
                "Spanish_formal",
                "Solicito la eliminación permanente de la cuenta asociada a este correo. Revisen los identificadores actuales y anteriores.",
            ),
            (
                "Portuguese",
                "Solicito a exclusão permanente da conta associada a este e-mail. Verifiquem os identificadores atuais e anteriores conforme o processo.",
            ),
            (
                "German",
                "Bitte löschen Sie mein Konto und alle damit verbundenen personenbezogenen Daten endgültig.",
            ),
            (
                "Japanese",
                "このメールアドレスに関連するアカウントの完全な削除を依頼します。 プライバシー手続きに従い、現在および過去の識別情報を確認してください。",
            ),
            (
                "Korean",
                "이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다. 개인정보 처리 절차에 따라 현재 및 이전 식별자를 검토해 주세요.",
            ),
        ],
    )
    def test_multilingual_deletion(
        self, fake_llm: FakeLLM, lang: str, text: str
    ) -> None:
        res = fake_llm.classify_intent(text)
        assert res.authorizes_deletion, f"Failed for language {lang}: {res.rationale}"
        assert res.intent_category == "DELETION"


class TestNonDeletionDecoys:
    """Verify non-deletion decoys (exports, opt-outs, profile updates, account recovery)."""

    @pytest.mark.parametrize(
        ("expected_cat", "text"),
        [
            (
                "KEEP_ACCOUNT_ACTIVE",
                "The mobile number on my profile is out of date. Please replace it with the new one and leave the account active.",
            ),
            (
                "NON_DELETION_EXPLICIT",
                "Please stop the promotional emails. I still need the account and my order history, so I am not asking for deletion.",
            ),
            (
                "KEEP_ACCOUNT_ACTIVE",
                "I'd like to download my account information in a portable format. Please keep the account as it is.",
            ),
            (
                "NON_DELETION_EXPLICIT",
                "I can't access my profile and need help resetting the login. Do not close the account.",
            ),
            (
                "NON_DELETION_EXPLICIT",
                "My surname is misspelled on the account. Can you correct it without removing any of my records?",
            ),
            (
                "MARKETING_OPT_OUT_ONLY",
                "Please remove me from marketing lists only. I still want receipts and service messages for this account.",
            ),
            (
                "NON_DELETION_EXPLICIT",
                "Can you tell me what personal information you hold about me? This is an information request, not a request to erase it.",
            ),
            (
                "DATA_EXPORT_ONLY",
                "I need a copy of last year's invoices for my records. Please leave my profile and purchase history in place.",
            ),
            (
                "KEEP_ACCOUNT_ACTIVE",
                "Please change the email address used for this account. I want to continue using the service.",
            ),
            (
                "NON_DELETION_EXPLICIT",
                "Could you send me a copy of the information held on my account? I still use it, so please don't delete or change anything.",
            ),
            (
                "MARKETING_OPT_OUT_ONLY",
                "Please unsubscribe me from marketing emails only.",
            ),
            (
                "MARKETING_OPT_OUT_ONLY",
                "I want to opt out of promotional emails only.",
            ),
            (
                "DATA_ACCESS_ONLY",
                "I am requesting access to my personal data only under GDPR.",
            ),
            (
                "NON_DELETION_OTHER",
                "Where can I track my latest shipment?",
            ),
        ],
    )
    def test_non_deletion_decoys(
        self, fake_llm: FakeLLM, expected_cat: str, text: str
    ) -> None:
        res = fake_llm.classify_intent(text)
        assert not res.authorizes_deletion, f"Should not authorize deletion: {text}"
        assert res.intent_category == expected_cat


class TestPromptAndGateway:
    """Verify prompt templating and LLMGateway integration with disk caching."""

    def test_prompt_template_renders_cleanly(self) -> None:
        prompt = load_prompt(Path("prompts"), "intent_classification_v1.md")
        rendered = prompt.render(request_text="Close my account please.")
        assert "Close my account please." in rendered
        assert "authorizes_deletion" in rendered

    def test_gateway_caching_and_usage(self, llm_gateway: LLMGateway) -> None:
        text = "Please delete my account and erase all my data."
        res1 = llm_gateway.classify_request_intent(text)
        assert res1.authorizes_deletion

        # Second call should hit disk cache
        res2 = llm_gateway.classify_request_intent(text)
        assert res2.authorizes_deletion
        assert res1 == res2

        records = llm_gateway.usage_tracker.records
        assert len(records) == 2
        assert records[0].cache_hit is False
        assert records[1].cache_hit is True
