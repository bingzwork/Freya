from app.failure_recovery.orchestrator import RecoveryOrchestrator
from app.core.observability import HealthStatus

def test_zero_recovery_attempts_are_not_degraded():
    orchestrator = RecoveryOrchestrator(observability=None)
    result = orchestrator._health_check()
    assert result.status is HealthStatus.HEALTHY
    assert 'no recovery attempts yet' in result.message
    assert result.metadata['success_rate'] is None

def test_zero_successes_after_attempts_are_degraded():
    orchestrator = RecoveryOrchestrator(observability=None)
    orchestrator._stats['total_recoveries'] = 10
    orchestrator._stats['successful'] = 0
    result = orchestrator._health_check()
    assert result.status is HealthStatus.DEGRADED
    assert result.metadata['success_rate'] == 0.0
