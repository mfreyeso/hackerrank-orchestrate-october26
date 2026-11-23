"""End-to-end sample pipeline and FastAPI endpoint integration tests."""

from __future__ import annotations

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from deletion_audit.api import create_app
from deletion_audit.config import AuditSettings
from deletion_audit.data import load_dataset_bundle
from deletion_audit.eval_metrics import evaluate_predictions
from deletion_audit.graph import run_cases_concurrently
from deletion_audit.llm import LLMGateway
from deletion_audit.output import validate_output_file, write_output_csv


async def test_end_to_end_sample_pipeline(tmp_path: Path) -> None:
    settings = AuditSettings(cache_dir=tmp_path / "cache")
    bundle = load_dataset_bundle(settings, split="sample")
    llm = LLMGateway(settings)
    try:
        results = await run_cases_concurrently(bundle.cases, settings, bundle, llm)
        assert len(results) == 32

        out_csv = tmp_path / "sample_predictions.csv"
        write_output_csv(results, out_csv)
        validated = validate_output_file(
            out_csv,
            expected_case_ids=[c.case_id for c in bundle.cases],
        )
        assert len(validated) == 32

        summary = evaluate_predictions(out_csv, Path("dataset/sample_output.csv"))
        assert summary.total_cases == 32
        assert summary.status_accuracy >= 0.75
    finally:
        llm.close()


async def test_fastapi_endpoints(tmp_path: Path) -> None:
    settings = AuditSettings(cache_dir=tmp_path / "api_cache")
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp_health = await client.get("/health")
        assert resp_health.status_code == 200
        assert resp_health.json()["status"] == "ok"

        resp_case = await client.get("/audit/case_01")
        assert resp_case.status_code == 200
        body = resp_case.json()
        assert body["case_id"] == "case_01"
        assert body["deletion_status"] == "COMPLETE"

        # Test POST /audit with a NOT_APPLICABLE request
        post_payload = {
            "case_id": "case_custom_na",
            "email": "amina.elmasri@gmail.com",
            "requested_at": "2026-08-18T09:14:00Z",
            "reported_status": "NOT_STARTED",
            "reported_at": "2026-08-20T16:42:00Z",
            "audit_at": "2026-09-03T11:30:00Z",
            "request_text": "I only want a copy of my data; please do not delete my account.",
        }
        resp_post = await client.post("/audit", json=post_payload)
        assert resp_post.status_code == 200
        post_data = resp_post.json()
        assert post_data["deletion_status"] == "NOT_APPLICABLE"
        assert post_data["steps"] == []
