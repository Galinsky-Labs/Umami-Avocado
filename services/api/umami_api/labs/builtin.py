"""Built-in adapters: the deterministic simulator and the supervised manual CRO adapter."""
import csv
import hashlib
import io

from umami_api.labs.sdk import (
    Capability,
    IntegrationMode,
    LabAdapter,
    Quote,
    ResultFile,
    Submission,
    SubmissionState,
    WorkOrder,
    dispatch_guard,
)
from umami_api.science.simulator import Design, simulate

FOOD_YEASTS = ("Saccharomyces cerevisiae", "Cyberlindnera jadinii", "Kluyveromyces marxianus")


class SimulatedLabAdapter(LabAdapter):
    """Deterministic in-process 'laboratory'. Every result is SIMULATED."""
    key = "simulator"
    mode = IntegrationMode.SIMULATED
    origin = "SIMULATED"

    def __init__(self):
        self._orders: dict[str, tuple[WorkOrder, SubmissionState]] = {}

    def capabilities(self) -> list[Capability]:
        return [Capability("batch_fermentation", FOOD_YEASTS,
                           ("sim-dcw", "sim-glucose", "sim-glutamate"), 10.0, 0, 0)]

    def quote(self, order: WorkOrder) -> Quote:
        self._require(order)
        return Quote(order.order_id, 0, "USD", 30, "SIMULATED")

    def submit(self, order: WorkOrder) -> Submission:
        self._require(order)
        if order.order_id in self._orders:  # idempotent resubmission
            return Submission(self._external(order.order_id), self._orders[order.order_id][1])
        self._orders[order.order_id] = (order, SubmissionState.RESULTS_READY)
        return Submission(self._external(order.order_id), SubmissionState.RESULTS_READY)

    def status(self, external_id: str) -> SubmissionState:
        return self._lookup(external_id)[1]

    def fetch_results(self, external_id: str) -> list[ResultFile]:
        order, state = self._lookup(external_id)
        if state not in (SubmissionState.RESULTS_READY, SubmissionState.COMPLETED):
            return []
        p = order.parameters
        seed = int(hashlib.sha256(order.order_id.encode()).hexdigest()[:7], 16)
        samples = simulate(Design(
            temperature_c=float(p.get("temperature_c", 30)), ph=float(p.get("ph", 5)),
            initial_glucose_g_l=float(p.get("initial_glucose_g_l", 20)),
            initial_biomass_g_l=float(p.get("initial_biomass_g_l", 0.1)),
            duration_h=float(p.get("duration_h", 24)),
            sample_interval_h=float(p.get("sample_interval_h", 4)),
            biological_replicates=order.replicates, technical_replicates=1, seed=seed))
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["quantity", "unit", "time_h", "biological_replicate",
                         "technical_replicate", "value", "origin"])
        for s in samples:
            writer.writerow([s.quantity, s.unit, s.time_h, s.biological_replicate,
                             s.technical_replicate, s.value, "SIMULATED"])
        self._orders[order.order_id] = (order, SubmissionState.COMPLETED)
        return [ResultFile("results.csv", "text/csv", buffer.getvalue().encode(), "SIMULATED")]

    def cancel(self, external_id: str) -> SubmissionState:
        order, state = self._lookup(external_id)
        if state in (SubmissionState.COMPLETED,):
            return state
        self._orders[order.order_id] = (order, SubmissionState.CANCELLED)
        return SubmissionState.CANCELLED

    def _require(self, order: WorkOrder) -> None:
        if not self.supports(order.capability, order.organism):
            raise ValueError("The simulator does not offer this capability for this organism.")

    @staticmethod
    def _external(order_id: str) -> str:
        return "sim-" + order_id

    def _lookup(self, external_id: str):
        order_id = external_id.removeprefix("sim-")
        if order_id not in self._orders:
            raise KeyError("Unknown submission.")
        return self._orders[order_id]


class ManualCROAdapter(LabAdapter):
    """Human-supervised exchange with a contract research organisation (UA-014).

    It never transmits anything itself: a person sends the approved work-order package and
    uploads returned files. ``submit`` is still dispatch-guarded so that recording a
    submission is impossible while live submission is disabled."""
    key = "manual_cro"
    mode = IntegrationMode.MANUAL
    origin = "PHYSICAL"

    def __init__(self, capabilities: list[Capability] | None = None,
                 live_submission_enabled: bool = False):
        self._capabilities = capabilities or []
        self._live = live_submission_enabled

    def capabilities(self) -> list[Capability]:
        return list(self._capabilities)

    def quote(self, order: WorkOrder) -> Quote:
        raise NotImplementedError("Manual CRO quotes are recorded by a human from the vendor.")

    def submit(self, order: WorkOrder) -> Submission:
        dispatch_guard(self, self._live)
        raise NotImplementedError("Manual CRO submission is performed by a supervised human.")

    def status(self, external_id: str) -> SubmissionState:
        raise NotImplementedError("Manual CRO status is recorded by a human.")

    def fetch_results(self, external_id: str) -> list[ResultFile]:
        return []

    def cancel(self, external_id: str) -> SubmissionState:
        return SubmissionState.CANCELLED


ADAPTERS: dict[str, type[LabAdapter]] = {"simulator": SimulatedLabAdapter,
                                         "manual_cro": ManualCROAdapter}
