# Safe Self-Improvement Architecture

The Safe Self-Improvement system provides production-safe autonomous modification capabilities for Freya. It ensures that all self-initiated code changes go through rigorous safety checks, human approval gates, and automatic rollback mechanisms.

## Overview

The system implements a defense-in-depth approach with multiple safety layers:

1. **File Allowlist/Denylist** - Controls which files can be modified
2. **Modification Boundaries** - Enforces limits on scope and size of changes
3. **Risk-Based Execution** - Integrates with RiskAnalyzer for risk assessment
4. **Human Approval Gates** - Requires approval for risky changes
5. **Improvement Prioritization** - Ranks improvements by impact/effort/risk
6. **Rollback Checkpoints** - Automatic rollback on failure
7. **Safe Patch Promotion** - Staged promotion with validation
8. **Policy Engine** - Declarative safety policies

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  SafeSelfImprovementEngine                  │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │  Allowlist  │  │ Boundaries  │  │  Risk       │          │
│  │  Manager    │  │  Manager    │  │  Executor   │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         │                │                │                 │
│  ┌──────▼────────────────▼────────────────▼──────┐          │
│  │              Policy Engine                     │          │
│  └──────┬──────────────────────────────────────┬──┘          │
│         │                                      │             │
│  ┌──────▼─────────────┐  ┌────────────────────▼──────┐       │
│  │  Prioritizer       │  │  Approval Gates           │       │
│  └────────────────────┘  └────────────┬──────────────┘       │
│                                       │                       │
│  ┌────────────────────────────────────▼──────────────┐       │
│  │              Execution & Verification             │       │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │       │
│  │  │  Rollback   │  │  Promotion  │  │ Verification│  │       │
│  │  │  Manager    │  │  Manager    │  │  Pipeline  │  │       │
│  │  └─────────────┘  └─────────────┘  └───────────┘  │       │
│  └───────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. File Allowlist/Denylist (`allowlist.py`)

Controls which files can be modified using pattern matching.

```python
from app.safe_self_improvement import AllowlistManager

manager = AllowlistManager()

# Allow source files
manager.add_allowlist("app/**/*.py", "Application source code")

# Deny secrets and config
manager.add_denylist("**/*.key", "Private keys", "Security")
manager.add_denylist("**/.env*", "Environment files", "Security")

# Check if file is allowed
allowed, reason = manager.check_file_allowed("app/core/config.py")
```

**Default Allowlist Patterns:**
- `app/**/*.py` - Application source
- `tests/**/*.py` - Tests
- `scripts/**/*.py` - Scripts
- `*.md`, `*.txt`, `*.json`, `*.yaml`, `*.yml`, `*.toml` - Documentation and config

**Default Denylist Patterns:**
- `**/__pycache__/**`, `**/.git/**`, `**/.venv/**`, `**/node_modules/**` - Cache and VCS
- `**/*.key`, `**/*.pem`, `**/*.crt`, `**/*.env*` - Secrets
- `**/secrets/**`, `**/credentials/**` - Credential directories
- `**/logs/**`, `**/output/**`, `**/dist/**`, `**/build/**` - Output directories

### 2. Modification Boundaries (`boundaries.py`)

Enforces limits on modifications:

```python
from app.safe_self_improvement import BoundaryManager, ModificationBoundary

boundary = ModificationBoundary(
    max_files_per_improvement=10,
    max_lines_per_modification=500,
    max_total_lines_per_improvement=2000,
    max_files_per_session=50,
    max_risk_level=RiskLevel.MEDIUM,
    allow_delete=False,
    allow_move=False,
)

manager = BoundaryManager(boundary=boundary)
valid, violations = manager.validate_candidate(candidate)
```

**Configurable Limits:**
- Files per improvement
- Lines per modification
- Total lines per improvement
- Session modification limit
- File size limit (1MB default)
- Allowed modification types (CREATE, MODIFY, RENAME by default)
- Allowed/forbidden file extensions
- Forbidden paths and patterns
- Forbidden content patterns (secrets, passwords, API keys)

### 3. Risk-Based Execution (`risk_execution.py`)

Integrates with RiskAnalyzer for risk assessment:

```python
from app.safe_self_improvement import RiskBasedExecutor
from app.risk import RiskAnalyzer

risk_analyzer = RiskAnalyzer()
executor = RiskBasedExecutor(
    risk_analyzer=risk_analyzer,
    auto_approve_max_risk=RiskLevel.LOW,
    require_human_approval_risk=RiskLevel.HIGH,
    require_verification_risk=RiskLevel.MEDIUM,
)

# Assess risk before execution
assessment = executor.assess_risk(candidate)
print(f"Overall risk: {assessment.overall_risk}")
print(f"Requires approval: {assessment.requires_approval}")
print(f"Requires verification: {assessment.requires_verification}")

# Execute with safeguards
result = executor.execute(candidate, approval_status="approved")
```

**Risk Levels and Actions:**
- **NONE/LOW**: Auto-approved, minimal verification
- **MEDIUM**: Requires verification, auto-approval possible
- **HIGH**: Requires human approval + verification
- **CRITICAL**: Denied by default, requires override

### 4. Approval Gates (`approval_gates.py`)

Manages human approval workflows:

```python
from app.safe_self_improvement import ApprovalGateManager
from app.decision import DecisionManager

decision_manager = DecisionManager()
approval_gates = ApprovalGateManager(decision_manager=decision_manager)

# Request approval
request = approval_gates.request_approval(candidate)

# Check status
if request.status == ApprovalStatus.PENDING:
    # Wait for human approval
    pass

# Approve/reject
approval_gates.approve(request.id, "reviewer", "Looks good")
approval_gates.reject(request.id, "reviewer", "Too risky")
```

**Approval Rules:**
- High risk (HIGH/CRITICAL) → requires approval
- Security category → requires approval
- Architecture changes → requires approval
- Many files (>5) → requires approval
- Low confidence (<0.7) → requires approval
- Delete operations → requires approval

### 5. Improvement Prioritization (`prioritization.py`)

Ranks improvements by multiple criteria:

```python
from app.safe_self_improvement import ImprovementPrioritizer, PrioritizationCriteria

criteria = PrioritizationCriteria(
    impact_weight=0.4,
    effort_weight=0.2,
    risk_weight=0.2,
    confidence_weight=0.2,
)

prioritizer = ImprovementPrioritizer(criteria)

results = prioritizer.prioritize(candidates, limit=10)
for result in results:
    print(f"{result.rank}. {result.candidate.title} - Score: {result.score:.2f}")
```

**Scoring Formula:**
```
score = (impact × 0.4) + (effort_inverted × 0.2) + (risk_inverted × 0.2) + (confidence × 0.2)
      × category_multiplier × source_multiplier
```

**Predefined Strategies:**
- `create_security_focused_prioritizer()` - Prioritizes security
- `create_performance_focused_prioritizer()` - Prioritizes performance
- `create_maintenance_prioritizer()` - Prioritizes tests/docs/deprecation
- `create_balanced_prioritizer()` - Default balanced approach

### 6. Rollback Checkpoints (`rollback.py`)

Automatic rollback on failure:

```python
from app.safe_self_improvement import RollbackManager, RollbackReason

rollback_manager = RollbackManager(checkpoint_dir="data/checkpoints")

# Create checkpoint before execution
checkpoint = rollback_manager.create_checkpoint(candidate, "Before execution")

# Execute...

# Rollback on failure
if not execution_result.success:
    result = rollback_manager.rollback(
        candidate.id,
        RollbackReason.VERIFICATION_FAILED,
        checkpoint.id
    )
```

**Automatic Rollback Triggers:**
- Verification failure
- Test failure
- Regression detected
- Human rejection
- Risk exceeded
- Policy violation
- System error
- Timeout

### 7. Safe Patch Promotion (`promotion.py`)

Staged promotion pipeline:

```python
from app.safe_self_improvement import PatchPromotionManager, PromotionStage
from app.core.safety_gates import SafetyPromotionGates

safety_gates = SafetyPromotionGates()
promotion_manager = PatchPromotionManager(safety_gates=safety_gates)

result = promotion_manager.promote(candidate, execution_result)
```

**Pipeline Stages:**
1. **Verification** - Safety gates evaluation
2. **Testing** - Full test suite + linting
3. **Canary** - Deploy to subset (configurable %)
4. **Production** - Final validation and recording

### 8. Policy Engine (`policies.py`)

Declarative safety policies:

```python
from app.safe_self_improvement import PolicyEngine, SelfImprovementPolicy, PolicyAction, PolicyCondition
from app.safe_self_improvement.models import RiskLevel, ImprovementCategory

policy_engine = PolicyEngine()

# Add custom policy
policy = SelfImprovementPolicy(
    id="custom_policy",
    name="Limit Database Migrations",
    description="Require approval for database migration files",
    scope=PolicyScope.FILE_PATTERN,
    conditions=[
        PolicyCondition("affected_files", "matches", "**/migrations/*.py"),
    ],
    action=PolicyAction.REQUIRE_APPROVAL,
    priority=75,
)
policy_engine.add_policy(policy)

# Evaluate
result = policy_engine.evaluate(candidate)
if result["requires_approval"]:
    # Request approval
    pass
```

**Default Policies:**
1. Deny CRITICAL risk
2. Require approval for HIGH risk
3. Require verification for MEDIUM+ risk
4. Deny delete operations
5. Limit large changes (>10 files)
6. Require approval for security changes
7. Require verification for architecture changes
8. Require approval for low confidence (<0.5)
9. Require verification for autonomous source

## Main Engine (`self_improvement.py`)

Orchestrates the complete pipeline:

```python
from app.safe_self_improvement import SafeSelfImprovementEngine, SafeSelfImprovementConfig

config = SafeSelfImprovementConfig(
    enable_allowlist=True,
    enable_denylist=True,
    max_files_per_improvement=10,
    max_lines_per_modification=500,
    auto_approve_max_risk=RiskLevel.LOW,
    require_human_approval_risk=RiskLevel.HIGH,
    min_confidence_for_auto_execute=0.8,
    require_rollback_checkpoint=True,
    auto_rollback_on_verification_failure=True,
    auto_rollback_on_test_failure=True,
    promotion_require_tests=True,
    promotion_require_lint=True,
    enforce_policies=True,
)

engine = SafeSelfImprovementEngine(config=config)

# Submit improvement
candidate = ImprovementCandidate(
    title="Fix bug in user authentication",
    description="Fixes edge case in token validation",
    category=ImprovementCategory.CORRECTNESS,
    modifications=[...],
    estimated_risk=RiskLevel.LOW,
    confidence=0.9,
)

result = engine.submit_improvement(candidate)

if result.queued:
    print("Awaiting approval...")
elif result.accepted:
    print("Executed successfully!")
```

## Configuration

### SafeSelfImprovementConfig

```python
@dataclass
class SafeSelfImprovementConfig:
    # Allowlist/Denylist
    enable_allowlist: bool = True
    enable_denylist: bool = True
    default_allowlist_paths: List[str] = [...]
    default_denylist_paths: List[str] = [...]

    # Boundaries
    max_files_per_improvement: int = 10
    max_lines_per_modification: int = 500
    max_total_modifications_per_session: int = 50

    # Risk thresholds
    auto_approve_max_risk: RiskLevel = RiskLevel.LOW
    require_human_approval_risk: RiskLevel = RiskLevel.HIGH
    max_concurrent_improvements: int = 1

    # Confidence thresholds
    min_confidence_for_auto_execute: float = 0.8
    min_confidence_for_approval_request: float = 0.5
    reject_below_confidence: float = 0.3

    # Prioritization weights
    impact_weight: float = 0.4
    effort_weight: float = 0.2
    risk_weight: float = 0.2
    confidence_weight: float = 0.2

    # Rollback
    require_rollback_checkpoint: bool = True
    auto_rollback_on_verification_failure: bool = True
    auto_rollback_on_test_failure: bool = True
    auto_rollback_on_regression: bool = True
    checkpoint_retention_hours: int = 24

    # Promotion
    promotion_require_tests: bool = True
    promotion_require_lint: bool = True
    promotion_require_no_regression: bool = True
    promotion_min_confidence: float = 0.75

    # Policy
    enforce_policies: bool = True
    policy_evaluation_on_submit: bool = True
    policy_evaluation_on_execute: bool = True

    # Timeouts
    approval_timeout_seconds: float = 300.0
    execution_timeout_seconds: float = 600.0
    verification_timeout_seconds: float = 300.0
```

## Integration with Existing Systems

The Safe Self-Improvement system reuses existing Freya components:

| Component | Reused From | Purpose |
|-----------|-------------|---------|
| RiskAnalyzer | `app/risk/risk_analyzer.py` | Risk assessment |
| DecisionManager | `app/decision/manager.py` | Structured decisions |
| RepairLoop | `app/verification/repair_loop.py` | Dry-run verification |
| PatchGenerator | `app/evaluation/patch_generator.py` | Patch creation |
| HumanOversightManager | `app/decision/human_oversight.py` | Human approval UI |
| PatchEngine | `app/editing/patch_engine.py` | Transactional patches |
| SafetyPromotionGates | `app/core/safety_gates.py` | Promotion evaluation |

## Usage Examples

### Basic Autonomous Improvement

```python
from app.safe_self_improvement import create_self_improvement_engine
from app.safe_self_improvement.models import ImprovementCandidate, FileModification, ModificationType, ImprovementCategory, RiskLevel

engine = create_self_improvement_engine()

# Create candidate
candidate = ImprovementCandidate(
    title="Add type hints to utils module",
    description="Improve type safety",
    category=ImprovementCategory.STYLE,
    source="autonomous",
    modifications=[
        FileModification(
            file_path="app/utils/helpers.py",
            modification_type=ModificationType.MODIFY,
            new_content='def helper(x: int) -> str:\n    return str(x)',
            description="Add type hints",
        )
    ],
    affected_files=["app/utils/helpers.py"],
    estimated_risk=RiskLevel.LOW,
    confidence=0.95,
)

# Submit for processing
result = engine.submit_improvement(candidate)

if result.accepted and not result.queued:
    print(f"Success! Execution: {result.risk_assessment}")
else:
    print(f"Queued for approval: {result.approval_request.id}")
```

### Manual Approval Workflow

```python
# Check pending approvals
pending = engine.get_pending_candidates()
for candidate in pending:
    print(f"Pending: {candidate.title}")

# Approve
success, msg = engine.approve_candidate(candidate.id, "senior_dev", "Approved after review")
```

### Policy Customization

```python
from app.safe_self_improvement import PolicyEngine, SelfImprovementPolicy, PolicyAction, PolicyCondition, PolicyScope

engine = create_self_improvement_engine()

# Add organization-specific policy
policy = SelfImprovementPolicy(
    id="org_require_review_for_public_api",
    name="Require Review for Public API Changes",
    description="Any changes to public API modules require senior review",
    scope=PolicyScope.FILE_PATTERN,
    conditions=[
        PolicyCondition("affected_files", "matches", "**/api/public/**"),
    ],
    action=PolicyAction.REQUIRE_APPROVAL,
    priority=90,
)
engine.policy_engine.add_policy(policy)
```

## Safety Guarantees

1. **No Unauthorized File Access** - Allowlist/denylist prevents modification of sensitive files
2. **Bounded Modifications** - Size and scope limits prevent runaway changes
3. **Risk-Aware Execution** - Every change assessed by RiskAnalyzer before execution
4. **Human-in-the-Loop** - High-risk changes require explicit approval
5. **Automatic Rollback** - Failed verifications/tests trigger immediate rollback
6. **Staged Promotion** - Changes validated at multiple stages before production
7. **Policy Enforcement** - Declarative policies ensure consistent safety rules
8. **Audit Trail** - Complete history of all evaluations, approvals, executions, rollbacks

## Monitoring and Observability

```python
# Get engine stats
stats = engine.get_stats()
print(f"Submitted: {stats['submitted']}, Succeeded: {stats['succeeded']}, Failed: {stats['failed']}")

# Get component stats
component_stats = engine.get_component_stats()
print(f"Allowlist checks: {component_stats['allowlist']['allowlist_checks']}")
print(f"Rollbacks: {component_stats['rollback_manager']['rollbacks_executed']}")

# Get recent executions
recent = engine.get_recent_executions(limit=10)
for exec_result in recent:
    print(f"{exec_result.candidate_id}: {'✓' if exec_result.success else '✗'}")
```

## Best Practices

1. **Start Restrictive** - Begin with strict boundaries and relax as confidence grows
2. **Monitor Metrics** - Track approval rates, rollback frequency, execution success
3. **Iterate Policies** - Adjust policies based on false positives/negatives
4. **Test Thoroughly** - Use dry-run mode extensively before enabling auto-execution
5. **Document Exceptions** - All overrides and policy exceptions should be documented
6. **Regular Audits** - Periodically review allowlist/denylist and policy effectiveness

## Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| "File not in allowlist" | File pattern not covered | Add pattern to allowlist |
| "Boundary violation: max files" | Too many files in candidate | Split into multiple candidates |
| "Risk too high: CRITICAL" | RiskAnalyzer detected critical issue | Review risk factors, fix underlying issue |
| "Approval timeout" | No approver responded | Increase timeout or add more approvers |
| "Verification failed" | Tests or lint failed | Fix code, re-run candidate |

### Debug Mode

Enable detailed logging:

```python
import logging
logging.getLogger("app.safe_self_improvement").setLevel(logging.DEBUG)
```