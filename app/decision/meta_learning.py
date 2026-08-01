"""Meta-Decision Learning - Learn when to trust/subvert own confidence estimates.

This module implements the Meta-Decision Learning capability (Phase 2+ enhancement):
- Learns patterns in when confidence estimates are reliable vs unreliable
- Identifies systematic biases in decision-making
- Provides meta-confidence: confidence in the confidence estimates
- Adapts decision thresholds based on learned reliability
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
from app.confidence.confidence_scoring import ConfidenceCalculator, ConfidenceEvent, ConfidenceEventType

logger = logging.getLogger(__name__)


@dataclass
class MetaConfidenceRule:
    """A learned rule about when to trust/subvert confidence."""
    rule_id: str
    name: str
    description: str
    conditions: Dict[str, Any]  # Context conditions where this applies
    confidence_reliability: float  # How reliable confidence is in this context (0-1)
    direction: str  # "trust", "subvert_up", "subvert_down"
    adjustment_factor: float  # Multiply confidence by this factor
    sample_count: int
    confidence: float  # Confidence in this rule
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_validated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def applies_to(self, context: Dict[str, Any], threshold: float = 0.6) -> bool:
        """Check if rule applies to given context."""
        matches = 0
        total = len(self.conditions)
        for key, expected in self.conditions.items():
            actual = context.get(key)
            if actual == expected:
                matches += 1
            elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                if expected != 0 and abs(actual - expected) / abs(expected) < 0.15:
                    matches += 1
        return (matches / total if total > 0 else 0) >= threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "conditions": self.conditions,
            "confidence_reliability": self.confidence_reliability,
            "direction": self.direction,
            "adjustment_factor": self.adjustment_factor,
            "sample_count": self.sample_count,
            "confidence": self.confidence,
            "discovered_at": self.discovered_at,
            "last_validated": self.last_validated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaConfidenceRule":
        return cls(**data)


@dataclass
class BiasProfile:
    """A profile of systematic bias in decision-making."""
    bias_id: str
    bias_type: str  # "overconfidence", "underconfidence", "risk_aversion", "risk_seeking", "recency", "anchoring"
    description: str
    affected_contexts: List[Dict[str, Any]]
    magnitude: float  # How strong the bias is (0-1)
    direction: str  # "positive", "negative"
    evidence_count: int
    confidence: float
    mitigation_suggestions: List[str] = field(default_factory=list)
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bias_id": self.bias_id,
            "bias_type": self.bias_type,
            "description": self.description,
            "affected_contexts": self.affected_contexts,
            "magnitude": self.magnitude,
            "direction": self.direction,
            "evidence_count": self.evidence_count,
            "confidence": self.confidence,
            "mitigation_suggestions": self.mitigation_suggestions,
            "detected_at": self.detected_at,
        }


@dataclass
class MetaDecisionEvent:
    """An event in meta-decision learning."""
    event_id: str
    timestamp: str
    event_type: str  # "rule_discovered", "bias_detected", "threshold_adjusted", "validation"
    description: str
    context: Dict[str, Any]
    impact: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "description": self.description,
            "context": self.context,
            "impact": self.impact,
        }


class MetaDecisionLearning:
    """Learns when to trust or subvert confidence estimates.

    This class provides the Meta-Decision Learning capability:
    1. Analyzes confidence calibration across contexts
    2. Discovers systematic biases in decision-making
    3. Learns context-dependent reliability rules
    4. Adjusts decision thresholds dynamically
    5. Provides meta-confidence estimates
    """

    def __init__(
        self,
        decision_history: DecisionHistory,
        learning_from_decisions=None,  # Optional: integrate with learning module
        confidence_calculator: Optional[ConfidenceCalculator] = None,
        workspace: str = ".",
        min_samples_for_rule: int = 10,
        min_samples_for_bias: int = 20,
    ):
        """Initialize the meta-decision learning engine.

        Args:
            decision_history: DecisionHistory with outcome records
            learning_from_decisions: Optional LearningFromDecisions instance
            confidence_calculator: Optional ConfidenceCalculator to adjust
            workspace: Workspace path for persistence
            min_samples_for_rule: Minimum samples to create a rule
            min_samples_for_bias: Minimum samples to detect bias
        """
        self.decision_history = decision_history
        self.learning_from_decisions = learning_from_decisions
        self.confidence_calculator = confidence_calculator or ConfidenceCalculator()
        self.workspace = Path(workspace).resolve()
        self.min_samples_rule = min_samples_for_rule
        self.min_samples_bias = min_samples_for_bias

        self._lock = threading.RLock()
        self._rules: Dict[str, MetaConfidenceRule] = {}
        self._biases: Dict[str, BiasProfile] = {}
        self._events: List[MetaDecisionEvent] = []
        self._storage_path = self.workspace / "data" / "meta_decision_learning.json"

        # Default decision thresholds (can be adjusted)
        self._decision_thresholds = {
            "accept_confidence": 0.70,
            "reject_confidence": 0.30,
            "human_approval_risk": "high",
            "human_approval_confidence": 0.50,
        }

        self._load()

    def _load(self) -> None:
        """Load meta-learning data from disk."""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for r in data.get("rules", []):
                rule = MetaConfidenceRule.from_dict(r)
                self._rules[rule.rule_id] = rule

            for b in data.get("biases", []):
                bias = BiasProfile(**b)
                self._biases[bias.bias_id] = bias

            for e in data.get("events", []):
                self._events.append(MetaDecisionEvent(**e))

            self._decision_thresholds.update(data.get("thresholds", {}))

            logger.info(f"[MetaDecisionLearning] Loaded {len(self._rules)} rules, {len(self._biases)} biases")
        except Exception as e:
            logger.warning(f"[MetaDecisionLearning] Failed to load meta-learning data: {e}")

    def _save(self) -> None:
        """Save meta-learning data to disk."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(".tmp")
        try:
            data = {
                "rules": [r.to_dict() for r in self._rules.values()],
                "biases": [b.to_dict() for b in self._biases.values()],
                "events": [e.to_dict() for e in self._events],
                "thresholds": self._decision_thresholds,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self._storage_path)
        except Exception as e:
            logger.error(f"[MetaDecisionLearning] Failed to save meta-learning data: {e}")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def analyze(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Run meta-decision analysis to discover rules and biases.

        Args:
            force_refresh: If True, re-analyze all records

        Returns:
            Analysis summary
        """
        with self._lock:
            records = self._get_records_with_outcomes()

            if len(records) < self.min_samples_rule:
                return {
                    "message": "Insufficient data for meta-analysis",
                    "records": len(records),
                    "rules_discovered": 0,
                    "biases_detected": 0,
                }

            rules_before = len(self._rules)
            biases_before = len(self._biases)

            # 1. Discover confidence reliability rules
            self._discover_reliability_rules(records)

            # 2. Detect systematic biases
            self._detect_biases(records)

            # 3. Adjust decision thresholds based on findings
            self._adjust_thresholds()

            # 4. Validate existing rules
            self._validate_rules(records)

            # Save
            self._save()

            return {
                "records_analyzed": len(records),
                "rules_discovered": len(self._rules) - rules_before,
                "rules_total": len(self._rules),
                "biases_detected": len(self._biases) - biases_before,
                "biases_total": len(self._biases),
                "thresholds": self._decision_thresholds.copy(),
            }

    def get_meta_confidence(
        self,
        decision_type: DecisionType,
        predicted_confidence: float,
        context: Dict[str, Any],
    ) -> Tuple[float, float, str]:
        """Get meta-confidence (confidence in the confidence estimate).

        Args:
            decision_type: Type of decision
            predicted_confidence: The confidence estimate to evaluate
            context: Decision context

        Returns:
            Tuple of (meta_confidence, adjusted_confidence, explanation)
            meta_confidence: How reliable the confidence estimate is (0-1)
            adjusted_confidence: The confidence adjusted by learned rules
            explanation: Human-readable explanation
        """
        with self._lock:
            # Build evaluation context
            eval_context = self._build_eval_context(decision_type, predicted_confidence, context)

            # Find applicable rules
            applicable_rules = [r for r in self._rules.values() if r.applies_to(eval_context)]

            if not applicable_rules:
                return 0.5, predicted_confidence, "No learned rules apply; using default meta-confidence"

            # Select best rule (highest confidence * sample_count)
            best_rule = max(applicable_rules, key=lambda r: r.confidence * min(r.sample_count, 100) / 100)

            # Apply rule
            adjusted = predicted_confidence * best_rule.adjustment_factor
            adjusted = max(0.0, min(1.0, adjusted))  # Clamp

            meta_confidence = best_rule.confidence_reliability * best_rule.confidence

            direction_text = {
                "trust": "trust",
                "subvert_up": "increase",
                "subvert_down": "decrease",
            }.get(best_rule.direction, "adjust")

            explanation = (
                f"Rule '{best_rule.name}': {direction_text} confidence by "
                f"{(best_rule.adjustment_factor - 1) * 100:+.0f}% "
                f"(reliability: {best_rule.confidence_reliability:.0%}, "
                f"based on {best_rule.sample_count} samples)"
            )

            return meta_confidence, adjusted, explanation

    def get_decision_thresholds(self) -> Dict[str, Any]:
        """Get current adaptive decision thresholds."""
        with self._lock:
            return self._decision_thresholds.copy()

    def get_rules(self) -> List[MetaConfidenceRule]:
        """Get all learned reliability rules."""
        with self._lock:
            return sorted(self._rules.values(), key=lambda r: (r.confidence * r.sample_count), reverse=True)

    def get_biases(self) -> List[BiasProfile]:
        """Get all detected biases."""
        with self._lock:
            return sorted(self._biases.values(), key=lambda b: b.magnitude * b.confidence, reverse=True)

    def get_events(self, limit: int = 50) -> List[MetaDecisionEvent]:
        """Get recent meta-decision events."""
        with self._lock:
            return self._events[-limit:]

    def should_require_human_approval(
        self,
        decision_type: DecisionType,
        risk_level: str,
        confidence: float,
        context: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Determine if human approval should be required (with meta-learning)."""
        with self._lock:
            # Base thresholds
            risk_threshold = self._decision_thresholds.get("human_approval_risk", "high")
            conf_threshold = self._decision_thresholds.get("human_approval_confidence", 0.50)

            # Get meta-confidence adjustment
            meta_conf, adjusted_conf, explanation = self.get_meta_confidence(
                decision_type, confidence, context
            )

            # Check risk level
            risk_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
            requires_approval = risk_order.get(risk_level, 0) >= risk_order.get(risk_threshold, 3)

            # Check confidence
            if adjusted_conf < conf_threshold:
                requires_approval = True

            # Meta-confidence: if we're uncertain about our confidence, require approval
            if meta_conf < 0.4:
                requires_approval = True

            reason = []
            if risk_order.get(risk_level, 0) >= risk_order.get(risk_threshold, 3):
                reason.append(f"risk level {risk_level} >= threshold {risk_threshold}")
            if adjusted_conf < conf_threshold:
                reason.append(f"adjusted confidence {adjusted_conf:.0%} < threshold {conf_threshold:.0%}")
            if meta_conf < 0.4:
                reason.append(f"low meta-confidence ({meta_conf:.0%})")

            return requires_approval, "; ".join(reason) if reason else "No approval required"

    # -------------------------------------------------------------------------
    # Internal Analysis Methods
    # -------------------------------------------------------------------------

    def _get_records_with_outcomes(self) -> List[DecisionRecord]:
        """Get all decision records that have outcomes recorded."""
        all_records = list(self.decision_history._records.values())
        return [r for r in all_records if r.actual_success is not None and r.confidence > 0]

    def _discover_reliability_rules(self, records: List[DecisionRecord]) -> None:
        """Discover rules about when confidence is reliable."""
        # Group records by context features
        groups = defaultdict(list)

        for record in records:
            features = self._extract_reliability_features(record)
            groups[features].append(record)

        for feature_key, group_records in groups.items():
            if len(group_records) < self.min_samples_rule:
                continue

            # Calculate calibration accuracy in this context
            errors = [abs(r.confidence - (1.0 if r.actual_success else 0.0)) for r in group_records]
            mean_error = sum(errors) / len(errors)
            reliability = 1.0 - mean_error  # High reliability = low error

            # Calculate variance in errors (consistency)
            variance = sum((e - mean_error) ** 2 for e in errors) / len(errors) if len(errors) > 1 else 0
            consistency = 1.0 - min(1.0, variance * 10)  # Penalize high variance

            overall_reliability = (reliability * 0.7 + consistency * 0.3)

            # Determine direction
            avg_confidence = sum(r.confidence for r in group_records) / len(group_records)
            success_rate = sum(1 for r in group_records if r.actual_success) / len(group_records)

            if avg_confidence > success_rate + 0.1:
                direction = "subvert_down"
                adjustment = success_rate / avg_confidence if avg_confidence > 0 else 1.0
            elif avg_confidence + 0.1 < success_rate:
                direction = "subvert_up"
                adjustment = success_rate / avg_confidence if avg_confidence > 0 else 1.0
            else:
                direction = "trust"
                adjustment = 1.0

            adjustment = max(0.5, min(1.5, adjustment))

            # Only create rule if meaningful
            if overall_reliability > 0.5 and len(group_records) >= self.min_samples_rule:
                conditions = self._parse_feature_key(feature_key)
                conditions["decision_type"] = group_records[0].decision_type.value

                rule_id = f"rule_{uuid.uuid4().hex[:8]}"
                rule = MetaConfidenceRule(
                    rule_id=rule_id,
                    name=f"Confidence {direction.replace('_', ' ')} for {conditions.get('risk_level', 'medium')} risk {conditions.get('decision_type', 'decisions')}",
                    description=f"In this context, confidence is {overall_reliability:.0%} reliable. "
                               f"Avg confidence {avg_confidence:.0%} vs success rate {success_rate:.0%}.",
                    conditions=conditions,
                    confidence_reliability=overall_reliability,
                    direction=direction,
                    adjustment_factor=adjustment,
                    sample_count=len(group_records),
                    confidence=min(0.9, overall_reliability * 0.8 + min(len(group_records) / 50, 0.2)),
                )

                # Check if similar rule exists
                existing = self._find_similar_rule(rule)
                if existing:
                    # Merge/update existing
                    existing.sample_count += len(group_records)
                    existing.confidence_reliability = (
                        existing.confidence_reliability * (existing.sample_count - len(group_records)) + overall_reliability * len(group_records)
                    ) / existing.sample_count
                    existing.adjustment_factor = (existing.adjustment_factor + adjustment) / 2
                    existing.last_validated = datetime.now(timezone.utc).isoformat()
                    existing.confidence = min(0.95, existing.confidence + 0.05)
                else:
                    self._rules[rule_id] = rule
                    self._add_event(MetaDecisionEvent(
                        event_id=f"evt_{uuid.uuid4().hex[:8]}",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        event_type="rule_discovered",
                        description=f"Discovered rule: {rule.name}",
                        context=conditions,
                        impact={"reliability": overall_reliability, "adjustment": adjustment, "samples": len(group_records)},
                    ))

    def _detect_biases(self, records: List[DecisionRecord]) -> None:
        """Detect systematic biases in decision-making."""
        # 1. Overall over/under confidence
        self._detect_calibration_bias(records)

        # 2. Risk-level specific biases
        self._detect_risk_bias(records)

        # 3. Decision-type specific biases
        self._decide_type_bias(records)

        # 4. Temporal biases (recency)
        self._detect_temporal_bias(records)

        # 5. Anchoring bias (first decision influences later)
        self._detect_anchoring_bias(records)

    def _detect_calibration_bias(self, records: List[DecisionRecord]) -> None:
        """Detect overall calibration bias."""
        errors = [r.confidence - (1.0 if r.actual_success else 0.0) for r in records]
        mean_error = sum(errors) / len(errors)

        if abs(mean_error) > 0.1 and len(records) >= self.min_samples_bias:
            bias_type = "overconfidence" if mean_error > 0 else "underconfidence"
            bias_id = f"bias_calibration_{bias_type}"

            if bias_id not in self._biases:
                self._biases[bias_id] = BiasProfile(
                    bias_id=bias_id,
                    bias_type=bias_type,
                    description=f"Systematic {bias_type}: average calibration error is {mean_error:+.2f}",
                    affected_contexts=[{"all": True}],
                    magnitude=min(1.0, abs(mean_error) * 2),
                    direction="positive" if mean_error > 0 else "negative",
                    evidence_count=len(records),
                    confidence=min(0.9, abs(mean_error) * 3),
                    mitigation_suggestions=[
                        f"{'Decrease' if mean_error > 0 else 'Increase'} base confidence by {abs(mean_error)*100:.0f}%",
                        "Review confidence scoring factors",
                        "Add calibration step to decision workflow",
                    ],
                )
                self._add_event(MetaDecisionEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="bias_detected",
                    description=f"Detected {bias_type}: {mean_error:+.2f} mean error",
                    context={"bias_type": bias_type},
                    impact={"mean_error": mean_error, "samples": len(records)},
                ))

    def _detect_risk_bias(self, records: List[DecisionRecord]) -> None:
        """Detect bias in risk level assessment."""
        by_risk = defaultdict(list)
        for r in records:
            by_risk[r.risk_level].append(r)

        for risk_level, risk_records in by_risk.items():
            if len(risk_records) < self.min_samples_bias:
                continue

            success_rate = sum(1 for r in risk_records if r.actual_success) / len(risk_records)
            avg_confidence = sum(r.confidence for r in risk_records) / len(risk_records)

            # Expected: higher risk -> lower success rate
            # Bias: if high risk has HIGH success rate, we're overestimating risk (risk aversion)
            #       if low risk has LOW success rate, we're underestimating risk (risk seeking)
            expected_rates = {"critical": 0.3, "high": 0.5, "medium": 0.7, "low": 0.85, "info": 0.9}

            expected = expected_rates.get(risk_level, 0.5)
            diff = success_rate - expected

            if abs(diff) > 0.2 and len(risk_records) >= self.min_samples_bias:
                if risk_level in ("critical", "high") and diff > 0:
                    bias_type = "risk_aversion"
                    bias_id = f"bias_risk_aversion_{risk_level}"
                elif risk_level in ("low", "info") and diff < 0:
                    bias_type = "risk_seeking"
                    bias_id = f"bias_risk_seeking_{risk_level}"
                else:
                    continue

                if bias_id not in self._biases:
                    self._biases[bias_id] = BiasProfile(
                        bias_id=bias_id,
                        bias_type=bias_type,
                        description=f"{bias_type.replace('_', ' ').title()} for {risk_level} risk: "
                                   f"expected {expected:.0%} success, got {success_rate:.0%}",
                        affected_contexts=[{"risk_level": risk_level}],
                        magnitude=min(1.0, abs(diff) * 2),
                        direction="positive" if diff > 0 else "negative",
                        evidence_count=len(risk_records),
                        confidence=min(0.85, abs(diff) * 2.5),
                        mitigation_suggestions=[
                            f"Revise risk assessment criteria for {risk_level} decisions",
                            "Add explicit risk calibration step",
                            "Review historical outcomes for similar risk levels",
                        ],
                    )
                    self._add_event(MetaDecisionEvent(
                        event_id=f"evt_{uuid.uuid4().hex[:8]}",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        event_type="bias_detected",
                        description=f"Detected {bias_type} for {risk_level} risk",
                        context={"risk_level": risk_level, "bias_type": bias_type},
                        impact={"expected_rate": expected, "actual_rate": success_rate, "diff": diff},
                    ))

    def _decide_type_bias(self, records: List[DecisionRecord]) -> None:
        """Detect bias in specific decision types."""
        by_type = defaultdict(list)
        for r in records:
            by_type[r.decision_type.value].append(r)

        for dtype, type_records in by_type.items():
            if len(type_records) < self.min_samples_bias:
                continue

            success_rate = sum(1 for r in type_records if r.actual_success) / len(type_records)
            avg_confidence = sum(r.confidence for r in type_records) / len(type_records)
            diff = avg_confidence - success_rate

            if abs(diff) > 0.15:
                bias_type = "overconfidence" if diff > 0 else "underconfidence"
                bias_id = f"bias_{dtype}_{bias_type}"

                if bias_id not in self._biases:
                    self._biases[bias_id] = BiasProfile(
                        bias_id=bias_id,
                        bias_type=bias_type,
                        description=f"{dtype} decisions: {bias_type} ({diff:+.0%} gap)",
                        affected_contexts=[{"decision_type": dtype}],
                        magnitude=min(1.0, abs(diff) * 3),
                        direction="positive" if diff > 0 else "negative",
                        evidence_count=len(type_records),
                        confidence=min(0.85, abs(diff) * 3),
                        mitigation_suggestions=[
                            f"Adjust confidence scoring for {dtype} decisions",
                            f"Add {dtype}-specific calibration factors",
                        ],
                    )

    def _detect_temporal_bias(self, records: List[DecisionRecord]) -> None:
        """Detect recency bias (recent outcomes weighted too heavily)."""
        # This would require tracking confidence changes over time
        # Simplified: check if later decisions have systematically different calibration
        sorted_records = sorted(records, key=lambda r: r.timestamp)
        mid = len(sorted_records) // 2

        first_half = sorted_records[:mid]
        second_half = sorted_records[mid:]

        if len(first_half) < 10 or len(second_half) < 10:
            return

        first_error = sum(r.confidence - (1.0 if r.actual_success else 0.0) for r in first_half) / len(first_half)
        second_error = sum(r.confidence - (1.0 if r.actual_success else 0.0) for r in second_half) / len(second_half)

        if abs(first_error - second_error) > 0.15:
            bias_id = "bias_temporal_recalibration"
            if bias_id not in self._biases:
                self._biases[bias_id] = BiasProfile(
                    bias_id=bias_id,
                    bias_type="recency",
                    description=f"Calibration drift over time: early error {first_error:+.2f}, late error {second_error:+.2f}",
                    affected_contexts=[{"temporal": True}],
                    magnitude=abs(first_error - second_error),
                    direction="drift",
                    evidence_count=len(records),
                    confidence=0.7,
                    mitigation_suggestions=[
                        "Implement periodic recalibration",
                        "Weight recent outcomes appropriately",
                    ],
                )

    def _detect_anchoring_bias(self, records: List[DecisionRecord]) -> None:
        """Detect anchoring bias (first decision influences subsequent)."""
        # Group by plan_id to check sequential decisions
        by_plan = defaultdict(list)
        for r in records:
            plan_id = r.metadata.get("plan_id") if r.metadata else None
            if plan_id:
                by_plan[plan_id].append(r)

        anchor_diffs = []
        for plan_id, plan_records in by_plan.items():
            if len(plan_records) < 3:
                continue
            plan_records.sort(key=lambda r: r.timestamp)
            first_conf = plan_records[0].confidence
            for r in plan_records[1:]:
                anchor_diffs.append(abs(r.confidence - first_conf))

        if anchor_diffs:
            avg_anchor_diff = sum(anchor_diffs) / len(anchor_diffs)
            if avg_anchor_diff < 0.15 and len(anchor_diffs) >= 10:
                bias_id = "bias_anchoring"
                if bias_id not in self._biases:
                    self._biases[bias_id] = BiasProfile(
                        bias_id=bias_id,
                        bias_type="anchoring",
                        description=f"Subsequent decisions anchor to first decision confidence (avg diff: {avg_anchor_diff:.2f})",
                        affected_contexts=[{"sequential": True}],
                        magnitude=1.0 - avg_anchor_diff,
                        direction="anchor",
                        evidence_count=len(anchor_diffs),
                        confidence=min(0.8, 1.0 - avg_anchor_diff),
                        mitigation_suggestions=[
                            "Encourage independent confidence assessment for each decision",
                            "Add 'reset' prompt between sequential decisions",
                        ],
                    )

    def _adjust_thresholds(self) -> None:
        """Adjust decision thresholds based on learned biases."""
        # Adjust human approval confidence threshold based on overconfidence bias
        overconfidence_biases = [b for b in self._biases.values() if b.bias_type == "overconfidence" and b.confidence > 0.7]

        if overconfidence_biases:
            max_magnitude = max(b.magnitude for b in overconfidence_biases)
            # Increase threshold (require higher confidence) if overconfident
            adjustment = max_magnitude * 0.1  # Up to 10% increase
            self._decision_thresholds["human_approval_confidence"] = min(
                0.8, self._decision_thresholds.get("human_approval_confidence", 0.5) + adjustment
            )
            self._add_event(MetaDecisionEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="threshold_adjusted",
                description=f"Increased human approval confidence threshold due to overconfidence bias",
                context={"adjustment": adjustment, "biases": len(overconfidence_biases)},
                impact={"new_threshold": self._decision_thresholds["human_approval_confidence"]},
            ))

        # Adjust based on risk aversion bias
        risk_aversion_biases = [b for b in self._biases.values() if b.bias_type == "risk_aversion" and b.confidence > 0.7]

        if risk_aversion_biases:
            # Lower risk threshold for approval (we're too conservative)
            current = self._decision_thresholds.get("human_approval_risk", "high")
            risk_order = ["info", "low", "medium", "high", "critical"]
            if current in risk_order and risk_order.index(current) > 1:
                new_idx = risk_order.index(current) - 1
                self._decision_thresholds["human_approval_risk"] = risk_order[new_idx]
                self._add_event(MetaDecisionEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="threshold_adjusted",
                    description=f"Lowered human approval risk threshold due to risk aversion bias",
                    context={"old": current, "new": self._decision_thresholds["human_approval_risk"]},
                    impact={},
                ))

    def _validate_rules(self, records: List[DecisionRecord]) -> None:
        """Validate existing rules against new data."""
        for rule in list(self._rules.values()):
            # Find records matching this rule
            matching = [r for r in records if rule.applies_to(self._extract_reliability_features(r))]

            if len(matching) >= 5:
                # Recalculate reliability
                errors = [abs(r.confidence - (1.0 if r.actual_success else 0.0)) for r in matching]
                new_reliability = 1.0 - (sum(errors) / len(errors))

                # Update rule
                old_reliability = rule.confidence_reliability
                rule.confidence_reliability = (rule.confidence_reliability * rule.sample_count + new_reliability * len(matching)) / (rule.sample_count + len(matching))
                rule.sample_count += len(matching)
                rule.last_validated = datetime.now(timezone.utc).isoformat()
                rule.confidence = min(0.95, rule.confidence + 0.02)

                # If reliability dropped significantly, log it
                if old_reliability - rule.confidence_reliability > 0.2:
                    self._add_event(MetaDecisionEvent(
                        event_id=f"evt_{uuid.uuid4().hex[:8]}",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        event_type="validation",
                        description=f"Rule '{rule.name}' reliability decreased from {old_reliability:.0%} to {rule.confidence_reliability:.0%}",
                        context={"rule_id": rule.rule_id},
                        impact={"old_reliability": old_reliability, "new_reliability": rule.confidence_reliability},
                    ))

            # Remove rules with very low confidence
            if rule.confidence < 0.3 and rule.sample_count > 20:
                del self._rules[rule.rule_id]
                self._add_event(MetaDecisionEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="validation",
                    description=f"Removed low-confidence rule: {rule.name}",
                    context={"rule_id": rule.rule_id},
                    impact={},
                ))

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _extract_reliability_features(self, record: DecisionRecord) -> str:
        """Extract features for reliability analysis."""
        features = []
        meta = record.metadata or {}

        # Key features affecting confidence reliability
        for key in ["risk_level", "system_state", "risk_tolerance", "current_phase"]:
            if key == "risk_level":
                features.append(f"risk={record.risk_level}")
            elif key in meta:
                features.append(f"{key}={meta[key]}")

        # Confidence bins
        conf_bin = int(record.confidence * 10) / 10
        features.append(f"conf_bin={conf_bin:.1f}")

        # Decision type
        features.append(f"type={record.decision_type.value}")

        return "|".join(sorted(features))

    def _parse_feature_key(self, feature_key: str) -> Dict[str, Any]:
        """Parse feature key into conditions dict."""
        conditions = {}
        for feat in feature_key.split("|"):
            if "=" in feat:
                k, v = feat.split("=", 1)
                if v.replace(".", "").isdigit():
                    v = float(v) if "." in v else int(v)
                conditions[k] = v
        return conditions

    def _build_eval_context(
        self,
        decision_type: DecisionType,
        predicted_confidence: float,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build evaluation context for rule matching."""
        eval_context = dict(context)
        eval_context["decision_type"] = decision_type.value
        eval_context["conf_bin"] = round(predicted_confidence, 1)
        return eval_context

    def _find_similar_rule(self, new_rule: MetaConfidenceRule) -> Optional[MetaConfidenceRule]:
        """Find existing rule similar to new rule."""
        for rule in self._rules.values():
            if rule.direction != new_rule.direction:
                continue
            # Check condition overlap
            common_keys = set(rule.conditions.keys()) & set(new_rule.conditions.keys())
            if len(common_keys) >= 2:
                matches = sum(1 for k in common_keys if rule.conditions[k] == new_rule.conditions[k])
                if matches / len(common_keys) >= 0.8:
                    return rule
        return None

    def _add_event(self, event: MetaDecisionEvent) -> None:
        """Add a meta-decision event."""
        self._events.append(event)
        # Keep only last 500 events
        if len(self._events) > 500:
            self._events = self._events[-500:]


# Convenience function
def create_meta_decision_learning(
    decision_history: DecisionHistory,
    learning_from_decisions=None,
    confidence_calculator: Optional[ConfidenceCalculator] = None,
    workspace: str = ".",
) -> MetaDecisionLearning:
    """Create a MetaDecisionLearning instance with standard configuration."""
    return MetaDecisionLearning(
        decision_history=decision_history,
        learning_from_decisions=learning_from_decisions,
        confidence_calculator=confidence_calculator,
        workspace=workspace,
    )