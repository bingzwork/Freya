"""Deterministic, non-mutating simulation capability.

The simulation layer predicts outcomes from an explicit scenario.  It never
executes the proposed action, never mutates the simulated state, and never
acts as an approval or verification mechanism.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from uuid import uuid4

from app.orchestrator.capabilities import BaseCapability
from app.orchestrator.capability_registry import CapabilityCategory, CapabilityMetadata


class SimulationType(str, Enum):
    SYSTEM = "system"
    WORKFLOW = "workflow"
    RESOURCE = "resource"
    FINANCIAL = "financial"
    PROJECT = "project"
    DECISION = "decision"
    AGENT_ACTION = "agent_action"


class AssumptionKind(str, Enum):
    KNOWN_FACT = "known_fact"
    SUPPLIED_VALUE = "supplied_value"
    INFERRED = "inferred"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Assumption:
    name: str
    value: Any
    kind: AssumptionKind
    source: str = ""
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "kind": self.kind.value, "source": self.source, "rationale": self.rationale}


@dataclass(frozen=True)
class Scenario:
    simulation_type: SimulationType
    objective: str
    current_state: Mapping[str, Any] = field(default_factory=dict)
    proposed_change: Mapping[str, Any] = field(default_factory=dict)
    assumptions: Sequence[Assumption] = field(default_factory=tuple)
    constraints: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    variables: Mapping[str, Any] = field(default_factory=dict)
    alternatives: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    time_horizon: Any = None
    requested_outputs: Sequence[str] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "simulation_type": self.simulation_type.value,
            "objective": self.objective,
            "current_state": dict(self.current_state),
            "proposed_change": dict(self.proposed_change),
            "assumptions": [a.to_dict() for a in self.assumptions],
            "constraints": [dict(c) for c in self.constraints],
            "variables": dict(self.variables),
            "alternatives": [dict(a) for a in self.alternatives],
            "time_horizon": self.time_horizon,
            "requested_outputs": list(self.requested_outputs),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class SimulationResult:
    """A hypothetical prediction; it is not execution or verification evidence."""

    simulation_id: str
    simulation_type: SimulationType
    scenario: Scenario
    assumptions: Sequence[Assumption]
    inputs: Mapping[str, Any]
    predicted_outcomes: Mapping[str, Any]
    affected_components: Sequence[str]
    constraints: Mapping[str, Any]
    risks: Sequence[Mapping[str, Any]]
    uncertainties: Sequence[str]
    alternatives: Sequence[Mapping[str, Any]]
    recommendation: Optional[str]
    confidence: str
    evidence: Sequence[Mapping[str, Any]]
    created_at: str
    result_kind: str = "PREDICTED"
    hypothetical: bool = True
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "simulation_type": self.simulation_type.value,
            "scenario": self.scenario.to_dict(),
            "assumptions": [a.to_dict() for a in self.assumptions],
            "inputs": dict(self.inputs),
            "predicted_outcomes": dict(self.predicted_outcomes),
            "affected_components": list(self.affected_components),
            "constraints": dict(self.constraints),
            "risks": [dict(r) for r in self.risks],
            "uncertainties": list(self.uncertainties),
            "alternatives": [dict(a) for a in self.alternatives],
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "evidence": [dict(e) for e in self.evidence],
            "created_at": self.created_at,
            "result_kind": self.result_kind,
            "hypothetical": self.hypothetical,
            "verified": self.verified,
        }


class ScenarioBuilder:
    """Convert caller input into a validated, explicit scenario."""

    def build(self, inputs: Mapping[str, Any], query: str = "") -> Scenario:
        raw_type = inputs.get("simulation_type") or inputs.get("type") or self._infer_type(query)
        try:
            normalized_type = str(raw_type).strip().lower().replace("-", "_").replace(" ", "_")
            simulation_type = raw_type if isinstance(raw_type, SimulationType) else SimulationType(normalized_type)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unsupported simulation type: {raw_type}") from exc

        objective = str(inputs.get("objective") or query or "").strip()
        if not objective:
            raise ValueError("A simulation objective is required")

        current_state = inputs.get("current_state", {})
        proposed_change = inputs.get("proposed_change", inputs.get("action", {}))
        if not isinstance(current_state, Mapping) or not isinstance(proposed_change, Mapping):
            raise ValueError("current_state and proposed_change must be objects")

        assumptions = AssumptionManager().normalize(inputs.get("assumptions", []), inputs)
        alternatives = inputs.get("alternatives", [])
        if not isinstance(alternatives, Sequence) or isinstance(alternatives, (str, bytes)):
            raise ValueError("alternatives must be a list of objects")
        alternatives = tuple(a if isinstance(a, Mapping) else {"value": a} for a in alternatives)
        constraints = inputs.get("constraints", [])
        if isinstance(constraints, Mapping):
            constraints = [constraints]
        if not isinstance(constraints, Sequence) or isinstance(constraints, (str, bytes)):
            raise ValueError("constraints must be a list of objects")

        return Scenario(
            simulation_type=simulation_type,
            objective=objective,
            current_state=dict(current_state),
            proposed_change=dict(proposed_change),
            assumptions=tuple(assumptions),
            constraints=tuple(c if isinstance(c, Mapping) else {"expression": str(c)} for c in constraints),
            variables=dict(inputs.get("variables", {}) or {}),
            alternatives=alternatives,
            time_horizon=inputs.get("time_horizon", inputs.get("horizon")),
            requested_outputs=tuple(inputs.get("requested_outputs", []) or []),
            provenance=dict(inputs.get("provenance", {}) or {}),
        )

    @staticmethod
    def _infer_type(query: str) -> str:
        text = query.lower()
        if any(word in text for word in ("budget", "revenue", "margin", "cash flow", "break-even")):
            return SimulationType.FINANCIAL.value
        if any(word in text for word in ("ram", "vram", "cpu", "storage", "throughput", "resource")):
            return SimulationType.RESOURCE.value
        if any(word in text for word in ("task", "milestone", "launch date", "staffing", "project")):
            return SimulationType.PROJECT.value
        if any(word in text for word in ("option", "alternatives", "tradeoff", "compare")):
            return SimulationType.DECISION.value
        if any(word in text for word in ("workflow", "automation", "every hour", "schedule")):
            return SimulationType.WORKFLOW.value
        if any(word in text for word in ("component", "goes down", "dependency", "system")):
            return SimulationType.SYSTEM.value
        return SimulationType.AGENT_ACTION.value


class AssumptionManager:
    """Preserve the distinction between facts, inputs, estimates, and unknowns."""

    def normalize(self, raw: Any, inputs: Mapping[str, Any]) -> List[Assumption]:
        assumptions: List[Assumption] = []
        if isinstance(raw, Mapping):
            raw = [{"name": key, "value": value, "kind": AssumptionKind.SUPPLIED_VALUE.value} for key, value in raw.items()]
        if raw is None:
            raw = []
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("assumptions must be an object or list")
        for item in raw:
            if isinstance(item, str):
                assumptions.append(Assumption(item, True, AssumptionKind.INFERRED, source="scenario", rationale="Explicitly stated assumption"))
                continue
            if not isinstance(item, Mapping) or not item.get("name"):
                raise ValueError("each assumption needs a name")
            try:
                kind = AssumptionKind(str(item.get("kind", AssumptionKind.SUPPLIED_VALUE.value)).lower())
            except ValueError as exc:
                raise ValueError(f"unsupported assumption kind: {item.get('kind')}") from exc
            assumptions.append(Assumption(str(item["name"]), item.get("value"), kind, str(item.get("source", "user")), str(item.get("rationale", ""))))
        return assumptions


@dataclass(frozen=True)
class StateModel:
    """Immutable typed wrapper for the relevant state projection."""

    simulation_type: SimulationType
    state: Mapping[str, Any]

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> "StateModel":
        return cls(scenario.simulation_type, scenario.current_state)


class ConstraintEngine:
    """Perform deterministic constraint checks without an LLM."""

    def check(self, scenario: Scenario, outcomes: Mapping[str, Any]) -> Dict[str, Any]:
        violations: List[Dict[str, Any]] = []
        checked: List[Dict[str, Any]] = []
        for constraint in scenario.constraints:
            checked.append(dict(constraint))
            kind = str(constraint.get("type", "")).lower()
            if kind in {"max", "maximum", "upper_bound"}:
                actual = _metric_value(outcomes, constraint.get("resource", constraint.get("metric")))
                limit = _number(constraint.get("value", constraint.get("max")))
                if limit is not None and actual is not None and actual > limit:
                    violations.append({"constraint": dict(constraint), "actual": actual, "limit": limit, "reason": "maximum exceeded"})
            elif kind in {"min", "minimum", "lower_bound"}:
                actual = _metric_value(outcomes, constraint.get("resource", constraint.get("metric")))
                limit = _number(constraint.get("value", constraint.get("min")))
                if limit is not None and actual is not None and actual < limit:
                    violations.append({"constraint": dict(constraint), "actual": actual, "limit": limit, "reason": "minimum not met"})
            elif kind in {"before", "dependency"}:
                order = outcomes.get("task_order", [])
                before, after = constraint.get("before"), constraint.get("after")
                if before in order and after in order and order.index(before) > order.index(after):
                    violations.append({"constraint": dict(constraint), "reason": "dependency order violated"})
            elif kind == "forbid":
                if constraint.get("action") == scenario.proposed_change.get("action"):
                    violations.append({"constraint": dict(constraint), "reason": "action forbidden by policy"})
            elif kind:
                violations.append({"constraint": dict(constraint), "reason": "unsupported constraint cannot be evaluated"})
        return {"satisfied": not violations, "checked": checked, "violations": violations}


class SimulationRunner:
    """Run deterministic projections for all supported simulation domains."""

    def run(self, scenario: Scenario) -> Dict[str, Any]:
        runners = {
            SimulationType.SYSTEM: self._system,
            SimulationType.WORKFLOW: self._workflow,
            SimulationType.RESOURCE: self._resource,
            SimulationType.FINANCIAL: self._financial,
            SimulationType.PROJECT: self._project,
            SimulationType.DECISION: self._decision,
            SimulationType.AGENT_ACTION: self._agent_action,
        }
        return runners[scenario.simulation_type](scenario)

    def _system(self, scenario: Scenario) -> Dict[str, Any]:
        state = scenario.current_state
        components = state.get("components", {})
        dependencies = state.get("dependencies", {})
        target = scenario.proposed_change.get("component") or scenario.proposed_change.get("target") or scenario.variables.get("component")
        known = isinstance(components, Mapping) and (not components or target in components)
        if not target:
            return {"unknown": ["target component"], "affected_components": [], "failure_propagation": "undetermined"}
        direct = list(dependencies.get(target, [])) if isinstance(dependencies, Mapping) else []
        downstream = _reverse_reachable(dependencies, target) if isinstance(dependencies, Mapping) else []
        if not known and target not in dependencies:
            return {"target": target, "direct_dependencies": [], "downstream_dependencies": [], "affected_components": [], "unknown": [f"relationships for {target}"], "failure_propagation": "unknown"}
        affected = list(dict.fromkeys([target, *direct, *downstream]))
        return {"target": target, "direct_dependencies": direct, "downstream_dependencies": downstream, "affected_components": affected, "degraded_functionality": state.get("services", {}).get(target, []) if isinstance(state.get("services", {}), Mapping) else [], "failure_propagation": "contained" if not downstream else "propagates", "recovery": scenario.proposed_change.get("rollback", state.get("rollback", "unknown"))}

    def _workflow(self, scenario: Scenario) -> Dict[str, Any]:
        values = {**scenario.current_state, **scenario.proposed_change, **scenario.variables}
        interval = _number(values.get("interval_minutes"))
        duration = _number(values.get("expected_duration_minutes", values.get("duration_minutes")))
        horizon_hours = _number(values.get("horizon_hours", values.get("time_horizon_hours", 24))) or 24.0
        frequency = values.get("frequency", values.get("schedule", "unspecified"))
        runs = max(1, math.floor(horizon_hours * 60 / interval)) if interval and interval > 0 else None
        overlap = bool(interval and duration and duration > interval)
        return {"schedule": frequency, "interval_minutes": interval, "expected_duration_minutes": duration, "horizon_hours": horizon_hours, "estimated_runs": runs, "overlap": overlap, "contention": "likely" if overlap else "not indicated", "resource_use": values.get("resource_use", {}), "dependent_services": values.get("dependent_services", []), "rate_limit_risk": values.get("rate_limit", values.get("rate_limit_per_hour"))}

    def _resource(self, scenario: Scenario) -> Dict[str, Any]:
        current = scenario.current_state.get("resources", scenario.current_state)
        planned = scenario.proposed_change.get("resources", scenario.proposed_change.get("planned", scenario.variables.get("planned", {})))
        result: Dict[str, Any] = {}
        oversubscribed: List[str] = []
        for resource in ("cpu", "ram", "vram", "storage", "throughput", "concurrency"):
            cur = _resource_entry(current, resource)
            add = _resource_entry(planned, resource)
            used = (cur.get("used", 0) if cur else 0) + (add.get("used", add.get("requested", add.get("total", 0))) if add else 0)
            capacity = (cur.get("capacity") if cur else None) or (add.get("capacity") if add else None)
            headroom = capacity - used if capacity is not None else None
            entry = {"current": cur.get("used", 0) if cur else 0, "planned_additional": add.get("used", add.get("requested", add.get("total", 0))) if add else 0, "estimated_total": used, "capacity": capacity, "headroom": headroom, "oversubscribed": bool(capacity is not None and used > capacity)}
            result[resource] = entry
            if entry["oversubscribed"]:
                oversubscribed.append(resource)
        return {"resources": result, "oversubscribed": oversubscribed, "likely_offloading": bool("vram" in oversubscribed), "risk_level": "HIGH" if oversubscribed else "LOW"}

    def _financial(self, scenario: Scenario) -> Dict[str, Any]:
        values = {**scenario.current_state, **scenario.proposed_change, **scenario.variables}
        starting_cash = _number(values.get("starting_cash", values.get("cash", 0))) or 0.0
        revenue = _number(values.get("revenue", values.get("price", 0))) or 0.0
        units = _number(values.get("units", values.get("volume", 1))) or 0.0
        price = _number(values.get("price", values.get("pricing", 0)))
        if price is not None and "revenue" not in values:
            revenue = price * units
        fixed = _number(values.get("fixed_costs", values.get("fixed_cost", 0))) or 0.0
        variable_per_unit = _number(values.get("variable_cost_per_unit", values.get("variable_cost", 0))) or 0.0
        variable = variable_per_unit * units if "variable_costs" not in values else (_number(values.get("variable_costs")) or 0.0)
        expenses = fixed + variable
        net = revenue - expenses
        periods = int(_number(values.get("forecast_period", values.get("periods", 1))) or 1)
        cumulative = starting_cash + net * periods
        break_even_units = math.ceil(fixed / (price - variable_per_unit)) if price is not None and price > variable_per_unit and fixed > 0 else None
        return {"starting_cash": starting_cash, "revenue": revenue, "fixed_costs": fixed, "variable_costs": variable, "expenses": expenses, "net_cash_flow": net, "forecast_periods": periods, "ending_cash": cumulative, "runway_periods": (starting_cash / abs(net)) if net < 0 else None, "break_even_units": break_even_units, "margin": (net / revenue) if revenue else None, "inputs_are_forecasts": True}

    def _project(self, scenario: Scenario) -> Dict[str, Any]:
        values = {**scenario.current_state, **scenario.proposed_change, **scenario.variables}
        raw_tasks = values.get("tasks", [])
        tasks = {str(t.get("id", t.get("name"))): t for t in raw_tasks if isinstance(t, Mapping) and (t.get("id") or t.get("name"))}
        delay_target = values.get("delay_task") or values.get("task") or values.get("target")
        delay = _number(values.get("delay_days", values.get("delay", 0))) or 0.0
        memo: Dict[str, float] = {}
        visiting: set[str] = set()
        def finish(task_id: str) -> float:
            if task_id in memo:
                return memo[task_id]
            if task_id in visiting:
                raise ValueError(f"cyclic project dependency involving {task_id}")
            task = tasks.get(task_id)
            if not task:
                return 0.0
            visiting.add(task_id)
            predecessors = task.get("dependencies", task.get("depends_on", [])) or []
            start = max((finish(str(dep)) for dep in predecessors), default=0.0)
            value = start + (_number(task.get("duration_days", task.get("duration", 0))) or 0.0)
            if str(task_id) == str(delay_target):
                value += delay
            visiting.remove(task_id)
            memo[task_id] = value
            return value
        for task_id in tasks:
            finish(task_id)
        baseline = max(((_number(t.get("duration_days", t.get("duration", 0))) or 0.0) for t in tasks.values()), default=0.0)
        project_finish = max(memo.values(), default=0.0)
        return {"task_finish_days": memo, "project_finish_days": project_finish, "estimated_schedule_slippage_days": max(0.0, project_finish - baseline) if delay_target else 0.0, "delayed_task": delay_target, "delay_days": delay, "capacity": values.get("capacity", values.get("staffing", "unknown")), "task_order": sorted(memo, key=memo.get)}

    def _decision(self, scenario: Scenario) -> Dict[str, Any]:
        alternatives = list(scenario.alternatives)
        if not alternatives:
            alternatives = list(scenario.proposed_change.get("alternatives", []))
        rows: List[Dict[str, Any]] = []
        for index, option in enumerate(alternatives):
            name = str(option.get("name", option.get("id", f"option_{index + 1}")))
            score = _number(option.get("score"))
            if score is None:
                metrics = option.get("metrics", {}) if isinstance(option.get("metrics", {}), Mapping) else {}
                score = _number(metrics.get("score"))
            rows.append({"name": name, "score": score, "metrics": dict(option.get("metrics", {})) if isinstance(option.get("metrics", {}), Mapping) else {}, "tradeoffs": option.get("tradeoffs", []), "risks": option.get("risks", [])})
        usable = [row for row in rows if row["score"] is not None]
        recommendation = None
        if usable:
            usable.sort(key=lambda row: row["score"], reverse=True)
            if len(usable) == 1 or usable[0]["score"] > usable[1]["score"]:
                recommendation = usable[0]["name"]
        return {"alternatives": rows, "comparable_scores": bool(usable), "recommendation": recommendation, "evidence_quality": "inconclusive" if recommendation is None else "based on supplied scores"}

    def _agent_action(self, scenario: Scenario) -> Dict[str, Any]:
        action = scenario.proposed_change
        actions = action.get("actions", scenario.variables.get("planned_actions", []))
        if not actions:
            actions = [action] if action else []
        affected = list(dict.fromkeys(str(x) for x in action.get("affected_components", scenario.variables.get("affected_components", []))))
        resources = action.get("resource_requirements", scenario.variables.get("resource_requirements", {}))
        mutations = [a for a in actions if isinstance(a, Mapping) and (a.get("mutating") or a.get("mutation_level") in {"medium", "high"})]
        rollback = action.get("rollback_available", scenario.variables.get("rollback_available", "unknown"))
        return {"planned_actions": [dict(a) if isinstance(a, Mapping) else {"action": a} for a in actions], "action_count": len(actions), "mutating_action_count": len(mutations), "affected_components": affected, "resource_requirements": resources, "rollback_available": rollback, "expected_outputs": action.get("expected_outputs", []), "possible_failure_points": action.get("possible_failure_points", []), "would_execute_real_action": False}


class OutcomeComparator:
    """Compare deterministic alternative outcomes without manufacturing certainty."""

    def compare(self, outcomes: Mapping[str, Any], alternatives: Sequence[Mapping[str, Any]]) -> tuple[List[Mapping[str, Any]], Optional[str]]:
        if outcomes.get("alternatives"):
            rows = list(outcomes["alternatives"])
            recommendation = outcomes.get("recommendation")
            return rows, recommendation
        return list(alternatives), None


class RiskAnalyzer:
    """Produce qualitative risk and uncertainty signals."""

    def analyze(self, scenario: Scenario, outcomes: Mapping[str, Any], constraints: Mapping[str, Any]) -> tuple[List[Mapping[str, Any]], List[str], str]:
        risks: List[Mapping[str, Any]] = []
        uncertainties: List[str] = []
        if constraints.get("violations"):
            risks.append({"risk": "constraint_violation", "severity": "HIGH", "confidence": "HIGH", "reason": "One or more deterministic constraints were violated"})
        if outcomes.get("oversubscribed"):
            risks.append({"risk": "resource_oversubscription", "severity": "HIGH", "confidence": "HIGH", "resources": outcomes["oversubscribed"]})
        if outcomes.get("overlap"):
            risks.append({"risk": "workflow_overlap", "severity": "MEDIUM", "confidence": "MEDIUM", "reason": "Expected duration exceeds schedule interval"})
        if outcomes.get("failure_propagation") == "propagates":
            risks.append({"risk": "dependency_propagation", "severity": "HIGH", "confidence": "MEDIUM", "affected_components": outcomes.get("affected_components", [])})
        if outcomes.get("rollback_available") in (False, "no", "none"):
            risks.append({"risk": "low_reversibility", "severity": "HIGH", "confidence": "HIGH"})
        if outcomes.get("unknown"):
            uncertainties.extend(str(value) for value in outcomes["unknown"])
        if outcomes.get("capacity") == "unknown" or outcomes.get("rollback_available") == "unknown":
            uncertainties.append("important state or rollback information was not supplied")
        for assumption in scenario.assumptions:
            if assumption.kind in {AssumptionKind.INFERRED, AssumptionKind.ESTIMATED, AssumptionKind.UNKNOWN}:
                uncertainties.append(f"{assumption.name} is {assumption.kind.value}")
        if not uncertainties and not risks:
            confidence = "HIGH"
        elif any(r.get("confidence") == "HIGH" for r in risks) and not uncertainties:
            confidence = "MEDIUM"
        else:
            confidence = "LOW" if uncertainties else "MEDIUM"
        return risks, list(dict.fromkeys(uncertainties)), confidence


class SimulationEngine:
    """Composes scenario building, deterministic execution, constraints, and risk analysis."""

    def __init__(self) -> None:
        self.scenario_builder = ScenarioBuilder()
        self.assumption_manager = AssumptionManager()
        self.state_model = StateModel
        self.constraint_engine = ConstraintEngine()
        self.simulation_runner = SimulationRunner()
        self.outcome_comparator = OutcomeComparator()
        self.risk_analyzer = RiskAnalyzer()

    def simulate(self, inputs: Mapping[str, Any], query: str = "") -> SimulationResult:
        scenario = self.scenario_builder.build(inputs, query)
        outcomes = self.simulation_runner.run(scenario)
        constraints = self.constraint_engine.check(scenario, outcomes)
        risks, uncertainties, confidence = self.risk_analyzer.analyze(scenario, outcomes, constraints)
        alternatives, recommendation = self.outcome_comparator.compare(outcomes, scenario.alternatives)
        evidence = [{"source": key, "value": value, "kind": "input"} for key, value in scenario.provenance.items()]
        return SimulationResult(
            simulation_id=f"sim_{uuid4().hex}",
            simulation_type=scenario.simulation_type,
            scenario=scenario,
            assumptions=scenario.assumptions,
            inputs={"current_state": dict(scenario.current_state), "proposed_change": dict(scenario.proposed_change), "variables": dict(scenario.variables)},
            predicted_outcomes=outcomes,
            affected_components=tuple(outcomes.get("affected_components", [])),
            constraints=constraints,
            risks=tuple(risks),
            uncertainties=tuple(dict.fromkeys(uncertainties)),
            alternatives=tuple(alternatives),
            recommendation=recommendation,
            confidence=confidence,
            evidence=tuple(evidence),
            created_at=datetime.now(timezone.utc).isoformat(),
        )


class SimulationCapability(BaseCapability):
    """First-class capability for safe hypothetical outcome modeling."""

    def __init__(self) -> None:
        super().__init__(CapabilityMetadata(
            name="simulation_capability",
            version="1.0.0",
            description="Non-mutating system, workflow, resource, financial, project, decision, and agent-action simulation",
            category=CapabilityCategory.REASONING,
            is_singleton=True,
            auto_discoverable=True,
            default_action="simulate",
            supported_actions=["simulate", "compare", "should_simulate"],
            tags=["simulation", "simulate", "scenario", "what happens if", "impact", "compare scenarios"],
            safe_query=True,
        ))
        self.engine = SimulationEngine()

    def action_simulate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = str(inputs.get("query", ""))
        self._publish_event("simulation_started", {"simulation_type": inputs.get("simulation_type", inputs.get("type", "inferred"))})
        try:
            result = self.engine.simulate(inputs, query)
            payload = result.to_dict()
            self._publish_event("simulation_completed", {"simulation_id": result.simulation_id, "simulation_type": result.simulation_type.value, "confidence": result.confidence})
            if result.risks:
                self._publish_event("simulation_risk_detected", {"simulation_id": result.simulation_id, "risk_count": len(result.risks)})
            return {"success": True, "simulation": payload, "result_kind": "PREDICTED", "hypothetical": True, "verified": False, "message": "Simulation completed without executing the proposed action."}
        except (ValueError, KeyError, TypeError) as exc:
            self._publish_event("simulation_failed", {"error": str(exc)})
            return {"success": False, "error": str(exc), "what_could_be_simulated": [], "what_could_not_be_determined": ["requested scenario"], "hypothetical": True, "verified": False}

    def action_compare(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        inputs = dict(inputs)
        inputs["simulation_type"] = SimulationType.DECISION.value
        return self.action_simulate(inputs)

    def action_should_simulate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "required": self.requires_pre_execution_simulation(inputs), "reason": self._simulation_reason(inputs)}

    @staticmethod
    def requires_pre_execution_simulation(context: Mapping[str, Any]) -> bool:
        if context.get("requires_simulation") is True:
            return True
        if context.get("requires_simulation") is False:
            return False
        signals = (
            context.get("risk_level") in {"high", "critical", "HIGH", "CRITICAL"},
            context.get("mutation_level") in {"medium", "high", "destructive", "MEDIUM", "HIGH", "DESTRUCTIVE"},
            bool(context.get("approval_required")),
            bool(context.get("destructive")),
            context.get("reversibility") in {"low", "none", "irreversible"},
            bool(context.get("resource_intensive")),
            bool(context.get("system_wide_change")),
            bool(context.get("autonomous_recurrence")),
            bool(context.get("recurring")),
            bool(context.get("uncertain")),
            _number(context.get("affected_components_count", context.get("affected_components"))) is not None and (_number(context.get("affected_components_count", context.get("affected_components"))) or 0) > 1,
            (_number(context.get("complexity")) or 0) >= 3,
        )
        return any(signals)

    @staticmethod
    def _simulation_reason(context: Mapping[str, Any]) -> str:
        if context.get("requires_simulation") is True:
            return "explicitly requested"
        for key in ("risk_level", "mutation_level", "destructive", "resource_intensive", "system_wide_change", "autonomous_recurrence", "recurring", "uncertain", "complexity"):
            if context.get(key):
                return f"plan signal: {key}"
        return "no qualifying consequential-plan signal"


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_value(outcomes: Mapping[str, Any], metric: Any) -> Optional[float]:
    if metric is None:
        return None
    value = outcomes.get(str(metric))
    direct = _number(value)
    if direct is not None:
        return direct
    if isinstance(value, Mapping):
        for key in ("estimated_total", "used", "value", "total"):
            number = _number(value.get(key))
            if number is not None:
                return number
    resources = outcomes.get("resources")
    if isinstance(resources, Mapping):
        value = resources.get(str(metric))
        if isinstance(value, Mapping):
            for key in ("estimated_total", "used", "value", "total"):
                number = _number(value.get(key))
                if number is not None:
                    return number
    return None


def _resource_entry(resources: Any, name: str) -> Dict[str, Any]:
    if not isinstance(resources, Mapping):
        return {}
    value = resources.get(name, {})
    if isinstance(value, Mapping):
        return dict(value)
    number = _number(value)
    return {"used": number or 0.0} if number is not None else {}


def _reverse_reachable(dependencies: Mapping[str, Any], target: str) -> List[str]:
    reverse: Dict[str, List[str]] = {}
    for component, required in dependencies.items():
        if isinstance(required, Sequence) and not isinstance(required, (str, bytes)):
            for dependency in required:
                reverse.setdefault(str(dependency), []).append(str(component))
    found: List[str] = []
    pending = list(reverse.get(str(target), []))
    while pending:
        item = pending.pop(0)
        if item in found:
            continue
        found.append(item)
        pending.extend(reverse.get(item, []))
    return found


__all__ = [
    "Assumption", "AssumptionKind", "AssumptionManager", "ConstraintEngine", "OutcomeComparator", "RiskAnalyzer", "Scenario", "ScenarioBuilder", "SimulationCapability", "SimulationEngine", "SimulationResult", "SimulationRunner", "SimulationType", "StateModel",
]
