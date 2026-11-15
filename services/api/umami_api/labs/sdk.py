"""Laboratory adapter SDK (UA-013).

Every laboratory integration implements :class:`LabAdapter`. The platform talks to labs
only through this interface, and every method that could cause physical work or data
transfer goes through :func:`dispatch_guard`, which refuses while live submission is
disabled. Adapters never decide authorization: callers must already have passed the
policy engine. Results returned by an adapter are labelled with the adapter's origin and
are never relabelled downstream.
"""
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class LiveSubmissionDisabled(RuntimeError):
    """Raised by any physical adapter while LAB_LIVE_SUBMISSION_ENABLED is false."""


class AdapterError(RuntimeError):
    """A provider-side failure (rejected order, malformed payload, transport error)."""


class IntegrationMode(str, Enum):
    SIMULATED = "simulated"   # in-process deterministic simulator, SIMULATED results
    MANUAL = "manual"         # human-supervised file exchange with a CRO (UA-014)
    API = "api"               # direct machine integration (UA-027, not implemented)


class SubmissionState(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    RESULTS_READY = "results_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = {SubmissionState.COMPLETED, SubmissionState.FAILED, SubmissionState.CANCELLED}


@dataclass(frozen=True)
class Capability:
    code: str                         # e.g. "batch_fermentation", "dcw_assay"
    organisms: tuple[str, ...]
    assay_keys: tuple[str, ...] = ()
    max_volume_l: float = 1.0
    turnaround_days: int = 14
    unit_price_cents: int = 0


@dataclass(frozen=True)
class WorkOrder:
    order_id: str
    capability: str
    organism: str
    parameters: dict
    replicates: int = 3


@dataclass(frozen=True)
class Quote:
    order_id: str
    amount_cents: int
    currency: str
    valid_days: int
    origin: str                       # SIMULATED | PHYSICAL


@dataclass(frozen=True)
class Submission:
    external_id: str
    state: SubmissionState


@dataclass(frozen=True)
class ResultFile:
    name: str
    media_type: str
    content: bytes
    origin: str
    sha256: str = field(default="")

    def __post_init__(self):
        if not self.sha256:
            object.__setattr__(self, "sha256", hashlib.sha256(self.content).hexdigest())


class LabAdapter(ABC):
    key: str
    mode: IntegrationMode
    origin: str                       # origin of every result this adapter returns

    @abstractmethod
    def capabilities(self) -> list[Capability]: ...

    @abstractmethod
    def quote(self, order: WorkOrder) -> Quote: ...

    @abstractmethod
    def submit(self, order: WorkOrder) -> Submission: ...

    @abstractmethod
    def status(self, external_id: str) -> SubmissionState: ...

    @abstractmethod
    def fetch_results(self, external_id: str) -> list[ResultFile]: ...

    @abstractmethod
    def cancel(self, external_id: str) -> SubmissionState: ...

    def supports(self, capability: str, organism: str) -> bool:
        return any(c.code == capability and organism in c.organisms for c in self.capabilities())


def dispatch_guard(adapter: LabAdapter, live_submission_enabled: bool) -> None:
    """Call before any operation that could start physical work or send data to a lab."""
    if adapter.origin != "SIMULATED" and not live_submission_enabled:
        raise LiveSubmissionDisabled(
            "Live laboratory submission is disabled; physical adapters cannot dispatch.")
