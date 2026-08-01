"""Learning From Decisions - Analyze successful vs failed decisions and update confidence models.

This module implements the Learning From Decisions capability (Phase 2+ enhancement):
- Analyzes decision outcomes to identify patterns
- Updates confidence models based on actual vs predicted outcomes
- Provides recommendations for improving decision quality
- Integrates with DecisionHistory and ConfidenceCalculator
"""

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import uuid

from app.decision.history import DecisionHistory, DecisionRecord
from app.decision.models import DecisionType, DecisionCategory
from app.confidence.confidence_scoring import ConfidenceCalculator, ConfidenceLevel, ConfidenceEvent, ConfidenceEventType

logger = logging.getLogger(__name__)


@dataclass
class DecisionPattern:
    """A recognized pattern in decision outcomes."""
    pattern_id: str
    description: str
    decision_types: List[str]
    conditions: Dict[str, Any]
    success_rate: float
    sample_size: int
    confidence_adjustment: float  # How much to adjust confidence for similar decisions
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "description": self.description,
            "decision_types": self.decision_types,
            "conditions": self.conditions,
            "success_rate": self.success_rate,
            "sample_size": self.sample_size,
            "confidence_adjustment": self.confidence_adjustment,
            "discovered_at": self.discovered_at,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionPattern":
        return cls(**data)


@dataclass
class LearningInsight:
    """An insight derived from decision outcome analysis."""
    insight_id: str
    insight_type: str  # "pattern", "bias", "recommendation", "anomaly"
    title: str
    description: str
    severity: str  # "info", "warning", "critical"
    affected_decision_types: List[str]
    recommended_action: str
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "affected_decision_types": self.affected_decision_types,
            "recommended_action": self.recommended_action,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "created_at": self.created_at,
        }


@dataclass
class ConfidenceCalibration:
    """Calibration data for a specific decision context."""
    context_key: str
    decision_type: str
    predicted_confidence: float
    actual_outcome: bool
    calibration_error: float  # positive = overconfident, negative = underconfident
    sample_count: int = 1
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_overconfident(self) -> bool:
        return self.calibration_error > 0.1

    @property
    def is_underconfident(self) -> bool:
        return self.calibration_error < -0.1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_key": self.context_key,
            "decision_type": self.decision_type,
            "predicted_confidence": self.predicted_confidence,
            "actual_outcome": self.actual_outcome,
            "calibration_error": self.calibration_error,
            "sample_count": self.sample_count,
            "last_updated": self.last_updated,
        }


class LearningFromDecisions:
    """Analyzes decision outcomes and updates confidence models.

    This class provides the Learning From Decisions capability:
    1. Analyzes successful vs failed decisions from history
    2. Identifies patterns in decision contexts and outcomes
    3. Computes confidence calibration adjustments
    4. Generates actionable insights for improvement
    5. Updates confidence models with learned adjustments
    """

    def __init__(
        self,
        decision_history: DecisionHistory,
        confidence_calculator: Optional[ConfidenceCalculator] = None,
        workspace: str = ".",
        min_samples_for_pattern: int = 5,
        min_samples_for_calibration: int = 3,
    ):
        """Initialize the learning engine.

        Args:
            decision_history: DecisionHistory instance with recorded outcomes
            confidence_calculator: Optional ConfidenceCalculator to update
            workspace: Workspace path for persistence
            min_samples_for_pattern: Minimum samples to recognize a pattern
            min_samples_for_calibration: Minimum samples for calibration
        """
        self.decision_history = decision_history
        self.confidence_calculator = confidence_calculator or ConfidenceCalculator()
        self.workspace = Path(workspace).resolve()
        self.min_samples_pattern = min_samples_for_pattern
        self.min_samples_calibration = min_samples_for_calibration

        self._lock = threading.RLock()
        self._patterns: Dict[str, DecisionPattern] = {}
        self._calibrations: Dict[str, ConfidenceCalibration] = {}
        self._insights: List[LearningInsight] = []
        self._storage_path = self.workspace / "data" / "decision_learning.json"

        self._load()

    def _load(self) -> None:
        """Load learning data from disk."""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for p in data.get("patterns", []):
                pattern = DecisionPattern.from_dict(p)
                self._patterns[pattern.pattern_id] = pattern

            for c in data.get("calibrations", []):
                cal = ConfidenceCalibration(**c)
                self._calibrations[cal.context_key] = cal

            for i in data.get("insights", []):
                self._insights.append(LearningInsight(**i))

            logger.info(f"[LearningFromDecisions] Loaded {len(self._patterns)} patterns, "
                       f"{len(self._calibrations)} calibrations, {len(self._insights)} insights")
        except Exception as e:
            logger.warning(f"[LearningFromDecisions] Failed to load learning data: {e}")

    def _save(self) -> None:
        """Save learning data to disk."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(".tmp")
        try:
            data = {
                "patterns": [p.to_dict() for p in self._patterns.values()],
                "calibrations": [c.to_dict() for c in self._calibrations.values()],
                "insights": [i.to_dict() for i in self._insights],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self._storage_path)
        except Exception as e:
            logger.error(f"[LearningFromDecisions] Failed to save learning data: {e}")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def analyze_outcomes(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Analyze decision outcomes and update patterns/calibrations.

        Args:
            force_refresh: If True, re-analyze all records even if recently analyzed

        Returns:
            Analysis summary with discovered patterns, calibrations, and insights
        """
        with self._lock:
            records = self._get_records_with_outcomes()

            if len(records) < self.min_samples_calibration:
                return {
                    "message": "Insufficient outcome data for analysis",
                    "records_analyzed": len(records),
                    "patterns_found": 0,
                    "calibrations_updated": 0,
                    "insights_generated": 0,
                }

            # Update calibrations
            calibrations_updated = self._update_calibrations(records)

            # Discover patterns
            patterns_found = self._discover_patterns(records)

            # Generate insights
            insights_generated = self._generate_insights(records)

            # Save results
            self._save()

            return {
                "records_analyzed": len(records),
                "patterns_found": patterns_found,
                "calibrations_updated": calibrations_updated,
                "insights_generated": insights_generated,
                "overall_calibration": self._get_overall_calibration(),
            }

    def get_confidence_adjustment(
        self,
        decision_type: DecisionType,
        context: Dict[str, Any],
    ) -> Tuple[float, str]:
        """Get confidence adjustment for a decision context.

        Args:
            decision_type: Type of decision being made
            context: Context information (risk_level, complexity, etc.)

        Returns:
            Tuple of (adjustment_factor, explanation)
            adjustment_factor: Multiplier for confidence (e.g., 0.9 = reduce by 10%)
        """
        with self._lock:
            # Build context key
            context_key = self._build_context_key(decision_type, context)

            # Check for exact match in calibrations
            if context_key in self._calibrations:
                cal = self._calibrations[context_key]
                if cal.sample_count >= self.min_samples_calibration:
                    # Adjust based on calibration error
                    # Overconfident -> reduce confidence, Underconfident -> increase
                    adjustment = 1.0 - cal.calibration_error
                    adjustment = max(0.5, min(1.5, adjustment))  # Clamp
                    return adjustment, f"Calibrated from {cal.sample_count} samples (error: {cal.calibration_error:.2f})"

            # Check for matching patterns
            best_pattern = None
            best_match_score = 0
            for pattern in self._patterns.values():
                if decision_type.value not in pattern.decision_types:
                    continue
                score = self._match_pattern_conditions(pattern.conditions, context)
                if score > best_match_score and score > 0.5:
                    best_match_score = score
                    best_pattern = pattern

            if best_pattern and best_pattern.sample_size >= self.min_samples_pattern:
                # Apply pattern's confidence adjustment
                adjustment = 1.0 + best_pattern.confidence_adjustment
                adjustment = max(0.5, min(1.5, adjustment))
                return adjustment, f"Pattern match: {best_pattern.description} (confidence: {best_match_score:.2f})"

            return 1.0, "No calibration or pattern match"

    def get_patterns(
        self,
        decision_type: Optional[DecisionType] = None,
        min_success_rate: Optional[float] = None,
    ) -> List[DecisionPattern]:
        """Get discovered decision patterns.

        Args:
            decision_type: Optional filter by decision type
            min_success_rate: Optional minimum success rate filter

        Returns:
            List of matching patterns
        """
        with self._lock:
            patterns = list(self._patterns.values())

            if decision_type:
                patterns = [p for p in patterns if decision_type.value in p.decision_types]

            if min_success_rate is not None:
                patterns = [p for p in patterns if p.success_rate >= min_success_rate]

            return sorted(patterns, key=lambda p: p.success_rate, reverse=True)

    def get_calibrations(self) -> List[ConfidenceCalibration]:
        """Get all confidence calibrations."""
        with self._lock:
            return list(self._calibrations.values())

    def get_insights(
        self,
        severity: Optional[str] = None,
        insight_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[LearningInsight]:
        """Get generated insights.

        Args:
            severity: Optional filter by severity
            insight_type: Optional filter by type
            limit: Maximum number of insights to return

        Returns:
            List of matching insights
        """
        with self._lock:
            insights = self._insights

            if severity:
                insights = [i for i in insights if i.severity == severity]
            if insight_type:
                insights = [i for i in insights if i.insight_type == insight_type]

            # Sort by severity and confidence
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            insights.sort(key=lambda i: (severity_order.get(i.severity, 3), -i.confidence))

            return insights[:limit]

    def record_decision_outcome(
        self,
        decision_id: str,
        predicted_confidence: float,
        actual_success: bool,
        context: Dict[str, Any],
    ) -> None:
        """Record a decision outcome for learning.

        This can be called directly to add learning data without going through
        the full decision history.

        Args:
            decision_id: ID of the decision
            predicted_confidence: The confidence that was predicted
            actual_success: Whether the decision actually succeeded
            context: Context of the decision
        """
        with self._lock:
            decision_type_str = context.get("decision_type", "unknown")
            context_key = self._build_context_key_from_dict(decision_type_str, context)

            error = predicted_confidence - (1.0 if actual_success else 0.0)

            if context_key in self._calibrations:
                cal = self._calibrations[context_key]
                # Running average
                cal.calibration_error = (
                    cal.calibration_error * cal.sample_count + error
                ) / (cal.sample_count + 1)
                cal.sample_count += 1
                cal.last_updated = datetime.now(timezone.utc).isoformat()
            else:
                self._calibrations[context_key] = ConfidenceCalibration(
                    context_key=context_key,
                    decision_type=decision_type_str,
                    predicted_confidence=predicted_confidence,
                    actual_outcome=actual_success,
                    calibration_error=error,
                )

            # Check if this generates an insight
            self._check_calibration_insight(context_key)

            self._save()

    # -------------------------------------------------------------------------
    # Internal Analysis Methods
    # -------------------------------------------------------------------------

    def _get_records_with_outcomes(self) -> List[DecisionRecord]:
        """Get all decision records that have outcomes recorded."""
        all_records = list(self.decision_history._records.values())
        return [r for r in all_records if r.outcome is not None]

    def _update_calibrations(self, records: List[DecisionRecord]) -> int:
        """Update confidence calibrations from outcome records."""
        updated = 0

        for record in records:
            if record.actual_success is None or record.confidence == 0:
                continue

            context_key = self._build_context_key_from_record(record)
            error = record.confidence - (1.0 if record.actual_success else 0.0)

            if context_key in self._calibrations:
                cal = self._calibrations[context_key]
                cal.calibration_error = (
                    cal.calibration_error * cal.sample_count + error
                ) / (cal.sample_count + 1)
                cal.sample_count += 1
                cal.last_updated = datetime.now(timezone.utc).isoformat()
            else:
                self._calibrations[context_key] = ConfidenceCalibration(
                    context_key=context_key,
                    decision_type=record.decision_type.value,
                    predicted_confidence=record.confidence,
                    actual_outcome=record.actual_success,
                    calibration_error=error,
                )
                updated += 1

        return updated

    def _discover_patterns(self, records: List[DecisionRecord]) -> int:
        """Discover patterns in decision outcomes."""
        # Group records by decision type and context features
        groups = defaultdict(list)

        for record in records:
            # Create a feature key from context
            features = self._extract_features(record)
            feature_key = f"{record.decision_type.value}|{features}"
            groups[feature_key].append(record)

        patterns_found = 0

        for feature_key, group_records in groups.items():
            if len(group_records) < self.min_samples_pattern:
                continue

            # Calculate success rate
            success_count = sum(1 for r in group_records if r.actual_success)
            success_rate = success_count / len(group_records)

            # Only create pattern if significantly different from average
            avg_success = sum(1 for r in records if r.actual_success) / len(records) if records else 0.5
            diff = abs(success_rate - avg_success)

            if diff > 0.15:  # At least 15% difference from average
                decision_type_str = group_records[0].decision_type.value

                # Check if pattern already exists
                existing = None
                for p in self._patterns.values():
                    if decision_type_str in p.decision_types and self._match_pattern_conditions(p.conditions, self._parse_feature_key(feature_key)) > 0.8:
                        existing = p
                        break

                if existing:
                    # Update existing pattern
                    existing.success_rate = (existing.success_rate * existing.sample_size + success_count) / (existing.sample_size + len(group_records))
                    existing.sample_size += len(group_records)
                    existing.last_updated = datetime.now(timezone.utc).isoformat()
                    existing.confidence_adjustment = self._calculate_adjustment(existing.success_rate, avg_success)
                else:
                    # Create new pattern
                    conditions = self._parse_feature_key(feature_key)
                    pattern = DecisionPattern(
                        pattern_id=f"pat_{uuid.uuid4().hex[:8]}",
                        description=f"{decision_type_str} with {features}: {success_rate:.0%} success",
                        decision_types=[decision_type_str],
                        conditions=conditions,
                        success_rate=success_rate,
                        sample_size=len(group_records),
                        confidence_adjustment=self._calculate_adjustment(success_rate, avg_success),
                    )
                    self._patterns[pattern.pattern_id] = pattern
                    patterns_found += 1

        return patterns_found

    def _generate_insights(self, records: List[DecisionRecord]) -> int:
        """Generate actionable insights from analysis."""
        insights_before = len(self._insights)

        # 1. Overall calibration bias insight
        self._check_overall_calibration_insight(records)

        # 2. Decision type specific insights
        self._check_decision_type_insights(records)

        # 3. Risk level insights
        self._check_risk_insights(records)

        # 4. Context-specific insights
        self._check_context_insights(records)

        # 5. Anomaly detection
        self._check_anomalies(records)

        return len(self._insights) - insights_before

    def _check_overall_calibration_insight(self, records: List[DecisionRecord]) -> None:
        """Check for overall calibration bias."""
        if not records:
            return

        total_error = sum(
            r.confidence - (1.0 if r.actual_success else 0.0)
            for r in records if r.actual_success is not None
        )
        avg_error = total_error / len([r for r in records if r.actual_success is not None])

        if abs(avg_error) > 0.15:
            severity = "critical" if abs(avg_error) > 0.3 else "warning"
            self._add_insight(LearningInsight(
                insight_id=f"ins_{uuid.uuid4().hex[:8]}",
                insight_type="bias",
                title="Systematic Confidence Bias Detected",
                description=f"Average calibration error is {avg_error:+.2f}. System is {'overconfident' if avg_error > 0 else 'underconfident'}.",
                severity=severity,
                affected_decision_types=[r.decision_type.value for r in records],
                recommended_action=f"{'Reduce' if avg_error > 0 else 'Increase'} base confidence thresholds by {abs(avg_error)*100:.0f}%",
                confidence=min(0.9, abs(avg_error) * 2),
                evidence={"avg_error": avg_error, "sample_size": len(records)},
            ))

    def _check_decision_type_insights(self, records: List[DecisionRecord]) -> None:
        """Check for insights specific to decision types."""
        by_type = defaultdict(list)
        for r in records:
            if r.actual_success is not None:
                by_type[r.decision_type.value].append(r)

        for dtype, type_records in by_type.items():
            if len(type_records) < self.min_samples_calibration:
                continue

            success_rate = sum(1 for r in type_records if r.actual_success) / len(type_records)
            avg_confidence = sum(r.confidence for r in type_records) / len(type_records)

            # Check if confidence matches success rate
            diff = avg_confidence - success_rate
            if abs(diff) > 0.2:
                self._add_insight(LearningInsight(
                    insight_id=f"ins_{uuid.uuid4().hex[:8]}",
                    insight_type="pattern",
                    title=f"Confidence Mismatch for {dtype}",
                    description=f"Average confidence ({avg_confidence:.0%}) differs from actual success rate ({success_rate:.0%}) by {diff:+.0%}.",
                    severity="warning" if abs(diff) > 0.3 else "info",
                    affected_decision_types=[dtype],
                    recommended_action=f"{'Lower' if diff > 0 else 'Raise'} confidence estimates for {dtype} decisions",
                    confidence=min(0.9, abs(diff) * 1.5),
                    evidence={"avg_confidence": avg_confidence, "success_rate": success_rate, "sample_size": len(type_records)},
                ))

    def _check_risk_insights(self, records: List[DecisionRecord]) -> None:
        """Check for insights related to risk levels."""
        by_risk = defaultdict(list)
        for r in records:
            if r.actual_success is not None:
                by_risk[r.risk_level].append(r)

        for risk_level, risk_records in by_risk.items():
            if len(risk_records) < self.min_samples_calibration:
                continue

            success_rate = sum(1 for r in risk_records if r.actual_success) / len(risk_records)

            # High risk decisions should have lower success rates (that's expected)
            # But if they have HIGH success rates, we might be overestimating risk
            if risk_level in ("high", "critical") and success_rate > 0.8:
                self._add_insight(LearningInsight(
                    insight_id=f"ins_{uuid.uuid4().hex[:8]}",
                    insight_type="recommendation",
                    title=f"High-Risk Decisions Succeeding Frequently",
                    description=f"{risk_level.capitalize()} risk decisions have {success_rate:.0%} success rate. Risk assessment may be too conservative.",
                    severity="info",
                    affected_decision_types=list(set(r.decision_type.value for r in risk_records)),
                    recommended_action="Review risk assessment criteria; consider lowering risk thresholds for similar decisions",
                    confidence=success_rate * 0.8,
                    evidence={"risk_level": risk_level, "success_rate": success_rate, "sample_size": len(risk_records)},
                ))

    def _check_context_insights(self, records: List[DecisionRecord]) -> None:
        """Check for insights from specific context features."""
        # Check system state impact
        by_state = defaultdict(list)
        for r in records:
            if r.actual_success is not None:
                state = r.metadata.get("system_state", "normal") if r.metadata else "normal"
                by_state[state].append(r)

        for state, state_records in by_state.items():
            if len(state_records) < self.min_samples_calibration or state == "normal":
                continue

            success_rate = sum(1 for r in state_records if r.actual_success) / len(state_records)
            normal_records = by_state.get("normal", [])
            if normal_records:
                normal_rate = sum(1 for r in normal_records if r.actual_success) / len(normal_records)
                diff = normal_rate - success_rate

                if diff > 0.2:
                    self._add_insight(LearningInsight(
                        insight_id=f"ins_{uuid.uuid4().hex[:8]}",
                        insight_type="pattern",
                        title=f"Degraded Performance in {state.capitalize()} System State",
                        description=f"Success rate drops from {normal_rate:.0%} (normal) to {success_rate:.0%} ({state}).",
                        severity="warning",
                        affected_decision_types=list(set(r.decision_type.value for r in state_records)),
                        recommended_action=f"Apply confidence penalty for {state} system state; increase human oversight",
                        confidence=min(0.9, diff),
                        evidence={"system_state": state, "success_rate": success_rate, "normal_rate": normal_rate},
                    ))

    def _check_anomalies(self, records: List[DecisionRecord]) -> None:
        """Check for anomalous patterns."""
        # Find decisions with high confidence but failure
        high_conf_failures = [
            r for r in records
            if r.actual_success is False and r.confidence > 0.8
        ]

        if len(high_conf_failures) >= 3:
            types = list(set(r.decision_type.value for r in high_conf_failures))
            self._add_insight(LearningInsight(
                insight_id=f"ins_{uuid.uuid4().hex[:8]}",
                insight_type="anomaly",
                title="High Confidence Failures",
                description=f"{len(high_conf_failures)} decisions with >80% confidence resulted in failure.",
                severity="critical",
                affected_decision_types=types,
                recommended_action="Investigate root cause of high-confidence failures; review confidence model for these decision types",
                confidence=0.9,
                evidence={"count": len(high_conf_failures), "types": types},
            ))

        # Find decisions with low confidence but success
        low_conf_successes = [
            r for r in records
            if r.actual_success is True and r.confidence < 0.3
        ]

        if len(low_conf_successes) >= 5:
            types = list(set(r.decision_type.value for r in low_conf_successes))
            self._add_insight(LearningInsight(
                insight_id=f"ins_{uuid.uuid4().hex[:8]}",
                insight_type="anomaly",
                title="Low Confidence Successes",
                description=f"{len(low_conf_successes)} decisions with <30% confidence resulted in success.",
                severity="info",
                affected_decision_types=types,
                recommended_action="Confidence model may be too conservative for these decision types; review scoring factors",
                confidence=0.7,
                evidence={"count": len(low_conf_successes), "types": types},
            ))

    def _check_calibration_insight(self, context_key: str) -> None:
        """Check if a calibration warrants an insight."""
        if context_key not in self._calibrations:
            return

        cal = self._calibrations[context_key]
        if cal.sample_count >= 10 and abs(cal.calibration_error) > 0.25:
            # Check if we already have this insight
            for insight in self._insights:
                if insight.insight_type == "bias" and cal.context_key in str(insight.evidence):
                    return

            self._add_insight(LearningInsight(
                insight_id=f"ins_{uuid.uuid4().hex[:8]}",
                insight_type="bias",
                title=f"Calibration Drift: {cal.decision_type}",
                description=f"Context '{context_key}' shows {cal.calibration_error:+.2f} calibration error over {cal.sample_count} samples.",
                severity="warning" if abs(cal.calibration_error) > 0.3 else "info",
                affected_decision_types=[cal.decision_type],
                recommended_action=f"{'Reduce' if cal.calibration_error > 0 else 'Increase'} confidence for this context",
                confidence=min(0.8, abs(cal.calibration_error)),
                evidence={"context_key": context_key, "calibration_error": cal.calibration_error, "samples": cal.sample_count},
            ))

    def _get_overall_calibration(self) -> Dict[str, float]:
        """Get overall calibration statistics."""
        if not self._calibrations:
            return {"mean_error": 0.0, "overconfident_count": 0, "underconfident_count": 0}

        errors = [c.calibration_error for c in self._calibrations.values()]
        return {
            "mean_error": sum(errors) / len(errors),
            "overconfident_count": sum(1 for e in errors if e > 0.1),
            "underconfident_count": sum(1 for e in errors if e < -0.1),
            "total_contexts": len(errors),
        }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _build_context_key(self, decision_type: DecisionType, context: Dict[str, Any]) -> str:
        """Build a context key for calibration lookup."""
        features = []

        # Key contextual features
        for key in ["risk_level", "system_state", "risk_tolerance", "current_phase"]:
            if key in context:
                features.append(f"{key}={context[key]}")

        # Add complexity/impact estimates if present
        for key in ["estimated_effort", "estimated_impact", "reversible"]:
            if key in context:
                val = context[key]
                if isinstance(val, float):
                    val = f"{val:.1f}"
                features.append(f"{key}={val}")

        return f"{decision_type.value}|{('|').join(sorted(features))}"

    def _build_context_key_from_record(self, record: DecisionRecord) -> str:
        """Build context key from a decision record."""
        context = record.metadata or {}
        context.update({
            "risk_level": record.risk_level,
            "system_state": record.system_state,
        })
        return self._build_context_key_from_dict(record.decision_type.value, context)

    def _build_context_key_from_dict(self, decision_type_str: str, context: Dict[str, Any]) -> str:
        """Build context key from decision type string and context dict."""
        features = []
        for key in ["risk_level", "system_state", "risk_tolerance", "current_phase"]:
            if key in context:
                features.append(f"{key}={context[key]}")
        for key in ["estimated_effort", "estimated_impact", "reversible"]:
            if key in context:
                val = context[key]
                if isinstance(val, float):
                    val = f"{val:.1f}"
                features.append(f"{key}={val}")
        return f"{decision_type_str}|{('|').join(sorted(features))}"

    def _extract_features(self, record: DecisionRecord) -> str:
        """Extract feature string from a record."""
        features = []
        meta = record.metadata or {}

        for key in ["system_state", "risk_tolerance", "current_phase", "estimated_effort", "estimated_impact", "reversible"]:
            if key in meta:
                val = meta[key]
                if isinstance(val, float):
                    val = f"{val:.1f}"
                features.append(f"{key}={val}")

        features.append(f"risk={record.risk_level}")
        return ",".join(sorted(features))

    def _parse_feature_key(self, feature_key: str) -> Dict[str, Any]:
        """Parse feature key back into conditions dict."""
        conditions = {}
        parts = feature_key.split("|")
        if len(parts) > 1:
            for feat in parts[1].split(","):
                if "=" in feat:
                    k, v = feat.split("=", 1)
                    # Try to convert to appropriate type
                    if v.replace(".", "").isdigit():
                        v = float(v) if "." in v else int(v)
                    elif v.lower() in ("true", "false"):
                        v = v.lower() == "true"
                    conditions[k] = v
        return conditions

    def _match_pattern_conditions(self, pattern_conditions: Dict[str, Any], context: Dict[str, Any]) -> float:
        """Match pattern conditions against context, return match score 0-1."""
        if not pattern_conditions:
            return 0.5

        matches = 0
        total = len(pattern_conditions)

        for key, expected in pattern_conditions.items():
            actual = context.get(key)
            if actual == expected:
                matches += 1
            elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                # Numeric: match if within 20%
                if expected != 0 and abs(actual - expected) / abs(expected) < 0.2:
                    matches += 1

        return matches / total if total > 0 else 0

    def _calculate_adjustment(self, success_rate: float, baseline: float) -> float:
        """Calculate confidence adjustment based on success rate vs baseline."""
        diff = success_rate - baseline
        # Scale adjustment: +/- 15% max per 50% difference from baseline
        return max(-0.15, min(0.15, diff * 0.3))

    def _add_insight(self, insight: LearningInsight) -> None:
        """Add an insight if not duplicate."""
        # Check for duplicates
        for existing in self._insights:
            if (existing.insight_type == insight.inset_type and
                existing.title == insight.title):
                return
        self._insights.append(insight)
        logger.info(f"[LearningFromDecisions] Generated insight: {insight.title}")


# Convenience function
def create_learning_from_decisions(
    decision_history: DecisionHistory,
    confidence_calculator: Optional[ConfidenceCalculator] = None,
    workspace: str = ".",
) -> LearningFromDecisions:
    """Create a LearningFromDecisions instance with standard configuration."""
    return LearningFromDecisions(
        decision_history=decision_history,
        confidence_calculator=confidence_calculator,
        workspace=workspace,
    )