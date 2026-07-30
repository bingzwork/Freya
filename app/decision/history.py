"""Decision History - Persistent storage and querying for decision records.

This module provides the DecisionHistory class for storing, retrieving, and
querying decision records. It reuses the existing persistence infrastructure
(pattern from ConfidenceTracker, GoalStorage, etc.) with JSON file storage.
"""

import json
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.decision.models import DecisionRecord, DecisionType, DecisionCategory

logger = logging.getLogger(__name__)


class DecisionHistory:
    """Persistent decision history with querying capabilities.

    Stores decision records in a JSON file with atomic writes.
    Supports filtering by decision type, category, component, outcome, and time range.

    Usage:
        history = DecisionHistory(workspace=".")
        history.add_record(record)
        records = history.query(category=DecisionCategory.EXECUTION, since="2024-01-01")
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/decision_history.json",
    ):
        """
        Args:
            workspace: Root workspace directory
            storage_path: Relative path for history file within workspace
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self._lock = threading.RLock()
        self._records: Dict[str, DecisionRecord] = {}
        self._load()

    # -------------------------------------------------------------------------
    # Core persistence
    # -------------------------------------------------------------------------

    def _ensure_storage_dir(self) -> None:
        """Ensure storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Load records from disk."""
        with self._lock:
            if not self.storage_path.exists():
                return
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for record_data in data.get("records", []):
                    record = DecisionRecord.from_dict(record_data)
                    self._records[record.record_id] = record
                logger.info(f"[DecisionHistory] Loaded {len(self._records)} records from {self.storage_path}")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"[DecisionHistory] Failed to load history: {e}")

    def _save(self) -> None:
        """Save records to disk atomically."""
        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        payload = {
            "records": [r.to_dict() for r in self._records.values()],
            "metadata": {
                "count": len(self._records),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        }
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.storage_path)
        except OSError as e:
            logger.error(f"[DecisionHistory] Failed to save history: {e}")

    # -------------------------------------------------------------------------
    # Record management
    # -------------------------------------------------------------------------

    def add_record(self, record: DecisionRecord) -> DecisionRecord:
        """Add a decision record to history.

        Args:
            record: DecisionRecord to store

        Returns:
            The stored record
        """
        with self._lock:
            self._records[record.record_id] = record
            self._save()
            logger.debug(f"[DecisionHistory] Added record {record.record_id} for decision {record.decision_id}")
        return record

    def get_record(self, record_id: str) -> Optional[DecisionRecord]:
        """Get a single record by ID.

        Args:
            record_id: The record_id to retrieve

        Returns:
            DecisionRecord or None if not found
        """
        with self._lock:
            return self._records.get(record_id)

    def get_decision(self, decision_id: str) -> Optional[DecisionRecord]:
        """Get a record by decision_id (may have multiple records per decision).

        Args:
            decision_id: The decision_id to search for

        Returns:
            First matching DecisionRecord or None
        """
        with self._lock:
            for record in self._records.values():
                if record.decision_id == decision_id:
                    return record
        return None

    def update_record(self, record: DecisionRecord) -> bool:
        """Update an existing record.

        Args:
            record: DecisionRecord with updated fields

        Returns:
            True if updated, False if not found
        """
        with self._lock:
            if record.record_id not in self._records:
                return False
            self._records[record.record_id] = record
            self._save()
            return True

    def remove_record(self, record_id: str) -> bool:
        """Remove a record from history.

        Args:
            record_id: ID of record to remove

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if record_id not in self._records:
                return False
            del self._records[record_id]
            self._save()
            return True

    # -------------------------------------------------------------------------
    # Outcome recording
    # -------------------------------------------------------------------------

    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        outcome_details: str = "",
        actual_success: Optional[bool] = None,
        actual_effort: Optional[float] = None,
        actual_impact: Optional[float] = None,
        error: Optional[str] = None,
        lesson_learned: str = "",
        would_repeat: Optional[bool] = None,
    ) -> bool:
        """Record the outcome of a decision.

        This closes the decision loop: decision -> execution -> outcome.

        Args:
            decision_id: ID of the decision (DecisionResult.decision_id)
            outcome: Outcome category (success, partial, failure, aborted, skipped)
            outcome_details: Human-readable description
            actual_success: Whether the action succeeded
            actual_effort: Actual effort relative to estimate (0.0-1.0)
            actual_impact: Actual impact achieved (0.0-1.0)
            error: Error message if failed
            lesson_learned: What was learned
            would_repeat: Whether we'd make the same decision again

        Returns:
            True if record was found and updated
        """
        with self._lock:
            record = self.get_decision(decision_id)
            if not record:
                logger.warning(f"[DecisionHistory] Decision {decision_id} not found for outcome recording")
                return False

            record.mark_executed(
                outcome=outcome,
                details=outcome_details,
                error=error,
                actual_success=actual_success,
                actual_effort=actual_effort,
                actual_impact=actual_impact,
            )
            if lesson_learned or would_repeat is not None:
                record.add_learning(lesson_learned, would_repeat or False)

            self._records[record.record_id] = record
            self._save()
            logger.info(f"[DecisionHistory] Recorded outcome for {decision_id}: {outcome}")
            return True

    # -------------------------------------------------------------------------
    # Query interface
    # -------------------------------------------------------------------------

    def query(
        self,
        decision_type: Optional[Union[DecisionType, str]] = None,
        category: Optional[Union[DecisionCategory, str]] = None,
        component: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "decided_at",
        sort_desc: bool = True,
    ) -> List[DecisionRecord]:
        """Query records with filters.

        Args:
            decision_type: Filter by decision type
            category: Filter by decision category
            component: Filter by component name
            outcome: Filter by outcome (success, partial, failure, aborted, skipped)
            since: ISO timestamp - records after this time
            until: ISO timestamp - records before this time
            limit: Maximum records to return
            offset: Number of records to skip
            sort_by: Field to sort by (decided_at, executed_at, confidence, risk_level)
            sort_desc: Sort descending (newest first)

        Returns:
            List of matching DecisionRecord objects
        """
        with self._lock:
            records = list(self._records.values())

            # Apply filters
            if decision_type:
                dt = decision_type.value if isinstance(decision_type, DecisionType) else decision_type
                records = [r for r in records if r.decision_type.value == dt]

            if category:
                cat = category.value if isinstance(category, DecisionCategory) else category
                records = [r for r in records if r.category.value == cat]

            if component:
                records = [r for r in records if r.component == component]

            if outcome:
                records = [r for r in records if r.outcome == outcome]

            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                    records = [r for r in records if datetime.fromisoformat(r.decided_at.replace("Z", "+00:00")) >= since_dt]
                except ValueError:
                    logger.warning(f"[DecisionHistory] Invalid 'since' timestamp: {since}")

            if until:
                try:
                    until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
                    records = [r for r in records if datetime.fromisoformat(r.decided_at.replace("Z", "+00:00")) <= until_dt]
                except ValueError:
                    logger.warning(f"[DecisionHistory] Invalid 'until' timestamp: {until}")

            # Sort
            def sort_key(r: DecisionRecord):
                if sort_by == "decided_at":
                    return r.decided_at
                elif sort_by == "executed_at":
                    return r.executed_at or ""
                elif sort_by == "confidence":
                    return r.confidence
                elif sort_by == "risk_level":
                    risk_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
                    return risk_order.get(r.risk_level, 0)
                return r.decided_at

            records.sort(key=sort_key, reverse=sort_desc)

            # Apply pagination
            return records[offset:offset + limit]

    def query_decisions_by_type(self, decision_type: DecisionType, limit: int = 50) -> List[DecisionRecord]:
        """Convenience: query by decision type."""
        return self.query(decision_type=decision_type, limit=limit)

    def query_decisions_by_category(self, category: DecisionCategory, limit: int = 50) -> List[DecisionRecord]:
        """Convenience: query by decision category."""
        return self.query(category=category, limit=limit)

    def query_decisions_by_component(self, component: str, limit: int = 50) -> List[DecisionRecord]:
        """Convenience: query by component."""
        return self.query(component=component, limit=limit)

    def query_decisions_by_outcome(self, outcome: str, limit: int = 50) -> List[DecisionRecord]:
        """Convenience: query by outcome."""
        return self.query(outcome=outcome, limit=limit)

    def query_recent_decisions(self, hours: float = 24, limit: int = 50) -> List[DecisionRecord]:
        """Convenience: query decisions from the last N hours."""
        since = datetime.now(timezone.utc).replace(microsecond=0)
        since = since.timestamp() - hours * 3600
        since_dt = datetime.fromtimestamp(since, tz=timezone.utc).isoformat()
        return self.query(since=since_dt, limit=limit)

    def query_high_risk_decisions(self, limit: int = 50) -> List[DecisionRecord]:
        """Query decisions with high or critical risk."""
        with self._lock:
            records = [
                r for r in self._records.values()
                if r.risk_level in ("high", "critical")
            ]
            records.sort(key=lambda r: r.decided_at, reverse=True)
            return records[:limit]

    def query_low_confidence_decisions(self, limit: int = 50) -> List[DecisionRecord]:
        """Query decisions with low or critical confidence."""
        with self._lock:
            records = [
                r for r in self._records.values()
                if r.confidence_level in ("critical", "low")
            ]
            records.sort(key=lambda r: r.decided_at, reverse=True)
            return records[:limit]

    def query_pending_outcomes(self, limit: int = 50) -> List[DecisionRecord]:
        """Query decisions that don't have outcomes recorded yet."""
        with self._lock:
            records = [
                r for r in self._records.values()
                if r.outcome is None
            ]
            records.sort(key=lambda r: r.decided_at, reverse=True)
            return records[:limit]

    def query_calibrated_decisions(self, min_calibration: float = 0.0, limit: int = 50) -> List[DecisionRecord]:
        """Query decisions with calibration data."""
        with self._lock:
            records = [
                r for r in self._records.values()
                if r.confidence_calibration != 0.0 and abs(r.confidence_calibration) >= min_calibration
            ]
            records.sort(key=lambda r: abs(r.confidence_calibration), reverse=True)
            return records[:limit]

    # -------------------------------------------------------------------------
    # Analytics and summaries
    # -------------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the decision history.

        Returns:
            Dictionary with statistics and breakdowns
        """
        with self._lock:
            records = list(self._records.values())
            total = len(records)

            if total == 0:
                return {
                    "total_records": 0,
                    "by_category": {},
                    "by_type": {},
                    "by_component": {},
                    "by_outcome": {},
                    "by_confidence_level": {},
                    "by_risk_level": {},
                    "average_confidence": 0.0,
                    "calibration_stats": {},
                    "outcomes_recorded": 0,
                }

            # Breakdowns
            by_category = {}
            by_type = {}
            by_component = {}
            by_outcome = {}
            by_confidence = {}
            by_risk = {}

            calibration_values = []
            outcomes_recorded = 0

            for r in records:
                by_category[r.category.value] = by_category.get(r.category.value, 0) + 1
                by_type[r.decision_type.value] = by_type.get(r.decision_type.value, 0) + 1
                by_component[r.component] = by_component.get(r.component, 0) + 1
                by_outcome[r.outcome or "pending"] = by_outcome.get(r.outcome or "pending", 0) + 1
                by_confidence[r.confidence_level] = by_confidence.get(r.confidence_level, 0) + 1
                by_risk[r.risk_level] = by_risk.get(r.risk_level, 0) + 1

                if r.outcome is not None:
                    outcomes_recorded += 1
                if r.confidence_calibration != 0.0:
                    calibration_values.append(r.confidence_calibration)

            avg_confidence = sum(r.confidence for r in records) / total if total > 0 else 0.0

            calibration_stats = {}
            if calibration_values:
                calibration_stats = {
                    "count": len(calibration_values),
                    "mean": sum(calibration_values) / len(calibration_values),
                    "min": min(calibration_values),
                    "max": max(calibration_values),
                    # Positive = overconfident, negative = underconfident
                    "overconfident_count": sum(1 for v in calibration_values if v < 0),
                    "underconfident_count": sum(1 for v in calibration_values if v > 0),
                }

            return {
                "total_records": total,
                "by_category": by_category,
                "by_type": by_type,
                "by_component": by_component,
                "by_outcome": by_outcome,
                "by_confidence_level": by_confidence,
                "by_risk_level": by_risk,
                "average_confidence": round(avg_confidence, 3),
                "calibration_stats": calibration_stats,
                "outcomes_recorded": outcomes_recorded,
                "completion_rate": round(outcomes_recorded / total * 100, 1) if total > 0 else 0.0,
            }

    def get_calibration_report(self) -> Dict[str, Any]:
        """Get a detailed calibration report for confidence model improvement."""
        with self._lock:
            records = [r for r in self._records.values() if r.confidence_calibration != 0.0]

            if not records:
                return {"message": "No calibration data available"}

            # Group by confidence level
            by_level = {}
            for r in records:
                level = r.confidence_level
                if level not in by_level:
                    by_level[level] = {"count": 0, "calibrations": []}
                by_level[level]["count"] += 1
                by_level[level]["calibrations"].append(r.confidence_calibration)

            level_stats = {}
            for level, data in by_level.items():
                cals = data["calibrations"]
                level_stats[level] = {
                    "count": len(cals),
                    "mean_calibration": sum(cals) / len(cals),
                    "accuracy": 1.0 - abs(sum(cals) / len(cals)),
                }

            # Overall
            all_cals = [r.confidence_calibration for r in records]
            overall_mean = sum(all_cals) / len(all_cals)

            return {
                "total_calibrated": len(records),
                "overall_bias": overall_mean,  # Positive = underconfident, negative = overconfident
                "by_confidence_level": level_stats,
                "recommendations": self._generate_calibration_recommendations(overall_mean),
            }

    def _generate_calibration_recommendations(self, overall_bias: float) -> List[str]:
        """Generate recommendations based on calibration analysis."""
        recs = []
        if overall_bias < -0.1:
            recs.append("System is overconfident - consider increasing risk penalties and success thresholds")
        elif overall_bias > 0.1:
            recs.append("System is underconfident - consider reducing risk penalties, trust successful patterns more")
        else:
            recs.append("Confidence calibration is well-balanced")
        return recs

    # -------------------------------------------------------------------------
    # Export and maintenance
    # -------------------------------------------------------------------------

    def export_json(self, path: Optional[str] = None) -> str:
        """Export all records to JSON file.

        Args:
            path: Optional output path (defaults to workspace/decision_export.json)

        Returns:
            Path of exported file
        """
        if path is None:
            path = str(self.workspace / "decision_export.json")

        with self._lock:
            data = {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "records": [r.to_dict() for r in self._records.values()],
                "summary": self.get_summary(),
            }

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"[DecisionHistory] Exported {len(self._records)} records to {output_path}")
        return str(output_path)

    def clear(self) -> int:
        """Clear all records. Returns count of removed records."""
        with self._lock:
            count = len(self._records)
            self._records.clear()
            self._save()
            logger.warning(f"[DecisionHistory] Cleared {count} records")
            return count

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, record_id: str) -> bool:
        return record_id in self._records


# -------------------------------------------------------------------------
# Convenience functions
# -------------------------------------------------------------------------

_global_history: Optional[DecisionHistory] = None


def get_decision_history(workspace: str = ".") -> DecisionHistory:
    """Get or create the global DecisionHistory instance."""
    global _global_history
    if _global_history is None:
        _global_history = DecisionHistory(workspace)
    return _global_history