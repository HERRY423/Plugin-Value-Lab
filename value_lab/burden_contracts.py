"""Immutable internal contracts; not a host attestation or wire format."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextRun:
    case_id: str
    repetition: int
    arm: str
    session_id: str
    record_sha256: str
    coverage: str
    expected_samples: int
    samples: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class BurdenCollection:
    design_sha256: str
    observations_sha256: str
    context_observations_sha256: str | None
    case_ids: tuple[str, ...]
    runs_per_case: int
    measurement: tuple[tuple[str, str | int], ...] | None
    runs: tuple[ContextRun, ...]
