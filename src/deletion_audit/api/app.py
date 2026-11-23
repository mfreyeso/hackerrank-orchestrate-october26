"""Thin FastAPI application exposing /health, POST /audit, and GET /audit/{case_id}."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from deletion_audit.config import AuditSettings
from deletion_audit.data import DatasetBundle, load_dataset_bundle
from deletion_audit.graph import run_cases_concurrently
from deletion_audit.llm import LLMGateway
from deletion_audit.models import Case, CaseResult


def create_app(settings: AuditSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    cfg = settings or AuditSettings()
    api = FastAPI(
        title="Deletion Audit Agent API",
        version="0.1.0",
        description="Northstar Shop Deletion-Audit Agent (Ghost Data Still Exists)",
    )
    results_store: dict[str, CaseResult] = {}
    bundle_cache: dict[str, DatasetBundle] = {}

    def _get_bundle() -> DatasetBundle:
        if "bundle" not in bundle_cache:
            sample_b = load_dataset_bundle(cfg, split="sample")
            full_b = load_dataset_bundle(cfg, split="full")
            merged_cases = tuple(
                {c.case_id: c for c in (*sample_b.cases, *full_b.cases)}.values()
            )
            bundle_cache["bundle"] = DatasetBundle(
                cases=merged_cases,
                identities=sample_b.identities,
                audit_log=sample_b.audit_log,
                activities=sample_b.activities,
                rules=sample_b.rules,
                manifest=sample_b.manifest,
            )
        return bundle_cache["bundle"]

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "deletion-audit-agent"}

    @api.post("/audit", response_model=CaseResult)
    async def audit_single_case(case: Case) -> CaseResult:
        bundle = _get_bundle()
        llm = LLMGateway(cfg)
        try:
            results = await run_cases_concurrently([case], cfg, bundle, llm)
            res = results[0]
            results_store[case.case_id] = res
            return res
        finally:
            llm.close()

    @api.get("/audit/{case_id}", response_model=CaseResult)
    async def get_audit_by_case_id(case_id: str) -> CaseResult:
        if case_id in results_store:
            return results_store[case_id]
        bundle = _get_bundle()
        matching = [c for c in bundle.cases if c.case_id == case_id]
        if not matching:
            raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")
        llm = LLMGateway(cfg)
        try:
            results = await run_cases_concurrently(matching, cfg, bundle, llm)
            res = results[0]
            results_store[case_id] = res
            return res
        finally:
            llm.close()

    return api


app = create_app()
