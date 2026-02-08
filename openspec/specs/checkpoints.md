# Spec: Checkpoint Models

## Capability: workflow-checkpoints

### Requirement: CheckpointKind enum (REQ-1)
**Given** the workflow needs extensible checkpoint types
**When** defining checkpoint kinds
**Then** `CheckpointKind` is a `str, Enum` with values `strategy_confirmation`, `result_review`

**PBT**: Every `CheckpointKind` member has a corresponding payload model class.

### Requirement: DecisionAction enum (REQ-2)
**Given** checkpoint handlers return decisions
**When** defining decision actions
**Then** `DecisionAction` is a `str, Enum` with values `approve`, `edit`, `reject`

### Requirement: StrategyPayload model (REQ-3)
**Given** checkpoint 1 needs strategy context
**When** building STRATEGY_CONFIRMATION checkpoint
**Then** payload contains `intent: ParsedIntent`, `strategy: SearchStrategy`, `iteration: int`

### Requirement: ResultPayload model (REQ-4)
**Given** checkpoint 2 needs result context
**When** building RESULT_REVIEW checkpoint
**Then** payload contains `collection: PaperCollection`, `accumulated_papers: list[Paper]`, `iteration: int`

### Requirement: Checkpoint model (REQ-5)
**Given** checkpoints carry typed data
**When** constructing a checkpoint
**Then** `Checkpoint` has: `kind: CheckpointKind`, `payload: StrategyPayload | ResultPayload`, `run_id: str`, `iteration: int`, `timestamp: str`
**And** `timestamp` defaults to current UTC ISO 8601

### Requirement: Decision model (REQ-6)
**Given** handlers return decisions
**When** constructing a decision
**Then** `Decision` has: `action: DecisionAction`, `revised_data: Any = None`, `note: str | None = None`

### Requirement: CheckpointHandler protocol (REQ-7)
**Given** the handler must be product-form agnostic
**When** defining the handler interface
**Then** `CheckpointHandler` is a `Protocol` with single method `async def handle(self, checkpoint: Checkpoint) -> Decision`

**PBT**: Any class implementing `async handle(Checkpoint) -> Decision` satisfies the protocol.

---

## Properties

| ID | Property | Invariant | Falsification |
|----|----------|-----------|---------------|
| PROP-1 | Checkpoint kind/payload consistency | STRATEGY_CONFIRMATION always pairs with StrategyPayload; RESULT_REVIEW always pairs with ResultPayload | Construct mismatched kind+payload, verify engine rejects or never produces |
| PROP-2 | Decision action exhaustive | Every DecisionAction value has defined behavior in the workflow | Remove a case from match statement, verify test fails |
| PROP-3 | Timestamp auto-generated | Checkpoint.timestamp is always a valid ISO 8601 string | Create checkpoint, parse timestamp |
