"""Confidence Calibration for Knowledge Retrieval.

This module provides statistical calibration methods to improve the reliability
of confidence scores from knowledge sources, enabling better downstream decisions.
"""

import json
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


class CalibrationMethod(Enum):
    """Available calibration methods."""
    NONE = "none"
    ISOTONIC = "isotonic"
    PLATT = "platt"
    BETA = "beta"
    TEMPERATURE = "temperature"


class CalibrationData:
    """Stores calibration data for a specific source or global calibration."""

    def __init__(self):
        self.predictions: List[float] = []  # Predicted probabilities
        self.outcomes: List[bool] = []      # Actual correctness (True/False)
        self.source_type: Optional[str] = None
        self.updated_at: str = datetime.now(timezone.utc).isoformat()

    def add_observation(self, predicted: float, actual: bool) -> None:
        """Add a calibration observation."""
        self.predictions.append(max(0.0, min(1.0, predicted)))
        self.outcomes.append(actual)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def has_data(self) -> bool:
        return len(self.predictions) >= 10  # Minimum for meaningful calibration

    def to_dict(self) -> Dict[str, Any]:
        return {
            "predictions": self.predictions,
            "outcomes": self.outcomes,
            "source_type": self.source_type,
            "updated_at": self.updated_at,
            "sample_count": len(self.predictions),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationData":
        obj = cls()
        obj.predictions = data.get("predictions", [])
        obj.outcomes = data.get("outcomes", [])
        obj.source_type = data.get("source_type")
        obj.updated_at = data.get("updated_at", datetime.now(timezone.utc).isoformat())
        return obj


class Calibrator(ABC):
    """Abstract base class for confidence calibrators."""

    @abstractmethod
    def calibrate(self, confidence: float, source_type: Optional[str] = None) -> float:
        """Calibrate a raw confidence score."""
        pass

    @abstractmethod
    def update(self, predicted: float, actual: bool, source_type: Optional[str] = None) -> None:
        """Update calibrator with new observation."""
        pass

    @abstractmethod
    def get_metadata(self, confidence: float) -> Dict[str, Any]:
        """Get calibration metadata for a prediction."""
        pass


class IsotonicCalibrator(Calibrator):
    """Isotonic regression calibration (non-parametric, monotonic).

    Maps predicted probabilities to calibrated probabilities while preserving
    the order. Works well with sufficient data.
    """

    def __init__(self, min_samples: int = 20):
        self.min_samples = min_samples
        self._data: Dict[str, CalibrationData] = defaultdict(CalibrationData)
        self._global_data = CalibrationData()
        self._models: Dict[str, List[Tuple[float, float]]] = {}  # source -> [(x, y)]
        self._global_model: List[Tuple[float, float]] = []
        self._lock = threading.RLock()

    def calibrate(self, confidence: float, source_type: Optional[str] = None) -> float:
        """Calibrate using isotonic regression."""
        with self._lock:
            # Try source-specific model first
            if source_type and source_type in self._models and self._models[source_type]:
                return self._interpolate(confidence, self._models[source_type])

            # Fall back to global model
            if self._global_model:
                return self._interpolate(confidence, self._global_model)

            # No model yet - return raw confidence
            return confidence

    def update(self, predicted: float, actual: bool, source_type: Optional[str] = None) -> None:
        """Update calibration data."""
        with self._lock:
            predicted = max(0.0, min(1.0, predicted))

            # Update global data
            self._global_data.add_observation(predicted, actual)

            # Update source-specific data
            if source_type:
                self._data[source_type].add_observation(predicted, actual)

            # Rebuild models if enough data
            if len(self._global_data.predictions) >= self.min_samples:
                self._rebuild_global_model()

            if source_type and self._data[source_type].has_data():
                self._rebuild_source_model(source_type)

    def get_metadata(self, confidence: float) -> Dict[str, Any]:
        return {
            "method": "isotonic",
            "global_samples": len(self._global_data.predictions),
            "source_samples": len(self._data.get(confidence, CalibrationData()).predictions) if confidence in self._data else 0,
        }

    def _interpolate(self, x: float, model: List[Tuple[float, float]]) -> float:
        """Piecewise linear interpolation on isotonic model."""
        if not model:
            return x

        # Find surrounding points
        for i, (xi, yi) in enumerate(model):
            if x <= xi:
                if i == 0:
                    return yi
                # Linear interpolation between previous and current
                x0, y0 = model[i - 1]
                if xi == x0:
                    return yi
                t = (x - x0) / (xi - x0)
                return y0 + t * (yi - y0)

        # Beyond last point
        return model[-1][1]

    def _rebuild_global_model(self) -> None:
        """Rebuild global isotonic model using Pool Adjacent Violators Algorithm (PAVA)."""
        self._global_model = self._pava(self._global_data.predictions, self._global_data.outcomes)

    def _rebuild_source_model(self, source_type: str) -> None:
        """Rebuild source-specific isotonic model."""
        data = self._data[source_type]
        self._models[source_type] = self._pava(data.predictions, data.outcomes)

    def _pava(self, predictions: List[float], outcomes: List[bool]) -> List[Tuple[float, float]]:
        """Pool Adjacent Violators Algorithm for isotonic regression.

        Returns list of (x, y) points where y is the calibrated probability.
        """
        if not predictions:
            return []

        # Bin predictions into intervals
        n_bins = min(20, len(predictions) // 10 + 1)
        bins = [(i / n_bins, (i + 1) / n_bins) for i in range(n_bins)]

        # For each bin, compute average prediction and actual rate
        bin_data = []
        for low, high in bins:
            bin_preds = []
            bin_outcomes = []
            for p, o in zip(predictions, outcomes):
                if low <= p < high or (high == 1.0 and p == 1.0):
                    bin_preds.append(p)
                    bin_outcomes.append(1.0 if o else 0.0)

            if bin_preds:
                avg_pred = sum(bin_preds) / len(bin_preds)
                avg_outcome = sum(bin_outcomes) / len(bin_outcomes)
                bin_data.append((avg_pred, avg_outcome))

        if not bin_data:
            return []

        # Sort by predicted probability
        bin_data.sort(key=lambda x: x[0])

        # PAVA: ensure monotonicity
        # Start with each point as its own block
        blocks = [(x, y, 1) for x, y in bin_data]  # (avg_x, avg_y, weight)

        while True:
            violations = False
            new_blocks = []
            i = 0
            while i < len(blocks):
                if i + 1 < len(blocks) and blocks[i][1] > blocks[i + 1][1]:
                    # Violation: merge blocks
                    x1, y1, w1 = blocks[i]
                    x2, y2, w2 = blocks[i + 1]
                    merged_x = (x1 * w1 + x2 * w2) / (w1 + w2)
                    merged_y = (y1 * w1 + y2 * w2) / (w1 + w2)
                    new_blocks.append((merged_x, merged_y, w1 + w2))
                    i += 2
                    violations = True
                else:
                    new_blocks.append(blocks[i])
                    i += 1
            blocks = new_blocks
            if not violations:
                break

        # Return as (x, y) points
        return [(b[0], b[1]) for b in blocks]

    def save(self, path: Path) -> None:
        """Save calibration data to disk."""
        with self._lock:
            data = {
                "global": self._global_data.to_dict(),
                "sources": {k: v.to_dict() for k, v in self._data.items()},
                "method": "isotonic",
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

    def load(self, path: Path) -> bool:
        """Load calibration data from disk."""
        try:
            with open(path, "r") as f:
                data = json.load(f)

            with self._lock:
                self._global_data = CalibrationData.from_dict(data.get("global", {}))
                for k, v in data.get("sources", {}).items():
                    self._data[k] = CalibrationData.from_dict(v)

                # Rebuild models
                if self._global_data.has_data():
                    self._rebuild_global_model()
                for k, v in self._data.items():
                    if v.has_data():
                        self._rebuild_source_model(k)

            return True
        except Exception as e:
            logger.warning(f"Failed to load calibration data: {e}")
            return False


class PlattCalibrator(Calibrator):
    """Platt scaling calibration (sigmoid/Logistic regression).

    Fits P(y=1|x) = 1 / (1 + exp(A*x + B)) to calibration data.
    Works well with smaller datasets.
    """

    def __init__(self, min_samples: int = 10, learning_rate: float = 0.01, max_iter: int = 100):
        self.min_samples = min_samples
        self.learning_rate = learning_rate
        self.max_iter = max_iter
        self._A: Optional[float] = None
        self._B: Optional[float] = None
        self._data: Dict[str, CalibrationData] = defaultdict(CalibrationData)
        self._global_data = CalibrationData()
        self._params: Dict[str, Tuple[float, float]] = {}  # source -> (A, B)
        self._global_params: Tuple[float, float] = (0.0, 0.0)
        self._lock = threading.RLock()

    def calibrate(self, confidence: float, source_type: Optional[str] = None) -> float:
        with self._lock:
            confidence = max(0.0, min(1.0, confidence))

            # Use source-specific params if available
            if source_type and source_type in self._params:
                A, B = self._params[source_type]
            else:
                A, B = self._global_params

            # Platt scaling: 1 / (1 + exp(A * confidence + B))
            logit = A * confidence + B
            return 1.0 / (1.0 + math.exp(-logit))

    def update(self, predicted: float, actual: bool, source_type: Optional[str] = None) -> None:
        with self._lock:
            predicted = max(0.0, min(1.0, predicted))
            self._global_data.add_observation(predicted, actual)

            if source_type:
                self._data[source_type].add_observation(predicted, actual)

            # Refit if enough new data
            if len(self._global_data.predictions) >= self.min_samples:
                self._fit_global()

            if source_type and self._data[source_type].has_data():
                self._fit_source(source_type)

    def get_metadata(self, confidence: float) -> Dict[str, Any]:
        return {
            "method": "platt",
            "global_samples": len(self._global_data.predictions),
            "params_A": self._global_params[0],
            "params_B": self._global_params[1],
        }

    def _fit_global(self) -> None:
        self._global_params = self._fit_logistic(self._global_data)

    def _fit_source(self, source_type: str) -> None:
        self._params[source_type] = self._fit_logistic(self._data[source_type])

    def _fit_logistic(self, data: CalibrationData) -> Tuple[float, float]:
        """Fit logistic regression: logit(p) = A*x + B using gradient descent."""
        X = data.predictions
        y = [1.0 if o else 0.0 for o in data.outcomes]

        if len(X) < self.min_samples:
            return 0.0, 0.0

        # Initial parameters (no calibration)
        A = 0.0
        B = 0.0

        for _ in range(self.max_iter):
            dA = 0.0
            dB = 0.0
            for xi, yi in zip(X, y):
                p = 1.0 / (1.0 + math.exp(-(A * xi + B)))
                error = p - yi
                dA += error * xi
                dB += error

            if abs(dA) < 1e-6 and abs(dB) < 1e-6:
                break

            A -= self.learning_rate * dA
            B -= self.learning_rate * dB

        return A, B

    def save(self, path: Path) -> None:
        with self._lock:
            data = {
                "global": self._global_data.to_dict(),
                "sources": {k: v.to_dict() for k, v in self._data.items()},
                "method": "platt",
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

    def load(self, path: Path) -> bool:
        try:
            with open(path, "r") as f:
                data = json.load(f)

            with self._lock:
                self._global_data = CalibrationData.from_dict(data.get("global", {}))
                for k, v in data.get("sources", {}).items():
                    self._data[k] = CalibrationData.from_dict(v)

                if self._global_data.has_data():
                    self._fit_global()
                for k, v in self._data.items():
                    if v.has_data():
                        self._fit_source(k)

            return True
        except Exception as e:
            logger.warning(f"Failed to load Platt calibration: {e}")
            return False


class BetaCalibrator(Calibrator):
    """Beta calibration (generalized Platt scaling).

    Uses Beta distribution parameters for more flexible calibration curves.
    """

    def __init__(self, min_samples: int = 15):
        self.min_samples = min_samples
        self._data: Dict[str, CalibrationData] = defaultdict(CalibrationData)
        self._global_data = CalibrationData()
        self._params: Dict[str, Tuple[float, float, float]] = {}  # source -> (a, b, c)
        self._global_params: Tuple[float, float, float] = (1.0, 1.0, 1.0)
        self._lock = threading.RLock()

    def calibrate(self, confidence: float, source_type: Optional[str] = None) -> float:
        with self._lock:
            confidence = max(0.0, min(1.0, confidence))

            if source_type and source_type in self._params:
                a, b, c = self._params[source_type]
            else:
                a, b, c = self._global_params

            # Beta calibration: p_calibrated = c * x^a / (c * x^a + (1-x)^b)
            # Simplified: use sigmoid with temperature
            logit = a * math.log(max(confidence, 1e-6)) + b
            p = 1.0 / (1.0 + math.exp(-logit))
            return c * p

    def update(self, predicted: float, actual: bool, source_type: Optional[str] = None) -> None:
        with self._lock:
            predicted = max(0.0, min(1.0, predicted))
            self._global_data.add_observation(predicted, actual)
            if source_type:
                self._data[source_type].add_observation(predicted, actual)

            if len(self._global_data.predictions) >= self.min_samples:
                self._fit_global()
            if source_type and self._data[source_type].has_data():
                self._fit_source(source_type)

    def get_metadata(self, confidence: float) -> Dict[str, Any]:
        return {
            "method": "beta",
            "global_samples": len(self._global_data.predictions),
            "params": self._global_params,
        }

    def _fit_global(self) -> None:
        self._global_params = self._fit_beta(self._global_data)

    def _fit_source(self, source_type: str) -> None:
        self._params[source_type] = self._fit_beta(self._data[source_type])

    def _fit_beta(self, data: CalibrationData) -> Tuple[float, float, float]:
        """Simple beta calibration fit using method of moments."""
        if len(data.predictions) < self.min_samples:
            return 1.0, 1.0, 1.0

        X = data.predictions
        y = [1.0 if o else 0.0 for o in data.outcomes]

        mean_x = sum(X) / len(X)
        mean_y = sum(y) / len(y)

        # Simple temperature scaling as fallback
        num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(X, y))
        den = sum((xi - mean_x) ** 2 for xi in X)

        if den == 0:
            return 1.0, 0.0, 1.0

        a = num / den
        b = mean_y - a * mean_x
        c = 1.0

        return max(0.1, a), b, c

    def save(self, path: Path) -> None:
        with self._lock:
            data = {
                "global": self._global_data.to_dict(),
                "sources": {k: v.to_dict() for k, v in self._data.items()},
                "method": "beta",
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

    def load(self, path: Path) -> bool:
        try:
            with open(path, "r") as f:
                data = json.load(f)

            with self._lock:
                self._global_data = CalibrationData.from_dict(data.get("global", {}))
                for k, v in data.get("sources", {}).items():
                    self._data[k] = CalibrationData.from_dict(v)

                if self._global_data.has_data():
                    self._fit_global()
                for k, v in self._data.items():
                    if v.has_data():
                        self._fit_source(k)

            return True
        except Exception as e:
            logger.warning(f"Failed to load Beta calibration: {e}")
            return False


class TemperatureCalibrator(Calibrator):
    """Temperature scaling calibration (single parameter).

    Simplest calibration: p_calibrated = sigmoid(logit(p) / T)
    where T is the temperature parameter.
    """

    def __init__(self, min_samples: int = 10):
        self.min_samples = min_samples
        self._data: Dict[str, CalibrationData] = defaultdict(CalibrationData)
        self._global_data = CalibrationData()
        self._temperatures: Dict[str, float] = {}
        self._global_temperature = 1.0
        self._lock = threading.RLock()

    def calibrate(self, confidence: float, source_type: Optional[str] = None) -> float:
        with self._lock:
            confidence = max(1e-6, min(1.0 - 1e-6, confidence))

            if source_type and source_type in self._temperatures:
                T = self._temperatures[source_type]
            else:
                T = self._global_temperature

            # Temperature scaling
            logit = math.log(confidence / (1.0 - confidence))
            calibrated_logit = logit / T
            return 1.0 / (1.0 + math.exp(-calibrated_logit))

    def update(self, predicted: float, actual: bool, source_type: Optional[str] = None) -> None:
        with self._lock:
            predicted = max(1e-6, min(1.0 - 1e-6, predicted))
            self._global_data.add_observation(predicted, actual)
            if source_type:
                self._data[source_type].add_observation(predicted, actual)

            if len(self._global_data.predictions) >= self.min_samples:
                self._fit_global()
            if source_type and self._data[source_type].has_data():
                self._fit_source(source_type)

    def get_metadata(self, confidence: float) -> Dict[str, Any]:
        return {
            "method": "temperature",
            "global_samples": len(self._global_data.predictions),
            "global_temperature": self._global_temperature,
        }

    def _fit_global(self) -> None:
        self._global_temperature = self._fit_temperature(self._global_data)

    def _fit_source(self, source_type: str) -> None:
        self._temperatures[source_type] = self._fit_temperature(self._data[source_type])

    def _fit_temperature(self, data: CalibrationData) -> float:
        """Find temperature via gradient descent on NLL."""
        X = data.predictions
        y = [1.0 if o else 0.0 for o in data.outcomes]

        if len(X) < self.min_samples:
            return 1.0

        T = 1.0
        lr = 0.01

        for _ in range(100):
            dT = 0.0
            for xi, yi in zip(X, y):
                logit = math.log(xi / (1.0 - xi))
                p = 1.0 / (1.0 + math.exp(-logit / T))
                dT += (p - yi) * logit / (T * T)

            if abs(dT) < 1e-6:
                break

            T -= lr * dT
            T = max(0.1, min(10.0, T))  # Clamp temperature

        return T

    def save(self, path: Path) -> None:
        with self._lock:
            data = {
                "global": self._global_data.to_dict(),
                "sources": {k: v.to_dict() for k, v in self._data.items()},
                "method": "temperature",
                "temperatures": self._temperatures,
                "global_temperature": self._global_temperature,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

    def load(self, path: Path) -> bool:
        try:
            with open(path, "r") as f:
                data = json.load(f)

            with self._lock:
                self._global_data = CalibrationData.from_dict(data.get("global", {}))
                for k, v in data.get("sources", {}).items():
                    self._data[k] = CalibrationData.from_dict(v)
                self._temperatures = data.get("temperatures", {})
                self._global_temperature = data.get("global_temperature", 1.0)

            return True
        except Exception as e:
            logger.warning(f"Failed to load Temperature calibration: {e}")
            return False


class CalibrationManager:
    """Manages calibration for the retrieval system."""

    def __init__(
        self,
        method: str = "isotonic",
        storage_path: Optional[Path] = None,
        min_samples: int = 20,
    ):
        self.method = method
        self.storage_path = storage_path or Path("data/knowledge_retrieval/calibration.json")
        self.calibrator = self._create_calibrator(method, min_samples)
        self._enabled = True

        # Load existing calibration data
        if self.storage_path.exists():
            self.calibrator.load(self.storage_path)

    def _create_calibrator(self, method: str, min_samples: int) -> Calibrator:
        method = method.lower()
        if method == "isotonic":
            return IsotonicCalibrator(min_samples=min_samples)
        elif method == "platt":
            return PlattCalibrator(min_samples=min_samples)
        elif method == "beta":
            return BetaCalibrator(min_samples=min_samples)
        elif method == "temperature":
            return TemperatureCalibrator(min_samples=min_samples)
        else:
            logger.warning(f"Unknown calibration method: {method}, using none")
            return NoOpCalibrator()

    def calibrate(self, confidence: float, source_type: Optional[str] = None) -> float:
        """Calibrate a confidence score."""
        if not self._enabled:
            return confidence
        return self.calibrator.calibrate(confidence, source_type)

    def update(self, predicted: float, actual: bool, source_type: Optional[str] = None) -> None:
        """Update calibrator with observed outcome."""
        if not self._enabled:
            return
        self.calibrator.update(predicted, actual, source_type)

    def get_calibration_metadata(
        self,
        confidence: float,
        source_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get metadata about calibration applied."""
        metadata = self.calibrator.get_metadata(confidence)
        metadata["source_type"] = source_type
        metadata["original_confidence"] = confidence
        metadata["calibrated_confidence"] = self.calibrate(confidence, source_type)
        return metadata

    def save(self) -> None:
        """Persist calibration data."""
        self.calibrator.save(self.storage_path)

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False


class NoOpCalibrator(Calibrator):
    """No-op calibrator for when calibration is disabled."""

    def calibrate(self, confidence: float, source_type: Optional[str] = None) -> float:
        return confidence

    def update(self, predicted: float, actual: bool, source_type: Optional[str] = None) -> None:
        pass

    def get_metadata(self, confidence: float) -> Dict[str, Any]:
        return {"method": "none", "calibrated": confidence}


# Import for type hints
from enum import Enum