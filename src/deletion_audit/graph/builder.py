"""LangGraph builder and async batch execution runner with reported_status sequential-smart routing."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from deletion_audit.config import AuditSettings
from deletion_audit.data.loaders import DatasetBundle
from deletion_audit.graph.nodes import GraphNodes
from deletion_audit.graph.state import CaseGraphState
from deletion_audit.llm.client import LLMGateway
from deletion_audit.models import Case, CaseResult, ReportedStatus


def _route_by_reported_status(state: CaseGraphState) -> str:
    """Route sequentially to the branch matching the case's reported_status claim."""
    reported_status = state["case"].reported_status
    if reported_status == ReportedStatus.COMPLETE:
        return "complete_flow_checker"
    if reported_status == ReportedStatus.PARTIALLY_COMPLETE:
        return "partial_flow_checker"
    return "not_started_flow_checker"


def _route_after_verifier(state: CaseGraphState) -> str:
    if state.get("needs_rerun", False):
        return "timestamp_lineage_pruner"
    return str(END)


def build_case_graph(
    settings: AuditSettings,
    bundle: DatasetBundle,
    llm: LLMGateway,
) -> Any:
    """Compile the per-case sequential-smart LangGraph state machine."""
    nodes = GraphNodes(settings, bundle, llm)

    builder = StateGraph(CaseGraphState)
    builder.add_node("identity_resolver", nodes.identity_resolver)
    builder.add_node("timestamp_lineage_pruner", nodes.timestamp_lineage_pruner)
    builder.add_node("complete_flow_checker", nodes.complete_flow_checker)
    builder.add_node("partial_flow_checker", nodes.partial_flow_checker)
    builder.add_node("not_started_flow_checker", nodes.not_started_flow_checker)
    builder.add_node("state_reconstructor", nodes.state_reconstructor)
    builder.add_node("policy_engine", nodes.policy_engine)
    builder.add_node("planner", nodes.planner)
    builder.add_node("verifier", nodes.verifier)

    builder.add_edge(START, "identity_resolver")
    builder.add_edge("identity_resolver", "timestamp_lineage_pruner")
    builder.add_conditional_edges(
        "timestamp_lineage_pruner",
        _route_by_reported_status,
        {
            "complete_flow_checker": "complete_flow_checker",
            "partial_flow_checker": "partial_flow_checker",
            "not_started_flow_checker": "not_started_flow_checker",
        },
    )
    builder.add_edge("complete_flow_checker", "state_reconstructor")
    builder.add_edge("partial_flow_checker", "state_reconstructor")
    builder.add_edge("not_started_flow_checker", "state_reconstructor")
    builder.add_edge("state_reconstructor", "policy_engine")
    builder.add_edge("policy_engine", "planner")
    builder.add_edge("planner", "verifier")
    builder.add_conditional_edges(
        "verifier",
        _route_after_verifier,
        {
            "timestamp_lineage_pruner": "timestamp_lineage_pruner",
            str(END): END,
        },
    )

    return builder.compile()


async def run_cases_concurrently(
    cases: Sequence[Case],
    settings: AuditSettings,
    bundle: DatasetBundle,
    llm: LLMGateway,
) -> list[CaseResult]:
    """Run the compiled per-case graph across all cases with a bounded asyncio.Semaphore."""
    compiled_graph = build_case_graph(settings, bundle, llm)
    sem = asyncio.Semaphore(settings.max_concurrency)

    async def _run_one(c: Case) -> CaseResult:
        async with sem:
            initial_state: CaseGraphState = {
                "case": c,
                "facts": [],
                "validation_errors": [],
                "retry_count": 0,
                "needs_rerun": False,
            }
            final_state: dict[str, Any] = await asyncio.to_thread(
                compiled_graph.invoke,
                initial_state,
            )
            res: CaseResult = final_state["result"]
            return res

    tasks = [_run_one(c) for c in cases]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda r: r.case_id)
