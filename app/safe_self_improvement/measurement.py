"""Evidence-preserving before/after improvement measurements."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Callable, Dict, Mapping, Optional


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    NO_DIRECTION = "no_direction"


class ComparisonStatus(str, Enum):
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    REGRESSED = "regressed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class MetricMeasurement:
    name: str
    value: Optional[float]
    unit: str = ""
    direction: MetricDirection = MetricDirection.NO_DIRECTION
    provenance: str = ""
    valid: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["direction"] = self.direction.value
        return data


@dataclass(frozen=True)
class MetricComparison:
    name: str
    before: Optional[MetricMeasurement]
    after: Optional[MetricMeasurement]
    status: ComparisonStatus
    delta: Optional[float] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "before": self.before.to_dict() if self.before else None,
            "after": self.after.to_dict() if self.after else None,
            "status": self.status.value,
            "delta": self.delta,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ImprovementEvidence:
    before: Dict[str, MetricMeasurement]
    after: Dict[str, MetricMeasurement]
    comparisons: Dict[str, MetricComparison]
    valid: bool
    provenance: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "before": {name: value.to_dict() for name, value in self.before.items()},
            "after": {name: value.to_dict() for name, value in self.after.items()},
            "comparisons": {name: value.to_dict() for name, value in self.comparisons.items()},
            "valid": self.valid,
            "provenance": self.provenance,
        }


class ImprovementMeasurement:
    """Collect and compare factual metric snapshots."""

    def __init__(self, collector: Optional[Callable[[], Mapping[str, Any]]] = None, provenance: str = "") -> None:
        self._collector = collector
        self._provenance = provenance

    def collect(self, metrics: Optional[Mapping[str, Any]] = None, *, definitions: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, MetricMeasurement]:
        raw = metrics if metrics is not None else (self._collector() if self._collector else None)
        if not isinstance(raw, Mapping):
            return {}
        definitions = definitions or {}
        result: Dict[str, MetricMeasurement] = {}
        for name, value in raw.items():
            definition = definitions.get(name, {})
            direction = definition.get("direction", MetricDirection.NO_DIRECTION)
            try:
                direction = MetricDirection(direction)
            except (TypeError, ValueError):
                direction = MetricDirection.NO_DIRECTION
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))
            numeric_value = float(value) if valid else None
            if not valid:
                result[str(name)] = MetricMeasurement(
                    name=str(name), value=None, unit=str(definition.get("unit", "")),
                    direction=direction, provenance=str(definition.get("provenance", self._provenance)), valid=False,
                )
                continue
            result[str(name)] = MetricMeasurement(
                name=str(name),
                value=numeric_value,
                unit=str(definition.get("unit", "")),
                direction=direction,
                provenance=str(definition.get("provenance", self._provenance)),
            )
        return result

    @staticmethod
    def compare(
        before: Mapping[str, MetricMeasurement],
        after: Mapping[str, MetricMeasurement],
        *,
        tolerance: float = 0.0,
        provenance: str = "",
    ) -> ImprovementEvidence:
        comparisons: Dict[str, MetricComparison] = {}
        for name in sorted(set(before) | set(after)):
            old = before.get(name)
            new = after.get(name)
            if old is None or new is None:
                comparisons[name] = MetricComparison(name, old, new, ComparisonStatus.INCONCLUSIVE, reason="metric_missing")
                continue
            if not old.valid or not new.valid or old.unit != new.unit or old.direction != new.direction:
                comparisons[name] = MetricComparison(name, old, new, ComparisonStatus.INCONCLUSIVE, reason="incompatible_measurements")
                continue
            delta = new.value - old.value
            if abs(delta) <= tolerance:
                status = ComparisonStatus.UNCHANGED
            elif old.direction == MetricDirection.HIGHER_IS_BETTER:
                status = ComparisonStatus.IMPROVED if delta > 0 else ComparisonStatus.REGRESSED
            elif old.direction == MetricDirection.LOWER_IS_BETTER:
                status = ComparisonStatus.IMPROVED if delta < 0 else ComparisonStatus.REGRESSED
            else:
                status = ComparisonStatus.INCONCLUSIVE
            comparisons[name] = MetricComparison(name, old, new, status, delta=delta)
        valid = bool(comparisons) and all(item.status != ComparisonStatus.INCONCLUSIVE for item in comparisons.values())
        return ImprovementEvidence(dict(before), dict(after), comparisons, valid, provenance)


def measure_improvement(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    definitions: Optional[Mapping[str, Mapping[str, Any]]] = None,
    tolerance: float = 0.0,
    provenance: str = "",
) -> ImprovementEvidence:
    measurement = ImprovementMeasurement(provenance=provenance)
    return measurement.compare(
        measurement.collect(before, definitions=definitions),
        measurement.collect(after, definitions=definitions),
        tolerance=tolerance,
        provenance=provenance,
    )


__all__ = [
    "MetricDirection",
    "ComparisonStatus",
    "MetricMeasurement",
    "MetricComparison",
    "ImprovementEvidence",
    "ImprovementMeasurement",
    "measure_improvement",
]
