from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


STAGES = (
    "product_analysis",
    "research_plan",
    "market_intelligence",
    "icp_generation",
    "account_discovery",
    "account_research",
    "deterministic_scoring",
    "opportunity_brief",
    "campaign_draft",
)


class ResearchWorkflowState(TypedDict):
    workflow_run_id: str
    workspace_id: str
    completed_stages: list[str]
    status: str


def _stage(name: str):
    def execute(state: ResearchWorkflowState) -> ResearchWorkflowState:
        return {
            **state,
            "completed_stages": [*state["completed_stages"], name],
            "status": "completed" if name == STAGES[-1] else "running",
        }

    return execute


def build_research_graph(*, checkpointed: bool = True):
    graph = StateGraph(ResearchWorkflowState)
    for stage in STAGES:
        graph.add_node(stage, _stage(stage))
    graph.add_edge(START, STAGES[0])
    for current, following in zip(STAGES[:-1], STAGES[1:], strict=True):
        graph.add_edge(current, following)
    graph.add_edge(STAGES[-1], END)
    return graph.compile(checkpointer=InMemorySaver() if checkpointed else None)
