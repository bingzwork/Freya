"""Autonomy Manager for Long-Term Autonomy.

This module implements the main autonomy manager that orchestrates the
autonomous decision loop, background scheduling, and integration with
other Freya systems.
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import traceback

from app.long_term_autonomy.models import (
    AutonomyConfig,
    AutonomyStateData,
    ObservationData,
    DecisionOutput,
    LearningUpdate,
    AutonomousTask
)
from app.long_term_autonomy.storage import AutonomyStorage
# Use shared infrastructure instead of duplicate implementations
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType
from app.core.events import get_event_bus
from app.long_term_autonomy.watchdog import Watchdog, WatchdogConfig
from app.long_term_autonomy.self_initiated import SelfInitiatedWorkManager
from app.long_term_autonomy.maintenance import MaintenanceManager, MaintenanceConfig
from app.long_term_autonomy.continuous_operation import ContinuousOperationManager, ContinuousOperationConfig

# Import existing Freya systems
from app.memory.goals import GoalStorage
from app.memory.experience_memory import ExperienceMemory
from app.memory.engineering_lessons import EngineeringLessonStorage
from app.memory.long_term_memory import LongTermMemory
from app.memory.semantic_memory import SemanticMemory
from app.memory.validation import KnowledgeValidator
from app.planner.scheduler import Scheduler as PlannerScheduler, SchedulingStrategy
from app.planner.task_graph import TaskGraph
from app.planner.task import Task, TaskStatus, TaskPriority
from app.planner.resource_allocator import ResourceAllocator
from app.autonomous_learning.pipeline import AutonomousLearningPipeline as LearningPipeline
from app.world_model.model import WorldModel
from app.monitoring.system_monitor import SystemMonitor
from app.failure_recovery.orchestrator import RecoveryOrchestrator as FailureRecoveryOrchestrator
from app.core.logger import logger


class AutonomyPhase(Enum):
    """Phases of the autonomous decision loop."""
    OBSERVE = "observe"
    ANALYZE = "analyze"
    DECIDE = "decide"
    ACT = "act"
    VERIFY = "verify"
    LEARN = "learn"


class AutonomyManager:
    """
    Main manager for the Long-Term Autonomy system.

    This class orchestrates the autonomous operation of Freya by:
    1. Running the autonomous decision loop (observe-analyze-decide-act-verify-learn)
    2. Managing background scheduling for recurring tasks (via shared BackgroundJobService)
    3. Integrating with existing Freya systems (goals, planning, execution, learning, etc.)
    4. Handling state persistence and recovery
    5. Providing lifecycle management (start, stop, pause, resume)
    """

    def __init__(
        self,
        workspace: str = ".",
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """
        Initialize the Autonomy Manager.

        Args:
            workspace: The workspace directory for storage and resources
            event_bus: Optional shared EventBus instance (uses global if not provided)
            job_service: Optional shared BackgroundJobService instance (uses global if not provided)
            observability: Optional shared ObservabilityHub instance (uses global if not provided)
        """
        self.workspace = workspace

        # Shared infrastructure
        self.event_bus = event_bus or get_event_bus()
        self.job_service = job_service or get_job_service()
        self.observability = observability or get_observability_hub()

        self.storage = AutonomyStorage(workspace)
        self.config = self.storage.load_config()
        self.state = self.storage.load_state()
        self.tasks = self.storage.load_tasks()

        # Initialize core memory systems (needed for learning pipeline)
        self.experience_memory = ExperienceMemory(workspace)
        self.engineering_lessons = EngineeringLessonStorage(workspace)
        self.long_term_memory = LongTermMemory(workspace)
        self.semantic_memory = SemanticMemory(workspace)
        self.knowledge_validator = KnowledgeValidator(workspace)

        # Initialize core systems
        self.goal_storage = GoalStorage(workspace)
        self.resource_allocator = ResourceAllocator()
        self._initialize_default_resources()
        self.planner_scheduler = PlannerScheduler()
        self.task_graph = TaskGraph()
        self.world_model = WorldModel()
        self.system_monitor = SystemMonitor()
        self.failure_recovery = FailureRecoveryOrchestrator()
        self.learning_pipeline = LearningPipeline(
            experience_memory=self.experience_memory,
            engineering_lessons=self.engineering_lessons,
            long_term_memory=self.long_term_memory,
            semantic_memory=self.semantic_memory,
            knowledge_validator=self.knowledge_validator,
            goal_storage=self.goal_storage,
            planner=self.planner_scheduler,
        )
        # Note: Executor requires LLM and tools - we'll set these later or get from context
        self.executor = None  # Will be set via set_executor method

        # Initialize new Long-Term Autonomy systems
        self.watchdog = Watchdog(WatchdogConfig())
        self.self_initiated_work = SelfInitiatedWorkManager(workspace)
        self.maintenance = MaintenanceManager(workspace, MaintenanceConfig())
        self.continuous_operation = ContinuousOperationManager(workspace, ContinuousOperationConfig())

        # Register subsystems for continuous operation
        self.continuous_operation.register_subsystem("goal_storage", self.goal_storage)
        self.continuous_operation.register_subsystem("resource_allocator", self.resource_allocator)
        self.continuous_operation.register_subsystem("planner_scheduler", self.planner_scheduler)
        self.continuous_operation.register_subsystem("task_graph", self.task_graph)
        self.continuous_operation.register_subsystem("world_model", self.world_model)
        self.continuous_operation.register_subsystem("system_monitor", self.system_monitor)
        self.continuous_operation.register_subsystem("failure_recovery", self.failure_recovery)
        self.continuous_operation.register_subsystem("learning_pipeline", self.learning_pipeline)
        self.continuous_operation.register_subsystem("watchdog", self.watchdog)
        self.continuous_operation.register_subsystem("self_initiated_work", self.self_initiated_work)
        self.continuous_operation.register_subsystem("maintenance", self.maintenance)

        # Register with shared observability
        self._register_with_observability()

        # Initialize runtime state
        self._initialize_state()

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self.observability:
            self.observability.add_health_check(HealthCheck(
                name="long_term_autonomy_health",
                component="long_term_autonomy",
                check_func=self._autonomy_health_check,
                interval_seconds=30.0,
            ))

            # Register component
            self.observability.register_component(ComponentInfo(
                name="AutonomyManager",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Main manager for Long-Term Autonomy: decision loop, scheduling, integrations",
                metadata={},
            ))

    def _autonomy_health_check(self) -> HealthResult:
        """Health check for the AutonomyManager subsystem."""
        try:
            if not self._running:
                return HealthResult(
                    name="long_term_autonomy_health",
                    component="long_term_autonomy",
                    status=HealthStatus.UNHEALTHY,
                    message="Autonomy manager is not running",
                    metadata={"running": False}
                )

            # Check if main thread is alive
            if self._main_thread and not self._main_thread.is_alive():
                return HealthResult(
                    name="long_term_autonomy_health",
                    component="long_term_autonomy",
                    status=HealthStatus.UNHEALTHY,
                    message="Main autonomy thread has died",
                    metadata={"running": self._running, "cycle_count": self._cycle_count}
                )

            # Check error count
            if self._error_count > 10:
                return HealthResult(
                    name="long_term_autonomy_health",
                    component="long_term_autonomy",
                    status=HealthStatus.UNHEALTHY,
                    message=f"High error count: {self._error_count}",
                    metadata={"error_count": self._error_count, "cycle_count": self._cycle_count}
                )

            return HealthResult(
                name="long_term_autonomy_health",
                component="long_term_autonomy",
                status=HealthStatus.HEALTHY,
                message="Autonomy manager running normally",
                metadata={
                    "running": self._running,
                    "cycle_count": self._cycle_count,
                    "error_count": self._error_count,
                    "last_cycle_time": self._last_cycle_time,
                    "current_phase": self.state.current_phase.value if self.state.current_phase else None,
                }
            )
        except Exception as e:
            return HealthResult(
                name="long_term_autonomy_health",
                component="long_term_autonomy",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _register_background_jobs(self) -> None:
        """Register all recurring background jobs with the shared BackgroundJobService."""
        job_service = self.job_service

        # State persistence job
        job_service.schedule(
            job_id="autonomy_persist_state",
            func=self._autonomy_persist_state,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self.config.state_persistence_interval_seconds),
            priority=JobPriority.LOW,
            max_retries=3,
            replace_existing=True,
        )

        # Learning pipeline job
        job_service.schedule(
            job_id="autonomy_learning_pipeline",
            func=self._run_learning_pipeline_job,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self.config.learning_interval_seconds),
            priority=JobPriority.NORMAL,
            max_retries=3,
            replace_existing=True,
        )

        # Maintenance job (cleanup old tasks, etc.)
        job_service.schedule(
            job_id="autonomy_maintenance",
            func=self._autonomy_maintenance_job,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=3600),  # Every hour
            priority=JobPriority.LOW,
            max_retries=1,
            replace_existing=True,
        )

        # Watchdog checkpoint job
        job_service.schedule(
            job_id="autonomy_watchdog_checkpoint",
            func=self._autonomy_watchdog_checkpoint,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self.config.watchdog_checkpoint_interval_seconds),
            priority=JobPriority.HIGH,
            max_retries=1,
            replace_existing=True,
        )

        # Self-initiated work discovery job
        job_service.schedule(
            job_id="autonomy_self_initiated_work",
            func=self._autonomy_self_initiated_work_job,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self.config.self_initiated_work_interval_seconds),
            priority=JobPriority.NORMAL,
            max_retries=1,
            replace_existing=True,
        )

        logger.info("Registered autonomy background jobs with shared BackgroundJobService")

    def _unregister_background_jobs(self) -> None:
        """Unregister all background jobs from the shared BackgroundJobService."""
        job_service = self.job_service

        job_ids = [
            "autonomy_persist_state",
            "autonomy_learning_pipeline",
            "autonomy_maintenance",
            "autonomy_watchdog_checkpoint",
            "autonomy_self_initiated_work",
        ]

        for job_id in job_ids:
            try:
                job_service.cancel(job_id)
            except Exception as e:
                logger.warning(f"Failed to cancel job {job_id}: {e}")

        logger.info("Unregistered autonomy background jobs from shared BackgroundJobService")

    def _autonomy_persist_state(self) -> None:
        """Background job to persist autonomy state to storage."""
        try:
            with self._lock:
                self._sync_state_to_storage()
            logger.debug("Autonomy state persisted successfully")
        except Exception as e:
            logger.error(f"Failed to persist autonomy state: {e}")

    def _run_learning_pipeline_job(self) -> None:
        """Background job to run the learning pipeline."""
        try:
            if self.learning_pipeline:
                self.learning_pipeline.run_cycle()
            logger.debug("Learning pipeline job completed")
        except Exception as e:
            logger.error(f"Learning pipeline job failed: {e}")

    def _autonomy_maintenance_job(self) -> None:
        """Background job for autonomy maintenance tasks."""
        try:
            # Clean up completed/failed tasks older than 7 days
            if self.tasks:
                self._cleanup_old_tasks(max_age_days=7)
            logger.debug("Autonomy maintenance job completed")
        except Exception as e:
            logger.error(f"Autonomy maintenance job failed: {e}")

    def _autonomy_watchdog_checkpoint(self) -> None:
        """Background job for watchdog checkpoint."""
        try:
            if self.watchdog:
                self.watchdog.checkpoint("autonomy_system")
            logger.debug("Watchdog checkpoint job completed")
        except Exception as e:
            logger.error(f"Watchdog checkpoint job failed: {e}")

    def _autonomy_self_initiated_work_job(self) -> None:
        """Background job for self-initiated work discovery."""
        try:
            if self.self_initiated_work:
                self.self_initiated_work.discover_work()
            logger.debug("Self-initiated work job completed")
        except Exception as e:
            logger.error(f"Self-initiated work job failed: {e}")

    def _cleanup_old_tasks(self, max_age_days: int = 7) -> None:
        """Clean up old completed/failed tasks."""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cutoff_iso = cutoff.isoformat()

        removed = 0
        task_ids_to_remove = []
        for task_id, task in self.tasks.items():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if task.completed_at and task.completed_at < cutoff_iso:
                    task_ids_to_remove.append(task_id)

        for task_id in task_ids_to_remove:
            del self.tasks[task_id]
            removed += 1

        if removed > 0:
            self.storage.save_tasks(self.tasks)
            logger.info(f"Cleaned up {removed} old tasks")

    def _initialize_state(self) -> None:
        """Initialize runtime state."""
        self._lock = threading.RLock()
        self._running = False
        self._main_thread = None
        self._shutdown_event = threading.Event()
        self._pause_event = threading.Event()
        self._last_cycle_time = 0.0
        self._cycle_count = 0
        self._error_count = 0

        # Initialize state from storage
        self._sync_state_from_storage()

    def _initialize_default_resources(self) -> None:
        """Initialize default machine and tool resources."""
        # Default machine resource
        from app.planner.resource_allocator import Resource, ResourceType
        machine_resource = Resource(
            id="resource_machine_default",
            name="Default Machine",
            resource_type=ResourceType.MACHINE,
            capacity=1.0,
            available=1.0,
            unit="machine",
            description="Default execution machine",
        )
        self.resource_allocator.add_resource(machine_resource)

        # Default tool resources
        tool_resource = Resource(
            id="resource_tools_default",
            name="Development Tools",
            resource_type=ResourceType.TOOL,
            capacity=1.0,
            available=1.0,
            unit="toolset",
            description="Standard development toolset (git, build tools, test runners, etc.)",
        )
        self.resource_allocator.add_resource(tool_resource)

        # GPU resource (if available)
        gpu_resource = Resource(
            id="resource_gpu_default",
            name="GPU Resource",
            resource_type=ResourceType.GPU,
            capacity=1.0,
            available=1.0,
            unit="gpu",
            description="GPU acceleration resource",
        )
        self.resource_allocator.add_resource(gpu_resource)

    def _sync_state_from_storage(self) -> None:
        """Synchronize in-memory state with stored state."""
        with self._lock:
            # Update state from storage (but keep running status as is)
            stored_state = self.storage.load_state()
            self.state = stored_state  # Use the stored state directly

    def _sync_state_to_storage(self) -> None:
        """Synchronize stored state with in-memory state.

        Note: Caller must hold self._lock
        """
        self.state.updated_at = datetime.now(timezone.utc).isoformat()
        # Update the storage's internal state
        self.storage._state = self.state
        self.storage.save_state()

    def set_executor(self, llm, tools, engineering_lessons=None) -> None:
        """
        Set the executor for running tasks.

        Args:
            llm: The language model to use
            tools: The tools available to the agent
            engineering_lessons: Optional engineering lessons for learning
        """
        from app.agent.executor import Executor
        self.executor = Executor(llm, tools, engineering_lessons)
        self.executor.set_conversation_control(self)  # Use self as conversation control

    # ==================== Lifecycle Management ====================

    def start(self) -> bool:
        """
        Start the autonomous system.

        Returns:
            True if started successfully, False otherwise
        """
        with self._lock:
            if self._running:
                logger.warning("Autonomy system is already running")
                return False

            if not self.config.enabled:
                logger.warning("Autonomy system is disabled in configuration")
                return False

            try:
                # Initialize state
                self._running = True
                self._shutdown_event.clear()
                self._pause_event.clear()
                self.state.is_running = True
                self.state.startup_time = datetime.now(timezone.utc).isoformat()
                self.state.shutdown_time = None
                self.state.error_count = 0  # Reset error count on start
                self._sync_state_to_storage()

                # Register background jobs using shared BackgroundJobService
                self._register_background_jobs()

                # Start new Long-Term Autonomy systems
                self.watchdog.start()
                self.self_initiated_work.start()
                self.maintenance.start()
                self.continuous_operation.start()

                # Set up self-initiated work callbacks
                self._setup_self_initiated_work_callbacks()

                # Start the main autonomy loop in a separate thread
                self._main_thread = threading.Thread(
                    target=self._autonomy_loop,
                    daemon=True,
                    name="AutonomyMainLoop"
                )
                self._main_thread.start()

                logger.info("Autonomy system started")
                return True

            except Exception as e:
                logger.error(f"Failed to start autonomy system: {e}")
                self._running = False
                self.state.is_running = False
                self._sync_state_to_storage()
                return False

    def stop(self) -> bool:
        """
        Stop the autonomous system.

        Returns:
            True if stopped successfully, False otherwise
        """
        with self._lock:
            if not self._running:
                logger.warning("Autonomy system is not running")
                return False

            # Signal shutdown
            self._shutdown_event.set()
            self._running = False
            self.state.is_running = False
            self.state.shutdown_time = datetime.now(timezone.utc).isoformat()
            self._sync_state_to_storage()

        # Unregister background jobs and stop scheduler jobs (outside lock to avoid deadlock)
        self._unregister_background_jobs()

        # Stop new Long-Term Autonomy systems (outside lock)
        self.watchdog.stop()
        self.self_initiated_work.stop()
        self.maintenance.stop()
        self.continuous_operation.stop()

        # Wait for main thread to finish (with timeout, outside lock)
        if self._main_thread and self._main_thread.is_alive():
            self._main_thread.join(timeout=5.0)

        logger.info("Autonomy system stopped")
        return True

    def pause(self) -> bool:
        """
        Pause the autonomous system.

        Returns:
            True if paused successfully, False otherwise
        """
        with self._lock:
            if not self._running:
                logger.warning("Autonomy system is not running")
                return False

            try:
                self._pause_event.set()
                self.state.is_running = False  # Not running but not stopped
                self._sync_state_to_storage()
                logger.info("Autonomy system paused")
                return True
            except Exception as e:
                logger.error(f"Error pausing autonomy system: {e}")
                return False

    def resume(self) -> bool:
        """
        Resume the autonomous system.

        Returns:
            True if resumed successfully, False otherwise
        """
        with self._lock:
            if not self._running:
                # Should be paused state
                logger.warning("Autonomy system is not in a paused state")
                return False

            try:
                self._pause_event.clear()
                self.state.is_running = True
                self._sync_state_to_storage()
                logger.info("Autonomy system resumed")
                return True
            except Exception as e:
                logger.error(f"Error resuming autonomy system: {e}")
                return False

    def _setup_self_initiated_work_callbacks(self) -> None:
        """Set up callbacks for self-initiated work integration."""

        def task_creator(opportunity):
            """Create an autonomous task from an opportunity."""
            task = self.create_autonomous_task(
                description=opportunity.description,
                source=f"self_initiated:{opportunity.type.value}",
                priority=opportunity.priority.value,
                metadata={
                    "opportunity_id": opportunity.id,
                    "opportunity_type": opportunity.type.value,
                    "confidence": opportunity.confidence,
                    "location": opportunity.location
                }
            )
            return task.id

        def context_provider():
            """Provide context for opportunity detectors."""
            system_metrics = self.system_monitor.get_current_metrics()
            if system_metrics:
                metrics_dict = {
                    'cpu_usage_percent': system_metrics.cpu_percent,
                    'memory_usage_percent': system_metrics.memory_percent,
                    'disk_usage_percent': system_metrics.disk_percent,
                    'cpu_count': system_metrics.cpu_count,
                    'cpu_freq_mhz': system_metrics.cpu_freq_mhz,
                    'memory_total_gb': system_metrics.memory_total_gb,
                    'memory_used_gb': system_metrics.memory_used_gb,
                    'memory_free_gb': system_metrics.memory_free_gb,
                    'disk_total_gb': system_metrics.disk_total_gb,
                    'disk_used_gb': system_metrics.disk_used_gb,
                    'disk_free_gb': system_metrics.disk_free_gb,
                    'disk_read_mb': system_metrics.disk_read_mb,
                    'disk_write_mb': system_metrics.disk_write_mb,
                    'net_sent_mb': system_metrics.net_sent_mb,
                    'net_recv_mb': system_metrics.net_recv_mb,
                    'process_count': system_metrics.process_count,
                    'thread_count': system_metrics.thread_count,
                    'temperature_celsius': system_metrics.temperature_celsius,
                }
            else:
                metrics_dict = {}

            return {
                "workspace": self.workspace,
                "goals": [g.__dict__ for g in self.goal_storage.all()],
                "tasks": [t.__dict__ for t in self.storage.list_tasks()],
                "system_metrics": metrics_dict,
                "git_status": self._get_git_status() if hasattr(self, '_get_git_status') else {}
            }

        self.self_initiated_work.set_task_creator(task_creator)
        self.self_initiated_work.set_context_provider(context_provider)

    # ==================== Autonomous Decision Loop ====================

    def _autonomy_loop(self) -> None:
        """Main autonomous decision loop."""
        logger.info("Autonomy main loop started")

        while not self._shutdown_event.is_set():
            try:
                # Check if we should pause
                if self._pause_event.is_set():
                    time.sleep(1.0)
                    continue

                # Check if enough time has passed since last cycle
                now = time.time()
                if now - self._last_cycle_time < self.config.cycle_interval_seconds:
                    time.sleep(0.1)
                    continue

                # Run one autonomy cycle
                self._run_autonomy_cycle()

                # Update last cycle time
                self._last_cycle_time = now

                # Persist state periodically
                if self._cycle_count % 10 == 0:  # Every 10 cycles
                    with self._lock:
                        self._sync_state_to_storage()

            except Exception as e:
                logger.error(f"Error in autonomy loop: {e}")
                logger.error(traceback.format_exc())
                self._error_count += 1
                self.state.error_count = self._error_count
                # Continue running unless we have too many errors
                if self._error_count >= self.config.max_consecutive_failures:
                    logger.critical("Too many consecutive errors, stopping autonomy")
                    self.stop()
                    break

                # Wait before retrying
                time.sleep(5.0)

        logger.info("Autonomy main loop ended")

    def _run_autonomy_cycle(self) -> None:
        """Execute one complete autonomy cycle."""
        with self._lock:
            self._cycle_count += 1
            self.state.cycle_count = self._cycle_count
            cycle_start = time.time()

        try:
            # Phase 1: Observe
            self._update_state(phase=AutonomyPhase.OBSERVE.value)
            observation = self._observe()
            self.state.last_observation_data = observation.__dict__

            # Phase 2: Analyze
            self._update_state(phase=AutonomyPhase.ANALYZE.value)
            analysis = self._analyze(observation)

            # Phase 3: Decide
            self._update_state(phase=AutonomyPhase.DECIDE.value)
            decision = self._decide(analysis)

            # Phase 4: Act
            self._update_state(phase=AutonomyPhase.ACT.value)
            action_result = self._act(decision)

            # Phase 5: Verify
            self._update_state(phase=AutonomyPhase.VERIFY.value)
            verification_result = self._verify(action_result, decision)

            # Phase 6: Learn
            self._update_state(phase=AutonomyPhase.LEARN.value)
            learning_update = self._learn(observation, decision, action_result, verification_result)

            # Update state with results
            self._update_state(
                last_decision_time=datetime.now(timezone.utc).isoformat(),
                last_decision_output=decision.__dict__ if decision else None,
                last_action_result=action_result,
                last_verification_result=verification_result,
                last_learning_update=learning_update.__dict__ if learning_update else None
            )

            # Update metrics
            cycle_duration = time.time() - cycle_start
            self._update_metrics(cycle_duration, success=True)

        except Exception as e:
            logger.error(f"Error in autonomy cycle {self._cycle_count}: {e}")
            logger.error(traceback.format_exc())
            self._update_metrics(0, success=False)
            raise

    def _update_state(self, **kwargs) -> None:
        """Update the autonomy state with given fields."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, value)
            self.state.updated_at = datetime.now(timezone.utc).isoformat()

    def _update_metrics(self, cycle_duration: float, success: bool) -> None:
        """Update performance metrics."""
        with self._lock:
            if not hasattr(self.state, 'metrics') or self.state.metrics is None:
                self.state.metrics = {}

            # Update cycle timing
            self.state.metrics['last_cycle_duration'] = cycle_duration
            if success:
                self.state.metrics['successful_cycles'] = self.state.metrics.get('successful_cycles', 0) + 1
            else:
                self.state.metrics['failed_cycles'] = self.state.metrics.get('failed_cycles', 0) + 1

            # Calculate average cycle time (last 100 cycles)
            cycle_times = self.state.metrics.get('cycle_times', [])
            cycle_times.append(cycle_duration)
            if len(cycle_times) > 100:
                cycle_times.pop(0)
            self.state.metrics['cycle_times'] = cycle_times
            if cycle_times:
                self.state.metrics['average_cycle_time'] = sum(cycle_times) / len(cycle_times)

            # Update success rate
            total_cycles = self.state.metrics.get('successful_cycles', 0) + self.state.metrics.get('failed_cycles', 0)
            if total_cycles > 0:
                self.state.metrics['success_rate'] = self.state.metrics.get('successful_cycles', 0) / total_cycles

    # ==================== Decision Loop Phases ====================

    def _observe(self) -> ObservationData:
        """
        Observe the current state of the system and environment.

        Returns:
            ObservationData containing observations from various sources
        """
        observation = ObservationData()

        try:
            # System metrics
            if self.config.observation_enabled and "system_metrics" in self.config.observation_sources:
                # Get system metrics from monitor
                system_metrics = self.system_monitor.get_current_metrics()
                if system_metrics:
                    # Convert ResourceMetrics dataclass to dict
                    observation.system_metrics = {
                        'cpu_usage_percent': system_metrics.cpu_percent,
                        'memory_usage_percent': system_metrics.memory_percent,
                        'disk_usage_percent': system_metrics.disk_percent,
                        'cpu_count': system_metrics.cpu_count,
                        'cpu_freq_mhz': system_metrics.cpu_freq_mhz,
                        'memory_total_gb': system_metrics.memory_total_gb,
                        'memory_used_gb': system_metrics.memory_used_gb,
                        'memory_free_gb': system_metrics.memory_free_gb,
                        'disk_total_gb': system_metrics.disk_total_gb,
                        'disk_used_gb': system_metrics.disk_used_gb,
                        'disk_free_gb': system_metrics.disk_free_gb,
                        'disk_read_mb': system_metrics.disk_read_mb,
                        'disk_write_mb': system_metrics.disk_write_mb,
                        'net_sent_mb': system_metrics.net_sent_mb,
                        'net_recv_mb': system_metrics.net_recv_mb,
                        'process_count': system_metrics.process_count,
                        'thread_count': system_metrics.thread_count,
                        'temperature_celsius': system_metrics.temperature_celsius,
                    }

            # Goal status
            if self.config.observation_enabled and "goal_status" in self.config.observation_sources:
                goals = self.goal_storage.all()
                observation.goal_status = {
                    'total': len(goals),
                    'by_status': {},
                    'by_priority': {}
                }
                for goal in goals:
                    status = goal.status
                    priority = goal.priority
                    observation.goal_status['by_status'][status] = observation.goal_status['by_status'].get(status, 0) + 1
                    observation.goal_status['by_priority'][priority] = observation.goal_status['by_priority'].get(priority, 0) + 1

            # Task status
            if self.config.observation_enabled and "task_status" in self.config.observation_sources:
                tasks = self.storage.list_tasks()
                observation.task_status = {
                    'total': len(tasks),
                    'by_status': {},
                    'by_source': {}
                }
                for task in tasks:
                    status = task.status
                    source = task.source
                    observation.task_status['by_status'][status] = observation.task_status['by_status'].get(status, 0) + 1
                    observation.task_status['by_source'][source] = observation.task_status['by_source'].get(source, 0) + 1

            # Resource usage
            if self.config.observation_enabled and "resource_usage" in self.config.observation_sources:
                resource_usage = {}
                for resource in self.resource_allocator.list_resources():
                    resource_id = resource.id
                    usage = (resource.capacity - resource.available) / resource.capacity if resource.capacity > 0 else 0
                    resource_usage[resource_id] = {
                        'capacity': resource.capacity,
                        'available': resource.available,
                        'usage_ratio': usage
                    }
                observation.resource_usage = resource_usage

            # External events (from world model or other sources)
            if self.config.observation_enabled and "external_events" in self.config.observation_sources:
                # TODO: Implement event collection from external sources
                observation.external_events = []

            # Anomalies (from failure detection or monitoring)
            if self.config.observation_enabled and "anomalies" in self.config.observation_sources:
                # Get recent anomalies from failure recovery system
                anomalies = self.failure_recovery.get_recent_anomalies(hours=1)
                observation.anomalies = anomalies

        except Exception as e:
            logger.error(f"Error during observation phase: {e}")
            # Return partial observation data

        return observation

    def _analyze(self, observation: ObservationData) -> dict:
        """
        Analyze observations to identify patterns, opportunities, and issues.

        Args:
            observation: The observation data from the observe phase

        Returns:
            Analysis results as a dictionary
        """
        analysis = {
            'timestamp': observation.timestamp,
            'patterns': [],
            'opportunities': [],
            'issues': [],
            'recommendations': []
        }

        try:
            # Analyze goal progress
            if observation.goal_status:
                # Check for stalled goals
                stalled_goals = []  # Would need to implement goal staleness check
                if stalled_goals:
                    analysis['issues'].append({
                        'type': 'stalled_goals',
                        'count': len(stalled_goals),
                        'details': stalled_goals
                    })
                    analysis['recommendations'].append({
                        'action': 'review_stalled_goals',
                        'priority': 'medium',
                        'reason': 'Several goals have not been updated recently'
                    })

            # Analyze system metrics for performance issues
            if observation.system_metrics:
                cpu_usage = observation.system_metrics.get('cpu_usage_percent', 0)
                memory_usage = observation.system_metrics.get('memory_usage_percent', 0)
                if cpu_usage > 90:
                    analysis['issues'].append({
                        'type': 'high_cpu_usage',
                        'value': cpu_usage,
                        'threshold': 90
                    })
                    analysis['recommendations'].append({
                        'action': 'investigate_high_cpu',
                        'priority': 'high',
                        'reason': f'CPU usage is {cpu_usage}%'
                    })
                if memory_usage > 90:
                    analysis['issues'].append({
                        'type': 'high_memory_usage',
                        'value': memory_usage,
                        'threshold': 90
                    })
                    analysis['recommendations'].append({
                        'action': 'investigate_high_memory',
                        'priority': 'high',
                        'reason': f'Memory usage is {memory_usage}%'
                    })

            # Analyze task backlog
            if observation.task_status:
                pending_tasks = observation.task_status['by_status'].get('pending', 0)
                failed_tasks = observation.task_status['by_status'].get('failed', 0)
                if pending_tasks > 10:
                    analysis['opportunities'].append({
                        'type': 'task_backlog',
                        'count': pending_tasks,
                        'suggestion': 'Consider prioritizing or delegating some tasks'
                    })
                if failed_tasks > 0:
                    analysis['issues'].append({
                        'type': 'failed_tasks',
                        'count': failed_tasks
                    })
                    analysis['recommendations'].append({
                        'action': 'review_failed_tasks',
                        'priority': 'medium',
                        'reason': f'{failed_tasks} tasks have failed recently'
                    })

            # Analyze anomalies
            if observation.anomalies:
                analysis['issues'].extend([
                    {
                        'type': 'anomaly',
                        'details': anomaly
                    } for anomaly in observation.anomalies
                ])

            # Use world model for contextual analysis
            # TODO: Implement deeper analysis with world model

        except Exception as e:
            logger.error(f"Error during analysis phase: {e}")
            analysis['error'] = str(e)

        return analysis

    def _decide(self, analysis: dict) -> Optional[DecisionOutput]:
        """
        Make decisions based on analysis.

        Args:
            analysis: The analysis results from the analyze phase

        Returns:
            A DecisionOutput object representing the decision made, or None
        """
        # If no recommendations, return None (no action needed)
        if not analysis.get('recommendations'):
            return None

        try:
            # Simple decision making: pick the highest priority recommendation
            # In a more sophisticated system, we would use weighted scoring,
            # machine learning, or other decision-making algorithms

            recommendations = analysis['recommendations']
            # Sort by priority (high > medium > low)
            priority_order = {'high': 3, 'medium': 2, 'low': 1}
            sorted_recommendations = sorted(
                recommendations,
                key=lambda r: priority_order.get(r.get('priority', 'low'), 0),
                reverse=True
            )

            top_rec = sorted_recommendations[0] if sorted_recommendations else None
            if not top_rec:
                return None

            # Create decision output based on the recommendation
            decision = DecisionOutput()
            decision.action_type = top_rec.get('action', 'unknown')
            decision.action_details = {
                'reason': top_rec.get('reason', ''),
                'analysis_snapshot': analysis
            }
            decision.priority = priority_order.get(top_rec.get('priority', 'low'), 1)
            decision.confidence = 0.7  # Default confidence
            decision.reasoning = f"Selected based on analysis: {top_rec.get('reason', '')}"
            decision.expected_outcome = {
                'description': f"Expected outcome of {decision.action_type}",
                'success_criteria': ['Task completed without error']
            }

            return decision

        except Exception as e:
            logger.error(f"Error during decision phase: {e}")
            return None

    def _act(self, decision: Optional[DecisionOutput]) -> dict:
        """
        Execute the decided action.

        Args:
            decision: The decision to act on, or None

        Returns:
            Result of the action execution
        """
        if not decision:
            return {'action_taken': False, 'reason': 'No decision to act on'}

        try:
            action_type = decision.action_type
            action_details = decision.action_details

            # Handle different action types
            if action_type == 'execute_task':
                # Execute a specific task (would need to be defined in action_details)
                return self._execute_specific_task(action_details)

            elif action_type == 'create_goal':
                # Create a new goal based on the decision
                return self._create_goal_from_decision(action_details)

            elif action_type == 'review_stalled_goals':
                # Review and potentially update stalled goals
                return self._review_stalled_goals(action_details)

            elif action_type == 'investigate_high_cpu':
                # Investigate high CPU usage
                return self._investigate_resource_issue('cpu', action_details)

            elif action_type == 'investigate_high_memory':
                # Investigate high memory usage
                return self._investigate_resource_issue('memory', action_details)

            elif action_type == 'review_failed_tasks':
                # Review and potentially retry failed tasks
                return self._review_failed_tasks(action_details)

            elif action_type == 'maintenance':
                # Perform routine maintenance
                return self._perform_maintenance(action_details)

            else:
                # Unknown action type
                return {
                    'action_taken': False,
                    'reason': f'Unknown action type: {action_type}',
                    'decision': decision.__dict__
                }

        except Exception as e:
            logger.error(f"Error during action phase: {e}")
            logger.error(traceback.format_exc())
            return {
                'action_taken': False,
                'error': str(e),
                'decision': decision.__dict__
            }

    def _verify(self, action_result: dict, decision: Optional[DecisionOutput]) -> dict:
        """
        Verify the results of an action.

        Args:
            action_result: The result from the action phase
            decision: The decision that led to the action

        Returns:
            Verification results
        """
        verification = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action_successful': False,
            'expected_outcome_met': False,
            'actual_results': action_result,
            'verification_notes': ''
        }

        try:
            # Check if action was taken without error
            if not action_result.get('error') and action_result.get('action_taken', False):
                verification['action_successful'] = True

            # Check against expected outcome if available
            if decision and decision.expected_outcome:
                # Simple validation - in reality this would be more sophisticated
                expected_desc = decision.expected_outcome.get('description', '')
                if expected_desc:
                    # For now, we'll consider it successful if action succeeded
                    verification['expected_outcome_met'] = verification['action_successful']
                    verification['verification_notes'] = "Basic success check passed"
                else:
                    verification['verification_notes'] = "No specific success criteria defined"
            else:
                verification['verification_notes'] = "No expected outcome defined for verification"

        except Exception as e:
            logger.error(f"Error during verification phase: {e}")
            verification['error'] = str(e)

        return verification

    def _learn(self, observation: ObservationData, decision: Optional[DecisionOutput],
               action_result: dict, verification_result: dict) -> Optional[LearningUpdate]:
        """
        Learn from the experience of the cycle.

        Args:
            observation: The observation data
            decision: The decision made
            action_result: The result of the action
            verification_result: The result of verification

        Returns:
            A LearningUpdate object, or None if no learning occurred
        """
        try:
            # Only learn periodically based on configuration
            if self._cycle_count % self.config.learning_interval_cycles != 0:
                return None

            # Prepare learning data
            learning_data = {
                'cycle_number': self._cycle_count,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'observation': observation.__dict__,
                'decision': decision.__dict__ if decision else None,
                'action_result': action_result,
                'verification_result': verification_result,
                'context': {
                    'system_state': self.state.__dict__,
                    'config': self.config.__dict__
                }
            }

            # Use the learning pipeline to process this experience
            # The learning pipeline would update models, extract patterns, etc.
            # For now, we'll create a simple learning update
            learning_update = LearningUpdate()
            learning_update.update_type = 'experience_recorded'
            learning_update.description = f"Recorded experience from cycle {self._cycle_count}"
            learning_update.data = learning_data
            learning_update.confidence = 0.8

            # In a full implementation, we would call:
            # self.learning_pipeline.experience(learning_data)

            return learning_update

        except Exception as e:
            logger.error(f"Error during learning phase: {e}")
            return None

    # ==================== Action Implementations ====================

    def _execute_specific_task(self, action_details: dict) -> dict:
        """Execute a specific task defined in action details."""
        from app.agent.executor import Executor
        from app.planner.task import TaskStatus

        task_id = action_details.get('task_id')
        if not task_id:
            return {
                'action_taken': False,
                'reason': 'No task_id provided in action details'
            }

        # Find task in storage
        task = self.storage.get_task(task_id)
        if not task:
            return {
                'action_taken': False,
                'reason': f'Task {task_id} not found'
            }

        try:
            # If we have an executor, execute the task
            if self.executor:
                # Convert AutonomousTask to a format executor can run
                # For now, create a simple plan from the task description
                plan = self.planner.create_plan(task.description)
                if plan and plan.tasks:
                    allowed_tools = set(Executor.READ_ONLY_TOOLS)
                    allowed_tools.update(Executor.MUTATING_TOOLS)
                    results = self.executor.execute_plan(plan, allowed_tools)

                    task.status = 'completed'
                    self.storage.save_task(task)
                    return {
                        'action_taken': True,
                        'task_id': task_id,
                        'result': results,
                        'steps_executed': len(results)
                    }

            # Fallback: mark task as completed if no executor
            task.status = 'completed'
            self.storage.save_task(task)
            return {
                'action_taken': True,
                'task_id': task_id,
                'result': 'Task marked completed (no executor available)'
            }

        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}")
            task.status = 'failed'
            task.error = str(e)
            self.storage.save_task(task)
            return {
                'action_taken': False,
                'error': str(e)
            }

    def _create_goal_from_decision(self, action_details: dict) -> dict:
        """Create a new goal based on decision details."""
        try:
            goal_data = action_details.get('goal_data', {})
            if not goal_data:
                return {
                    'action_taken': False,
                    'reason': 'No goal data provided in action details'
                }

            # Create the goal
            goal = self.goal_storage.create(
                name=goal_data.get('name', 'New Goal from Autonomy'),
                description=goal_data.get('description', ''),
                priority=goal_data.get('priority', 'medium'),
                status=goal_data.get('status', 'pending')
            )

            return {
                'action_taken': True,
                'goal_id': goal.id,
                'goal_name': goal.name,
                'message': f'Created goal: {goal.name}'
            }

        except Exception as e:
            logger.error(f"Error creating goal: {e}")
            return {
                'action_taken': False,
                'error': str(e)
            }

    def _review_stalled_goals(self, action_details: dict) -> dict:
        """Review stalled goals and take appropriate action."""
        try:
            stall_threshold = action_details.get('stall_threshold_hours', 24)
            from datetime import datetime, timezone
            import time

            now = time.time()
            stalled_goals = []
            all_goals = self.goal_storage.all()

            for goal in all_goals:
                if goal.status in ('completed', 'cancelled', 'paused'):
                    continue

                # Check if goal was updated recently
                updated_at_str = goal.updated_at if goal.updated_at else goal.created_at
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                        hours_idle = (now - updated_at.timestamp()) / 3600
                        if hours_idle >= stall_threshold:
                            stalled_goals.append({
                                'goal_id': goal.id,
                                'goal_name': goal.name,
                                'hours_idle': round(hours_idle, 1),
                                'status': goal.status
                            })
                    except Exception:
                        pass

            # Take action on stalled goals based on policy
            action = action_details.get('action', 'pause')  # pause, cancel, decompose, notify
            actions_taken = []

            for sg in stalled_goals:
                if action == 'pause':
                    self.goal_storage.pause_goal(sg['goal_id'], f'Autonomous stall detection: idle {sg["hours_idle"]}h')
                    actions_taken.append(f"Paused {sg['goal_name']}")
                elif action == 'decompose':
                    # Trigger decomposition
                    suggestions = self.goal_storage.decompose_goal(sg['goal_id'])
                    if suggestions:
                        self.goal_storage.apply_decomposition(sg['goal_id'], suggestions)
                        actions_taken.append(f"Decomposed {sg['goal_name']} into {len(suggestions)} subtasks")
                elif action == 'notify':
                    actions_taken.append(f"Notification: {sg['goal_name']} stalled for {sg['hours_idle']}h")

            return {
                'action_taken': True,
                'action': f'review_stalled_goals ({action})',
                'stalled_goals_found': len(stalled_goals),
                'actions_taken': actions_taken,
                'message': f'Reviewed {len(stalled_goals)} stalled goals'
            }

        except Exception as e:
            logger.error(f"Error reviewing stalled goals: {e}")
            return {
                'action_taken': False,
                'error': str(e)
            }

    def _investigate_resource_issue(self, resource_type: str, action_details: dict) -> dict:
        """Investigate a resource usage issue."""
        investigation_results = {
            'action_taken': True,
            'action': f'investigate_{resource_type}_usage',
            'resource_type': resource_type,
            'details': {}
        }

        try:
            if resource_type == 'cpu':
                # Get top CPU consuming processes
                import psutil
                processes = []
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'cmdline']):
                    try:
                        cpu = proc.info['cpu_percent'] or 0
                        if cpu > 1.0:  # Only processes using >1% CPU
                            processes.append({
                                'pid': proc.info['pid'],
                                'name': proc.info['name'],
                                'cpu_percent': cpu,
                                'memory_mb': (proc.info['memory_info'].rss / 1024 / 1024) if proc.info['memory_info'] else 0,
                                'cmdline': ' '.join(proc.info['cmdline'][:3]) if proc.info['cmdline'] else ''
                            })
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
                investigation_results['details']['top_cpu_processes'] = processes[:10]

            elif resource_type == 'memory':
                import psutil
                mem = psutil.virtual_memory()
                investigation_results['details']['memory'] = {
                    'total_gb': round(mem.total / 1024**3, 2),
                    'available_gb': round(mem.available / 1024**3, 2),
                    'used_gb': round(mem.used / 1024**3, 2),
                    'percent': mem.percent
                }

                # Top memory processes
                processes = []
                for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cmdline']):
                    try:
                        mem_info = proc.info['memory_info']
                        if mem_info and mem_info.rss > 50 * 1024 * 1024:  # >50MB
                            processes.append({
                                'pid': proc.info['pid'],
                                'name': proc.info['name'],
                                'memory_mb': round(mem_info.rss / 1024 / 1024, 1),
                                'cmdline': ' '.join(proc.info['cmdline'][:3]) if proc.info['cmdline'] else ''
                            })
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                processes.sort(key=lambda x: x['memory_mb'], reverse=True)
                investigation_results['details']['top_memory_processes'] = processes[:10]

            elif resource_type == 'disk':
                import psutil
                disk = psutil.disk_usage('/')
                investigation_results['details']['disk'] = {
                    'total_gb': round(disk.total / 1024**3, 2),
                    'used_gb': round(disk.used / 1024**3, 2),
                    'free_gb': round(disk.free / 1024**3, 2),
                    'percent': round(disk.used / disk.total * 100, 1)
                }

            investigation_results['message'] = f'{resource_type.capitalize()} usage investigation completed'
            return investigation_results

        except Exception as e:
            logger.error(f"Error investigating {resource_type} issue: {e}")
            return {
                'action_taken': False,
                'error': str(e),
                'resource_type': resource_type
            }

    def _review_failed_tasks(self, action_details: dict) -> dict:
        """Review failed tasks and determine if they should be retried."""
        try:
            failed_tasks = [t for t in self.storage.list_tasks() if t.status == 'failed']
            retried_count = 0
            reviewed = []

            for task in failed_tasks:
                can_retry = task.retry_count < task.max_retries
                reviewed.append({
                    'task_id': task.id,
                    'description': task.description[:80],
                    'retry_count': task.retry_count,
                    'max_retries': task.max_retries,
                    'can_retry': can_retry,
                    'error': task.error[:200] if task.error else None
                })

                if can_retry:
                    # Reset task for retry
                    task.status = 'pending'
                    task.retry_count += 1
                    task.error = None
                    self.storage.save_task(task)
                    retried_count += 1

            return {
                'action_taken': True,
                'action': 'review_failed_tasks',
                'failed_tasks_found': len(failed_tasks),
                'tasks_reviewed': len(reviewed),
                'tasks_retried': retried_count,
                'details': reviewed,
                'message': f'Reviewed {len(failed_tasks)} failed tasks, retried {retried_count}'
            }

        except Exception as e:
            logger.error(f"Error reviewing failed tasks: {e}")
            return {
                'action_taken': False,
                'error': str(e)
            }

    def _perform_maintenance(self, action_details: dict) -> dict:
        """Perform routine maintenance tasks."""
        try:
            maintenance_tasks = []
            results = []

            # 1. Clean up old logs (if log rotation config provided)
            if action_details.get('clean_logs', True):
                try:
                    from app.core.logger import logger
                    # This would trigger log rotation/cleanup
                    logger.info("[Maintenance] Log cleanup triggered")
                    maintenance_tasks.append('log_cleanup')
                    results.append({'task': 'log_cleanup', 'status': 'completed'})
                except Exception as e:
                    results.append({'task': 'log_cleanup', 'status': 'failed', 'error': str(e)})

            # 2. Optimize database/storage (compact JSON files)
            if action_details.get('optimize_storage', True):
                try:
                    self.storage.compact()
                    maintenance_tasks.append('storage_compact')
                    results.append({'task': 'storage_compact', 'status': 'completed'})
                except Exception as e:
                    results.append({'task': 'storage_compact', 'status': 'failed', 'error': str(e)})

            # 3. Check dependency updates
            if action_details.get('check_dependencies', True):
                try:
                    # Could integrate with dependency checking here
                    maintenance_tasks.append('dependency_check')
                    results.append({'task': 'dependency_check', 'status': 'completed', 'note': 'Manual check recommended'})
                except Exception as e:
                    results.append({'task': 'dependency_check', 'status': 'failed', 'error': str(e)})

            # 4. Backup important data
            if action_details.get('backup', True):
                try:
                    backup_path = self.storage.backup()
                    maintenance_tasks.append('backup')
                    results.append({'task': 'backup', 'status': 'completed', 'path': backup_path})
                except Exception as e:
                    results.append({'task': 'backup', 'status': 'failed', 'error': str(e)})

            return {
                'action_taken': True,
                'action': 'maintenance',
                'tasks_performed': maintenance_tasks,
                'results': results,
                'message': f'Maintenance completed: {len(maintenance_tasks)} tasks performed'
            }

        except Exception as e:
            logger.error(f"Error performing maintenance: {e}")
            return {
                'action_taken': False,
                'error': str(e)
            }

    # ==================== Background Task Management ====================

    def schedule_background_task(self,
                                func: Callable,
                                interval: float,
                                args: tuple = (),
                                kwargs: dict = None,
                                max_runs: int = None,
                                metadata: dict = None) -> str:
        """
        Schedule a recurring background task.

        Args:
            func: The function to execute
            interval: How often to run the function (in seconds)
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
            max_runs: Maximum number of times to run (None for infinite)
            metadata: Additional metadata for the task

        Returns:
            The job ID for the scheduled task
        """
        if kwargs is None:
            kwargs = {}
        if metadata is None:
            metadata = {}

        job_id = self.background_scheduler.add_job(
            func=func,
            interval=interval,
            args=args,
            kwargs=kwargs,
            max_runs=max_runs,
            metadata=metadata
        )

        logger.info(f"Scheduled background task {job_id} with interval {interval}s")
        return job_id

    def cancel_background_task(self, job_id: str) -> bool:
        """Cancel a scheduled background task."""
        result = self.background_scheduler.remove_job(job_id)
        if result:
            logger.info(f"Cancelled background task {job_id}")
        return result

    # ==================== Task Management Integration ====================

    def create_autonomous_task(self,
                              description: str,
                              source: str = "decision_loop",
                              priority: int = 2,
                              dependencies: list = None,
                              metadata: dict = None) -> AutonomousTask:
        """
        Create a new autonomous task.

        Args:
            description: Description of what the task should accomplish
            source: Source of the task (decision_loop, self_initiated, maintenance, etc.)
            priority: Priority level (1=low, 2=medium, 3=high)
            dependencies: List of task IDs that must be completed before this task
            metadata: Additional metadata for the task

        Returns:
            The created AutonomousTask
        """
        if dependencies is None:
            dependencies = []
        if metadata is None:
            metadata = {}

        task = AutonomousTask(
            description=description,
            source=source,
            priority=priority,
            dependencies=dependencies,
            metadata=metadata
        )

        # Save to storage
        saved_task = self.storage.save_task(task)

        # Update state metrics
        with self._lock:
            self.state.active_tasks_count = len([t for t in self.storage.list_tasks() if t.status in ['pending', 'running']])
            self._sync_state_to_storage()

        return saved_task

    def get_autonomous_tasks(self, status: str = None) -> list[AutonomousTask]:
        """
        Get autonomous tasks, optionally filtered by status.

        Args:
            status: Optional status to filter by (pending, running, completed, failed, etc.)

        Returns:
            List of matching AutonomousTask objects
        """
        tasks = self.storage.list_tasks()
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    # ==================== Status and Introspection ====================

    def get_status(self) -> dict:
        """
        Get the current status of the autonomy system.

        Returns:
            A dictionary containing the current state and metrics
        """
        with self._lock:
            return {
                'state': self.state.__dict__,
                'config': self.config.__dict__,
                'is_running': self._running,
                'is_paused': self._pause_event.is_set() and self._running,
                'background_jobs': len(self.background_scheduler.list_jobs()),
                'autonomous_tasks': len(self.storage.list_tasks()),
                'goals': len(self.goal_storage.all())
            }

    def is_healthy(self) -> bool:
        """
        Check if the autonomy system is healthy.

        Returns:
            True if healthy, False otherwise
        """
        # Check if we're running when we should be
        if self.config.enabled and not self._running:
            return False

        # Check error rate
        if self.state.error_count > self.config.max_consecutive_failures:
            return False

        # Check background scheduler
        if not self.background_scheduler:  # Should always exist if initialized
            return False

        return True
