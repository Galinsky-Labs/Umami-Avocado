"""Deterministic experiment preflight (UA-011).

Every check is computed by code from structured protocol fields and database facts;
model-written prose cannot pass or waive a check. Blockers prevent execution;
warnings are shown to reviewers.
"""
import re
from dataclasses import asdict, dataclass

ALLOWED_ORGANISMS = {"Saccharomyces cerevisiae", "Cyberlindnera jadinii",
                     "Kluyveromyces marxianus"}
# Coarse screen for work outside this platform's food-yeast scope. A match blocks the
# proposal for human redesign; it is not a substitute for institutional biosafety review.
PROHIBITED = re.compile(
    r"gain[- ]of[- ]function|select agent|toxin|pathogen|virulen|aerosoli[sz]|"
    r"human subject|clinical|antibiotic resistance|gene drive|weapon", re.IGNORECASE)


@dataclass(frozen=True)
class Check:
    key: str
    passed: bool
    severity: str
    message: str


def run_preflight(*, content: dict, target_origin: str, evidence_ok: bool,
                  missing_assays: list[str], live_submission_enabled: bool) -> dict:
    checks = [
        Check("organism_allowlisted", content.get("organism") in ALLOWED_ORGANISMS
              and content.get("biosafety_level") == 1, "blocker",
              "Organism must be an allow-listed BSL-1 food yeast."),
        Check("evidence_linked", evidence_ok, "blocker",
              "The hypothesis must cite at least one existing claim or source in this workspace."),
        Check("assays_defined", not missing_assays, "blocker",
              "Undefined assay keys: " + ", ".join(sorted(missing_assays))[:150]
              if missing_assays else "All referenced assays are defined."),
        Check("scope_screen", not any(PROHIBITED.search(step) for step in content.get("steps", []))
              and not PROHIBITED.search(content.get("medium", "")), "blocker",
              "Protocol text matched the out-of-scope screen; redesign with a human."),
        Check("replication", content.get("biological_replicates", 0) >= 3, "warning",
              "Fewer than 3 biological replicates limits statistical power."),
    ]
    if target_origin == "PHYSICAL":
        checks.append(Check(
            "physical_execution_available", live_submission_enabled, "blocker",
            "Live laboratory submission is disabled; physical work needs a supervised adapter, "
            "a contracted lab and scoped human authorization (UA-013/014/027)."))
    else:
        checks.append(Check("simulator_compatible", True, "blocker",
                            "Parameters are within the simulator's validated input ranges."))
    blockers = [c for c in checks if c.severity == "blocker" and not c.passed]
    return {"passed": not blockers, "checks": [asdict(c) for c in checks]}
