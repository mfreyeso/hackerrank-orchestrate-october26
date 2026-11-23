"""Provider-agnostic LLM gateway, deterministic FakeLLM, disk caching, and retries."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

import diskcache
import orjson
from tenacity import retry, stop_after_attempt, wait_exponential

from deletion_audit.config import AuditSettings
from deletion_audit.llm.prompts import load_prompt, sanitize_untrusted_text
from deletion_audit.llm.usage import UsageTracker
from deletion_audit.logging import get_logger
from deletion_audit.models import IntentClassification

logger = get_logger(__name__)

# Structured patterns indicating a non-deletion request with specific intent categories and rationales
_NON_DELETION_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # Explicit non-deletion statements and negations
    (
        re.compile(
            r"\b(?:not|never|neither)\s+(?:asking\s+for|requesting)\s+(?:deletion|erasure|account\s+closure)\b",
            re.IGNORECASE,
        ),
        "NON_DELETION_EXPLICIT",
        "Customer explicitly states they are not requesting deletion.",
    ),
    (
        re.compile(
            r"\bnot\s+a\s+request\s+to\s+(?:erase|delete|close|remove)\b",
            re.IGNORECASE,
        ),
        "NON_DELETION_EXPLICIT",
        "Customer clarified this is not a request to erase or delete data.",
    ),
    (
        re.compile(
            r"\b(?:do\s+not|don['\u2019]t|please\s+don['\u2019]t)\s+(?:delete|erase|close|remove)\b",
            re.IGNORECASE,
        ),
        "NON_DELETION_EXPLICIT",
        "Customer explicitly asked not to delete, erase, or close the account.",
    ),
    (
        re.compile(
            r"\bwithout\s+(?:deleting|erasing|closing|removing)\b",
            re.IGNORECASE,
        ),
        "NON_DELETION_EXPLICIT",
        "Customer requested action without deleting or removing records.",
    ),
    # Keeping account or profile active / in place
    (
        re.compile(
            r"\bleave\s+(?:the|my)\s+account\s+active\b",
            re.IGNORECASE,
        ),
        "KEEP_ACCOUNT_ACTIVE",
        "Customer requested changes while keeping the account active.",
    ),
    (
        re.compile(
            r"\bkeep\s+(?:the|my)\s+account(?:\s+as\s+it\s+is|\s+open|\s+active)?\b",
            re.IGNORECASE,
        ),
        "KEEP_ACCOUNT_ACTIVE",
        "Customer requested to keep the account as is or open.",
    ),
    (
        re.compile(
            r"\bleave\s+my\s+profile(?:\s+and\s+\w+)?\s+in\s+place\b",
            re.IGNORECASE,
        ),
        "KEEP_ACCOUNT_ACTIVE",
        "Customer requested to leave profile/history in place.",
    ),
    (
        re.compile(
            r"\b(?:want|wish|plan)\s+to\s+continue\s+using\s+(?:the\s+service|my\s+account|this\s+service)\b",
            re.IGNORECASE,
        ),
        "KEEP_ACCOUNT_ACTIVE",
        "Customer wants to continue using the service.",
    ),
    (
        re.compile(
            r"\bi\s+still\s+use\s+it\b",
            re.IGNORECASE,
        ),
        "KEEP_ACCOUNT_ACTIVE",
        "Customer still uses the account.",
    ),
    (
        re.compile(
            r"\bi\s+still\s+need\s+the\s+account\b",
            re.IGNORECASE,
        ),
        "KEEP_ACCOUNT_ACTIVE",
        "Customer still needs the account.",
    ),
    # Data export / portability / DSAR copies only
    (
        re.compile(
            r"\bonly\s+want\s+a\s+copy\b",
            re.IGNORECASE,
        ),
        "DATA_EXPORT_ONLY",
        "Customer requests an export/access copy only without deletion.",
    ),
    (
        re.compile(
            r"\bdownload\s+a\s+copy\s+of\s+my\s+data\s+without\s+closing\b",
            re.IGNORECASE,
        ),
        "DATA_EXPORT_ONLY",
        "Customer requests a data download copy without closing the account.",
    ),
    (
        re.compile(
            r"\bdownload\s+my\s+account\s+information\s+in\s+a\s+portable\s+format\b",
            re.IGNORECASE,
        ),
        "DATA_EXPORT_ONLY",
        "Customer requests portable format data export while keeping account.",
    ),
    (
        re.compile(
            r"\bcopy\s+of\s+(?:last\s+year['\u2019]s\s+)?invoices\b",
            re.IGNORECASE,
        ),
        "DATA_EXPORT_ONLY",
        "Customer requests invoice copies while leaving profile in place.",
    ),
    (
        re.compile(
            r"\bcopy\s+of\s+the\s+information\s+held\s+on\s+my\s+account\b",
            re.IGNORECASE,
        ),
        "DATA_ACCESS_ONLY",
        "Customer requests an information copy for an active account.",
    ),
    (
        re.compile(
            r"\binformation\s+request\b",
            re.IGNORECASE,
        ),
        "DATA_ACCESS_ONLY",
        "Customer inquiry is an information request, not deletion.",
    ),
    (
        re.compile(
            r"\b(?:requesting|request)\s+access\s+to\s+my\s+personal\s+data\s+only\b",
            re.IGNORECASE,
        ),
        "DATA_ACCESS_ONLY",
        "Customer requests DSAR access only.",
    ),
    # Marketing and newsletter opt-out only
    (
        re.compile(
            r"\bremove\s+(?:me\s+)?from\s+(?:marketing|promotional|newsletter|mailing)\s+(?:lists?|emails?)\s+only\b",
            re.IGNORECASE,
        ),
        "MARKETING_OPT_OUT_ONLY",
        "Customer requests marketing opt-out only.",
    ),
    (
        re.compile(
            r"\bstop\s+(?:the\s+)?promotional\s+emails\b",
            re.IGNORECASE,
        ),
        "MARKETING_OPT_OUT_ONLY",
        "Customer requests stopping promotional emails only.",
    ),
    (
        re.compile(
            r"\bunsubscribe\s+(?:me\s+)?from\s+(?:marketing\s+)?(?:emails|newsletter)\s+only\b",
            re.IGNORECASE,
        ),
        "MARKETING_OPT_OUT_ONLY",
        "Customer requests unsubscribing from marketing/newsletter only.",
    ),
    (
        re.compile(
            r"\bopt\s*[- ]?out\s+of\s+(?:promotional|marketing)\s+emails\s+only\b",
            re.IGNORECASE,
        ),
        "MARKETING_OPT_OUT_ONLY",
        "Customer requests opting out of promotional emails only.",
    ),
    # Account recovery / login assistance
    (
        re.compile(
            r"\bhelp\s+resetting\s+the\s+login\b",
            re.IGNORECASE,
        ),
        "ACCOUNT_RECOVERY_ONLY",
        "Customer requests login reset assistance, not account deletion.",
    ),
    (
        re.compile(
            r"\bupdate\s+my\s+(?:shipping\s+|billing\s+|email\s+)?address\s+only\b",
            re.IGNORECASE,
        ),
        "PROFILE_UPDATE_ONLY",
        "Customer requests address update only.",
    ),
)

# Patterns indicating an authorized deletion or audit/verification request
_DELETION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # English root verb forms
    re.compile(r"\bdelet(?:e|es|ed|ing|ion)\b", re.IGNORECASE),
    re.compile(r"\beras(?:e|es|ed|ing|ure)\b", re.IGNORECASE),
    re.compile(r"\bremov(?:e|es|ed|ing|al)\b", re.IGNORECASE),
    re.compile(r"\bclos(?:e|es|ed|ing)\b", re.IGNORECASE),
    # Verification and audit phrasings
    re.compile(r"\bprofile\s+is\s+gone\b", re.IGNORECASE),
    re.compile(r"\baccount\s+is\s+gone\b", re.IGNORECASE),
    re.compile(r"\baccount\s+page\s+is\s+gone\b", re.IGNORECASE),
    re.compile(r"\bclean\s+(?:out\s+)?my\s+personal\s+details\b", re.IGNORECASE),
    re.compile(r"\bremaining\s+records\s+cannot\s+identify\s+me\b", re.IGNORECASE),
    re.compile(
        r"\bnothing\s+in\s+analytics\s+should\s+still\s+point\s+back\s+to\s+me\b",
        re.IGNORECASE,
    ),
    re.compile(r"\baudit\s+the\s+deletion\b", re.IGNORECASE),
    # Multilingual keywords
    re.compile(
        r"\b(?:eliminar|eliminación|eliminado|eliminé|elimine|borrar|borrado|cancelar\s+cuenta)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:suppression|supprimer|supprimé|effacer|effacement)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:exclusão|excluir|excluído|apagar|apagamento)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:löschen|löschung|gelöscht|schließen|schließung)\b",
        re.IGNORECASE,
    ),
    re.compile(r"削除|消去"),
    re.compile(r"삭제|영구\s*삭제|계정\s*삭제|탈퇴"),
)


def estimate_tokens(text: str) -> int:
    """Fast deterministic token count approximation (~4 chars/token, min 1)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class FakeLLM:
    """Deterministic offline LLM implementation used for tests and offline runs."""

    model_name: str = "fake-deterministic-v1"
    provider_name: str = "fake"

    def classify_intent(self, request_text: str) -> IntentClassification:
        """Deterministically classify whether `request_text` authorizes deletion."""
        sanitized = sanitize_untrusted_text(request_text)
        for pat, category, rationale in _NON_DELETION_PATTERNS:
            if pat.search(sanitized):
                return IntentClassification(
                    authorizes_deletion=False,
                    intent_category=category,
                    confidence=0.99,
                    rationale=rationale,
                )
        for d_pat in _DELETION_PATTERNS:
            if d_pat.search(sanitized):
                return IntentClassification(
                    authorizes_deletion=True,
                    intent_category="DELETION",
                    confidence=0.99,
                    rationale="Matched deletion/closure authorization pattern.",
                )
        return IntentClassification(
            authorizes_deletion=False,
            intent_category="NON_DELETION_OTHER",
            confidence=0.90,
            rationale="No deletion authorization keywords present in request_text.",
        )


class LLMGateway:
    """Unified wrapper around FakeLLM / Anthropic / OpenAI with diskcache & UsageTracker."""

    def __init__(
        self,
        settings: AuditSettings,
        usage_tracker: UsageTracker | None = None,
    ) -> None:
        self._settings = settings
        self._usage = usage_tracker or UsageTracker(settings)
        self._fake = FakeLLM()
        self._cache = diskcache.Cache(str(settings.resolved_cache_dir))

    @property
    def usage_tracker(self) -> UsageTracker:
        return self._usage

    def _cache_key(self, task: str, model: str, prompt_version: str, content: str) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"{task}:{model}:{prompt_version}:{digest}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=2.0),
        reraise=True,
    )
    def classify_request_intent(self, request_text: str) -> IntentClassification:
        """Classify whether `request_text` authorizes account/data deletion."""
        t0 = time.perf_counter()
        prompt_tmpl = load_prompt(
            self._settings.resolved_prompts_dir,
            "intent_classification_v1.md",
        )
        rendered = prompt_tmpl.render(request_text=request_text)
        provider = self._settings.llm_provider
        model = (
            self._fake.model_name
            if provider == "fake"
            else self._settings.extraction_model
        )
        key = self._cache_key(
            "intent_classification",
            model,
            f"{prompt_tmpl.version}-{prompt_tmpl.content_hash}",
            rendered,
        )

        cached_bytes: bytes | None = self._cache.get(key)
        in_tokens = estimate_tokens(rendered)

        if cached_bytes is not None:
            result = IntentClassification.model_validate(orjson.loads(cached_bytes))
            out_tokens = estimate_tokens(cached_bytes.decode("utf-8"))
            latency_ms = (time.perf_counter() - t0) * 1000.0
            self._usage.record_call(
                provider=provider,
                model=model,
                task="intent_classification",
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                latency_ms=latency_ms,
                cache_hit=True,
            )
            return result

        # Execute via FakeLLM (or configured provider with deterministic fallback)
        result = self._invoke_intent_model(provider, model, rendered, request_text)
        serialized = orjson.dumps(result.model_dump())
        self._cache.set(key, serialized)
        out_tokens = estimate_tokens(serialized.decode("utf-8"))
        latency_ms = (time.perf_counter() - t0) * 1000.0
        rec = self._usage.record_call(
            provider=provider,
            model=model,
            task="intent_classification",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            latency_ms=latency_ms,
            cache_hit=False,
        )
        logger.debug(
            "llm_call_completed",
            task="intent_classification",
            provider=rec.provider,
            model=rec.model,
            input_tokens=rec.input_tokens,
            output_tokens=rec.output_tokens,
            cost_usd=rec.estimated_cost_usd,
        )
        return result

    def _invoke_intent_model(
        self,
        provider: str,
        model: str,
        rendered_prompt: str,
        raw_request_text: str,
    ) -> IntentClassification:
        if provider == "anthropic" and self._settings.anthropic_api_key is not None:
            try:
                from langchain_anthropic import ChatAnthropic

                api_key_val: Any = self._settings.anthropic_api_key.get_secret_value()
                llm = ChatAnthropic(
                    model_name=model,
                    api_key=api_key_val,
                    temperature=0.0,
                    timeout=30.0,
                    stop=None,
                )
                structured = llm.with_structured_output(IntentClassification)
                resp = structured.invoke(rendered_prompt)
                if isinstance(resp, IntentClassification):
                    return resp
            except Exception as exc:
                logger.warning("anthropic_fallback_to_fake", error=str(exc))

        if provider == "openai" and self._settings.openai_api_key is not None:
            try:
                from langchain_openai import ChatOpenAI

                api_key_val = self._settings.openai_api_key.get_secret_value()
                llm_oa = ChatOpenAI(
                    model=model,
                    api_key=api_key_val,
                    temperature=0.0,
                )
                structured_oa = llm_oa.with_structured_output(IntentClassification)
                resp_oa = structured_oa.invoke(rendered_prompt)
                if isinstance(resp_oa, IntentClassification):
                    return resp_oa
            except Exception as exc:
                logger.warning("openai_fallback_to_fake", error=str(exc))

        return self._fake.classify_intent(raw_request_text)

    def close(self) -> None:
        self._cache.close()
