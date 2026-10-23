from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Iterator


@dataclass(slots=True)
class StageMetrics:
    """Monotonic, cumulative timings and operation counters for one scope.

    Timings are deliberately kept separate from wall-clock timestamps.  The
    latter make a run auditable while these values make stage comparisons
    reproducible across runs without depending on clock adjustments.
    Nested stages are allowed; their durations are cumulative by design.
    """

    elapsed_ns: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def add_elapsed(self, stage: str, elapsed_ns: int) -> None:
        self.elapsed_ns[stage] = self.elapsed_ns.get(stage, 0) + max(0, elapsed_ns)

    def add_count(self, name: str, value: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + value

    def merge(self, other: "StageMetrics") -> None:
        for stage, elapsed_ns in other.elapsed_ns.items():
            self.add_elapsed(stage, elapsed_ns)
        for name, value in other.counts.items():
            self.add_count(name, value)

    def timings_ms(self) -> dict[str, float]:
        return {name: round(value / 1_000_000, 3) for name, value in self.elapsed_ns.items()}


@contextmanager
def timed(metrics: StageMetrics, stage: str) -> Iterator[None]:
    started = perf_counter_ns()
    try:
        yield
    finally:
        metrics.add_elapsed(stage, perf_counter_ns() - started)


def elapsed_ms(started_ns: int) -> float:
    return round((perf_counter_ns() - started_ns) / 1_000_000, 3)
