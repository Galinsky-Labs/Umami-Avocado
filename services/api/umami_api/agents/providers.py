"""Planning providers for evidence-linked research agents (UA-019).

A provider turns a structured planning context into a *draft* simulated experiment.
Drafts carry no authority: the platform validates them against a strict schema,
checks every citation against the evidence it supplied, turns them into an immutable
protocol version + proposal and runs deterministic preflight. Nothing a provider
writes can execute physical work, spend money or approve anything.

Providers:
* ``simulated`` - deterministic, rule-based local search over a temperature/pH grid.
  Clearly labelled; used whenever no Anthropic API key is configured.
* ``claude`` - Claude via the official Anthropic SDK with structured outputs.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

SIMULATED_LABEL = "[SIMULATED PLANNER - deterministic rules, not an AI model]"
CLAUDE_MODEL = "claude-opus-5-5"


class PlanDraft(BaseModel):
    """The only shape a provider may return. Bounds mirror the simulator's input ranges."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    hypothesis: str = Field(min_length=10, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)
    temperature_c: float = Field(ge=4, le=45)
    ph: float = Field(ge=3, le=8)
    initial_glucose_g_l: float = Field(gt=0, le=150)
    duration_h: float = Field(gt=0, le=96)
    cited_evidence_ids: list[str] = Field(min_length=1, max_length=10)


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str          # claim | source
    text: str


@dataclass(frozen=True)
class PriorRun:
    temperature_c: float
    ph: float
    initial_glucose_g_l: float
    final_biomass_g_l: float


@dataclass(frozen=True)
class PlanningContext:
    project_name: str
    program: str
    objective: str
    evidence: tuple[Evidence, ...]
    prior_runs: tuple[PriorRun, ...] = field(default_factory=tuple)

    def as_json(self) -> str:
        return json.dumps({
            "project": {"name": self.project_name, "program": self.program,
                        "objective": self.objective},
            "evidence": [e.__dict__ for e in self.evidence],
            "prior_simulated_runs": [r.__dict__ for r in self.prior_runs],
        }, sort_keys=True)


class PlanningProvider(Protocol):
    name: str
    model: str

    def plan(self, context: PlanningContext) -> PlanDraft: ...


class ProviderError(Exception):
    """The provider could not produce a usable draft (refusal, transport, parse)."""


class SimulatedPlanner:
    name = "simulated"
    model = "rule-based-grid-v1"
    TEMPERATURES = (24.0, 27.0, 30.0, 33.0, 36.0)
    PHS = (4.0, 4.5, 5.0, 5.5, 6.0)

    def plan(self, context: PlanningContext) -> PlanDraft:
        tested = {(r.temperature_c, r.ph) for r in context.prior_runs}
        candidates = [(t, p) for t in self.TEMPERATURES for p in self.PHS if (t, p) not in tested]
        if not candidates:
            candidates = [(30.0, 5.0)]
        if context.prior_runs:
            best = max(context.prior_runs, key=lambda r: (r.final_biomass_g_l,
                                                          -r.temperature_c, -r.ph))
            anchor = (best.temperature_c, best.ph)
            reason = (f"the best prior simulated run ({best.final_biomass_g_l:.2f} g/L at "
                      f"{best.temperature_c:g} C, pH {best.ph:g})")
        else:
            anchor, reason = (30.0, 5.0), "the literature-typical optimum for S. cerevisiae"
        t, p = min(candidates, key=lambda c: (abs(c[0] - anchor[0]) / 3 + abs(c[1] - anchor[1])
                                              / 0.5, c[0], c[1]))
        cited = [e.id for e in context.evidence[:3]]
        return PlanDraft(
            title=f"Simulated probe {t:g} C / pH {p:g}",
            hypothesis=(f"Biomass yield at {t:g} C and pH {p:g} will differ measurably from "
                        f"{reason}."),
            rationale=(f"{SIMULATED_LABEL} Local search: nearest untested grid point to "
                       f"{reason}. Cites the first linked evidence items."),
            temperature_c=t, ph=p, initial_glucose_g_l=20.0, duration_h=24.0,
            cited_evidence_ids=cited or ["none"],
        )


SYSTEM_PROMPT = """You plan the next SIMULATED batch-culture experiment for a food-yeast \
research project. You only propose parameters for a deterministic Monod simulator; you cannot \
run physical experiments, order materials or approve anything, and your output is reviewed by \
humans and validated by code.

Choose temperature (C), pH, initial glucose (g/L) and duration (h) that best improve the \
project's objective given the prior simulated runs, preferring informative, untested \
conditions. Cite only evidence IDs that appear in the provided context, and state in the \
rationale which evidence and prior runs motivated the choice and any uncertainty. Simulated \
results are not scientific evidence; do not claim otherwise."""


class ClaudePlanner:
    name = "claude"
    model = CLAUDE_MODEL

    def __init__(self, client=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(max_retries=2, timeout=120.0)
        self.client = client

    def plan(self, context: PlanningContext) -> PlanDraft:
        import anthropic
        try:
            response = self.client.beta.messages.parse(
                model=CLAUDE_MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "medium"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": "Planning context (JSON):\n"
                           + context.as_json()}],
                output_format=PlanDraft,
            )
        except anthropic.APIStatusError as error:
            raise ProviderError(f"Claude API returned HTTP {error.status_code}.") from None
        except anthropic.APIConnectionError:
            raise ProviderError("Claude API could not be reached.") from None
        if response.stop_reason == "refusal":
            raise ProviderError("The model declined to produce a plan.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise ProviderError("The model response was incomplete.")
        return response.parsed_output


def get_provider() -> PlanningProvider:
    """Claude when an API key is configured and AGENT_PROVIDER is not 'simulated'."""
    choice = os.getenv("AGENT_PROVIDER", "auto").strip().lower()
    if choice != "simulated" and os.getenv("ANTHROPIC_API_KEY", "").strip():
        return ClaudePlanner()
    return SimulatedPlanner()
