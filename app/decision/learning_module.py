# Learning Module - Unified learning pipeline integrating EventBus and Diagnostics

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from app.core.events import get_event_bus, Event, EventPriority, EventBus
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority
from app.decision.learning import (
    LearningFromDecisions,
    DecisionPattern,
    LearningInsight,
    ConfidenceCalibration,
    create_learning_from_decisions,
)
from app.decision.history import DecisionHistory, DecisionRecord
from app.decision.models import DecisionType, DecisionCategory
from app.confidence.confidence_scoring import ConfidenceCalculator

logger = logging.getLogger(__name__)


class LearningEventSource(Enum):
    DIAGNOSTIC = 'diagnostic'
    DECISION_OUTCOME = 'decision_outcome'
    SYSTEM_HEALTH = 'system_health'
    USER_FEEDBACK = 'user_feedback'
    PERFORMANCE_METRICS = 'performance_metrics'
    FAILURE_RECOVERY = 'failure_recovery'


@dataclass
class LearningEvent:
    event_id: str
    source: LearningEventSource
    event_type: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    processed: bool = False
    processing_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'event_id': self.event_id,
            'source': self.source.value,
            'event_type': self.event_type,
            'payload': self.payload,
            'timestamp': self.timestamp,
            'processed': self.processed,
            'processing_error': self.processing_error,
        }


@dataclass
class ModelUpdateProposal:
    proposal_id: str
    model_target: str
    update_type: str
    description: str
    proposed_changes: Dict[str, Any]
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    status: str = 'pending'
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'proposal_id': self.proposal_id,
            'model_target': self.model_target,
            'update_type': self.update_type,
            'description': self.description,
            'proposed_changes': self.proposed_changes,
            'confidence': self.confidence,
            'evidence': self.evidence,
            'status': self.status,
            'created_at': self.created_at,
            'reviewed_at': self.reviewed_at,
            'reviewed_by': self.reviewed_by,
        }


class LearningModuleConfig:
    def __init__(
        self,
        workspace: str = '.',
        min_samples_for_learning: int = 10,
        background_processing_interval: float = 60.0,
        max_events_per_batch: int = 100,
        enable_diagnostic_learning: bool = True,
        enable_decision_learning: bool = True,
        enable_auto_proposals: bool = False,
        proposal_confidence_threshold: float = 0.75,
        max_pending_proposals: int = 50,
    ):
        self.workspace = workspace
        self.min_samples_for_learning = min_samples_for_learning
        self.background_processing_interval = background_processing_interval
        self.max_events_per_batch = max_events_per_batch
        self.enable_diagnostic_learning = enable_diagnostic_learning
        self.enable_decision_learning = enable_decision_learning
        self.enable_auto_proposals = enable_auto_proposals
        self.proposal_confidence_threshold = proposal_confidence_threshold
        self.max_pending_proposals = max_pending_proposals


class LearningModule:
    def __init__(
        self,
        decision_history: DecisionHistory,
        confidence_calculator = None,
        config = None,
        event_bus = None,
        job_service = None,
    ):
        self.config = config or LearningModuleConfig()
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()

        self._learning_engine = create_learning_from_decisions(
            decision_history=decision_history,
            confidence_calculator=confidence_calculator,
            workspace=self.config.workspace,
        )

        self._event_queue = []
        self._queue_lock = threading.RLock()

        self._subscription_ids = []
        self._learning_job_id = None
        self._running = False
        self._lock = threading.RLock()

        self._proposals = {}
        self._proposals_lock = threading.RLock()

        self._stats = {
            'events_received': 0,
            'events_processed': 0,
            'events_failed': 0,
            'proposals_generated': 0,
            'learning_cycles': 0,
            'last_cycle': None,
        }
        self._stats_lock = threading.RLock()

        logger.info('[LearningModule] Initialized')

    def start(self) -> bool:
        with self._lock:
            if self._running:
                logger.warning('[LearningModule] Already running')
                return False
            self._running = True
            self._subscribe_to_events()
            self._start_background_job()
            logger.info('[LearningModule] Started successfully')
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                return True
            self._running = False
            self._unsubscribe_from_events()
            if self._learning_job_id:
                self._job_service.remove_job(self._learning_job_id)
                self._learning_job_id = None
            logger.info('[LearningModule] Stopped')
            return True

    @property
    def is_running(self) -> bool:
        return self._running

    def get_learning_engine(self):
        return self._learning_engine

    def analyze_outcomes(self, force_refresh: bool = False):
        return self._learning_engine.analyze_outcomes(force_refresh)

    def get_confidence_adjustment(self, decision_type, context):
        return self._learning_engine.get_confidence_adjustment(decision_type, context)

    def get_patterns(self, decision_type=None, min_success_rate=None):
        return self._learning_engine.get_patterns(decision_type, min_success_rate)

    def get_calibrations(self):
        return self._learning_engine.get_calibrations()

    def get_insights(self, severity=None, insight_type=None, limit=20):
        return self._learning_engine.get_insights(severity, insight_type, limit)

    def get_pending_proposals(self):
        with self._proposals_lock:
            return [p for p in self._proposals.values() if p.status == 'pending']

    def get_all_proposals(self):
        with self._proposals_lock:
            return list(self._proposals.values())

    def approve_proposal(self, proposal_id: str, reviewer: str = 'human') -> bool:
        with self._proposals_lock:
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return False
            if proposal.status != 'pending':
                return False
            proposal.status = 'approved'
            proposal.reviewed_at = datetime.now(timezone.utc).isoformat()
            proposal.reviewed_by = reviewer
            return True

    def reject_proposal(self, proposal_id: str, reviewer: str = 'human', reason: str = '') -> bool:
        with self._proposals_lock:
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return False
            proposal.status = 'rejected'
            proposal.reviewed_at = datetime.now(timezone.utc).isoformat()
            proposal.reviewed_by = reviewer
            proposal.evidence['rejection_reason'] = reason
            return True

    def apply_proposal(self, proposal_id: str, applier: str = 'system') -> bool:
        with self._proposals_lock:
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return False
            if proposal.status != 'approved':
                return False
            proposal.status = 'applied'
            proposal.evidence['applied_by'] = applier
            proposal.evidence['applied_at'] = datetime.now(timezone.utc).isoformat()
            proposal.evidence['note'] = 'STUB: Actual model update requires ML infrastructure'
            return True

    def inject_event(self, source, event_type, payload):
        event = LearningEvent(
            event_id='evt_' + uuid4().hex[:12],
            source=source, event_type=event_type, payload=payload)
        self._enqueue_event(event)
        return event.event_id

    def get_stats(self):
        with self._stats_lock:
            stats = dict(self._stats)
        with self._queue_lock:
            stats['queued_events'] = len(self._event_queue)
        with self._proposals_lock:
            stats['pending_proposals'] = sum(1 for p in self._proposals.values() if p.status == 'pending')
            stats['total_proposals'] = len(self._proposals)
        stats['learning_engine'] = {
            'patterns': len(self._learning_engine.get_patterns()),
            'calibrations': len(self._learning_engine.get_calibrations()),
            'insights': len(self._learning_engine.get_insights()),
        }
        return stats

    def get_status(self):
        return {
            'running': self._running,
            'config': {
                'enable_diagnostic_learning': self.config.enable_diagnostic_learning,
                'enable_decision_learning': self.config.enable_decision_learning,
                'enable_auto_proposals': self.config.enable_auto_proposals,
                'background_interval': self.config.background_processing_interval,
            },
            'stats': self.get_stats(),
            'event_subscriptions': len(self._subscription_ids),
        }

    def _subscribe_to_events(self):
        if self.config.enable_diagnostic_learning:
            self._subscription_ids.append(self._event_bus.subscribe('diagnostic.run.completed', self._on_diagnostic_completed, priority=10))
            self._subscription_ids.append(self._event_bus.subscribe('diagnostic.issue.found', self._on_diagnostic_issue, priority=10))
        if self.config.enable_decision_learning:
            self._subscription_ids.append(self._event_bus.subscribe('decision.outcome.recorded', self._on_decision_outcome, priority=10))
            self._subscription_ids.append(self._event_bus.subscribe('decision.made', self._on_decision_made, priority=5))
        self._subscription_ids.append(self._event_bus.subscribe('system.health.degraded', self._on_system_health, priority=15))
        self._subscription_ids.append(self._event_bus.subscribe('performance.metrics.collected', self._on_performance_metrics, priority=5))
        self._subscription_ids.append(self._event_bus.subscribe('failure.recovery.completed', self._on_failure_recovery, priority=10))
        self._subscription_ids.append(self._event_bus.subscribe('user.feedback.received', self._on_user_feedback, priority=15))

    def _unsubscribe_from_events(self):
        for sub_id in self._subscription_ids:
            self._event_bus.unsubscribe(sub_id)
        self._subscription_ids.clear()

    def _on_diagnostic_completed(self, event: Event):
        data = event.data or {}
        self._enqueue_event(LearningEvent(event.event_id, LearningEventSource.DIAGNOSTIC, 'diagnostic.completed', {'summary': data.get('summary', {}), 'issues': data.get('issues', []), 'timestamp': event.timestamp}))

    def _on_diagnostic_issue(self, event: Event):
        data = event.data or {}
        self._enqueue_event(LearningEvent(event.event_id, LearningEventSource.DIAGNOSTIC, 'diagnostic.issue', {'issue': data, 'timestamp': event.timestamp}))

    def _on_decision_outcome(self, event: Event):
        data = event.data or {}
        self._enqueue_event(LearningEvent(event.event_id, LearningEventSource.DECISION_OUTCOME, 'decision.outcome', {'decision_id': data.get('decision_id'), 'outcome': data.get('outcome'), 'actual_success': data.get('actual_success'), 'actual_effort': data.get('actual_effort'), 'actual_impact': data.get('actual_impact'), 'lesson_learned': data.get('lesson_learned'), 'would_repeat': data.get('would_repeat'), 'confidence': data.get('confidence'), 'context': data.get('context', {}), 'timestamp': event.timestamp}))

    def _on_decision_made(self, event: Event):
        data = event.data or {}
        self._enqueue_event(LearningEvent(event.event_id, LearningEventSource.DECISION_OUTCOME, 'decision.made', {'decision_id': data.get('decision_id'), 'decision_type': data.get('decision_type'), 'chosen_option': data.get('chosen_option'), 'confidence': data.get('confidence'), 'context': data.get('context', {}), 'timestamp': event.timestamp}))

    def _on_system_health(self, event: Event):
        data = event.data or {}
        self._enqueue_event(LearningEvent(event.event_id, LearningEventSource.SYSTEM_HEALTH, 'system.health.degraded', {'component': data.get('component'), 'severity': data.get('severity'), 'message': data.get('message'), 'metrics': data.get('metrics', {}), 'timestamp': event.timestamp}))

    def _on_performance_metrics(self, event: Event):
        data = event.data or {}
        self._enqueue_event(LearningEvent(event.event_id, LearningEventSource.PERFORMANCE_METRICS, 'performance.metrics', {'metrics': data.get('metrics', {}), 'component': data.get('component'), 'timestamp': event.timestamp}))

    def _on_failure_recovery(self, event: Event):
        data = event.data or {}
        self._enqueue_event(LearningEvent(event.event_id, LearningEventSource.FAILURE_RECOVERY, 'failure.recovery.completed', {'workflow_id': data.get('workflow_id'), 'task_id': data.get('task_id'), 'error': data.get('error'), 'recovery_action': data.get('recovery_action'), 'success': data.get('success'), 'attempts': data.get('attempts'), 'timestamp': event.timestamp}))

    def _on_user_feedback(self, event: Event):
        data = event.data or {}
        self._enqueue_event(LearningEvent(event.event_id, LearningEventSource.USER_FEEDBACK, 'user.feedback', {'feedback_type': data.get('feedback_type'), 'content': data.get('content'), 'rating': data.get('rating'), 'context': data.get('context', {}), 'timestamp': event.timestamp}))

    def _enqueue_event(self, event):
        with self._queue_lock:
            self._event_queue.append(event)
            if len(self._event_queue) > self.config.max_events_per_batch * 2:
                self._event_queue = self._event_queue[-self.config.max_events_per_batch:]
        with self._stats_lock:
            self._stats['events_received'] += 1

    def _dequeue_events(self, max_count):
        with self._queue_lock:
            events = self._event_queue[:max_count]
            self._event_queue = self._event_queue[max_count:]
        return events

    def _start_background_job(self):
        trigger = JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self.config.background_processing_interval, max_runs=None, delay_seconds=5.0)
        self._learning_job_id = self._job_service.schedule(job_id='learning_module_background', func=self._background_learning_cycle, trigger=trigger, name='Learning Module Background Cycle', priority=JobPriority.LOW, replace_existing=True)

    def _background_learning_cycle(self):
        if not self._running:
            return {'status': 'stopped'}
        cycle_start = time.time()
        events_processed = 0
        events_failed = 0
        try:
            events = self._dequeue_events(self.config.max_events_per_batch)
            for event in events:
                try:
                    self._process_learning_event(event)
                    event.processed = True
                    events_processed += 1
                except Exception as e:
                    event.processed = False
                    event.processing_error = str(e)
                    events_failed += 1
            if events_processed > 0 or (time.time() - (self._stats.get('last_cycle_time') or 0)) > 300:
                try:
                    analysis_result = self._learning_engine.analyze_outcomes()
                    self._maybe_generate_proposals(analysis_result)
                except Exception as e:
                    pass
            with self._stats_lock:
                self._stats['events_processed'] += events_processed
                self._stats['events_failed'] += events_failed
                self._stats['learning_cycles'] += 1
                self._stats['last_cycle'] = datetime.now(timezone.utc).isoformat()
                self._stats['last_cycle_time'] = time.time()
            return {'status': 'completed', 'events_processed': events_processed, 'events_failed': events_failed, 'duration_seconds': time.time() - cycle_start}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'duration_seconds': time.time() - cycle_start}

    def _process_learning_event(self, event):
        if event.source == LearningEventSource.DIAGNOSTIC:
            self._process_diagnostic_event(event.event_type, event.payload)
        elif event.source == LearningEventSource.DECISION_OUTCOME:
            self._process_decision_event(event.event_type, event.payload)
        elif event.source == LearningEventSource.SYSTEM_HEALTH:
            self._process_system_health_event(event.payload)
        elif event.source == LearningEventSource.PERFORMANCE_METRICS:
            self._process_performance_event(event.payload)
        elif event.source == LearningEventSource.FAILURE_RECOVERY:
            self._process_failure_recovery_event(event.payload)
        elif event.source == LearningEventSource.USER_FEEDBACK:
            self._process_user_feedback_event(event.payload)

    def _process_diagnostic_event(self, event_type, payload):
        if event_type == 'diagnostic.completed':
            issues = payload.get('issues', [])
            by_severity = defaultdict(int)
            for issue in issues:
                if isinstance(issue, dict):
                    by_severity[issue.get('severity', 'info')] += 1
            if by_severity.get('critical', 0) > 5:
                logger.info('[LearningModule] Diagnostic pattern: ' + str(by_severity['critical']) + ' critical issues found')

    def _process_decision_event(self, event_type, payload):
        if event_type == 'decision.outcome' and payload.get('decision_id') and payload.get('actual_success') is not None:
            self._learning_engine.record_decision_outcome(payload['decision_id'], payload.get('confidence', 0.5), payload['actual_success'], payload.get('context', {}))

    def _process_system_health_event(self, payload):
        if payload.get('severity') in ('critical', 'high'):
            logger.info('[LearningModule] System health degradation: ' + str(payload.get('component')) + ' (' + str(payload.get('severity')) + ')')

    def _process_performance_event(self, payload):
        pass

    def _process_failure_recovery_event(self, payload):
        if payload.get('success'):
            logger.info('[LearningModule] Recovery successful: ' + str(payload.get('recovery_action')) + ' (attempts: ' + str(payload.get('attempts')) + ')')
        else:
            logger.info('[LearningModule] Recovery failed: ' + str(payload.get('recovery_action')) + ' (attempts: ' + str(payload.get('attempts')) + ')')

    def _process_user_feedback_event(self, payload):
        if payload.get('rating') is not None:
            logger.info('[LearningModule] User feedback: ' + str(payload.get('feedback_type')) + ' (rating: ' + str(payload.get('rating')) + ')')

    def _maybe_generate_proposals(self, analysis_result):
        if not self.config.enable_auto_proposals:
            return


def create_learning_module(decision_history, confidence_calculator=None, workspace='.', config=None, event_bus=None, job_service=None):
    if config is None:
        config = LearningModuleConfig(workspace=workspace)
    return LearningModule(decision_history, confidence_calculator, config, event_bus, job_service)
