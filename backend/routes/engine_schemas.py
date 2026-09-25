"""V2-01 — Typed public response DTOs for the 6 Intelligence Engines (arroba.v2).

These models document the 200 responses of the frozen v1 engines WITHOUT changing runtime
behaviour: they are attached via `responses={200: {"model": ...}}` (never `response_model=`),
so the engines keep returning their raw dicts unchanged. `extra="allow"` keeps them
forward-compatible and guarantees they never filter runtime output.

Derived faithfully from real runtime samples (tools/runtime_samples.json). Names are unique
to avoid any collision with the frozen v1 request-schema components.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


# ── Shared sub-models ────────────────────────────────────────────────────────
class SubjectRef(_Base):
    master_id: str
    name: Optional[str] = None


class IdentityBrief(_Base):
    name: Optional[str] = None
    cnae_code: Optional[str] = None
    cnae_section: Optional[str] = None
    provincia: Optional[str] = None


class EvidenceVersionRef(_Base):
    master: Optional[str] = None
    financial: Optional[str] = None
    signal: Optional[str] = None
    semantic: Optional[str] = None
    recommendation: Optional[str] = None
    strategy: Optional[str] = None
    knowledge_graph: Optional[str] = None
    transaction_os: Optional[str] = None


class ConfidenceScore(_Base):
    value: Optional[float] = None
    factors: Optional[Any] = None


class GraphEdge(_Base):
    from_: Optional[str] = Field(None, alias="from")
    to: Optional[str] = None
    relation: Optional[str] = None
    event: Optional[str] = None


# ── Financial Intelligence ───────────────────────────────────────────────────


class ValuationPackageSummary(_Base):
    currency: str = "EUR"
    as_of: Optional[Any] = None
    enterprise_value: Optional[float] = None
    enterprise_value_range: Optional[Dict[str, float]] = None
    equity_value: Optional[float] = None
    equity_value_range: Optional[Dict[str, float]] = None
    equity_value_available: bool = False


class ValuationPackageMethods(_Base):
    applied: List[Dict[str, Any]] = Field(default_factory=list)
    excluded: List[Dict[str, Any]] = Field(default_factory=list)


class ValuationPackageConfidence(_Base):
    score: float = 0.0
    grade: str = "screen_grade"
    weighting_rule: Optional[str] = None
    method_count: int = 0


class ValuationPackage(_Base):
    contract_version: str
    status: str
    summary: ValuationPackageSummary
    methods: ValuationPackageMethods
    scenarios: Dict[str, Any]
    assumptions: Dict[str, Any]
    comparables: Dict[str, Any]
    sensitivity: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: ValuationPackageConfidence
    warnings: List[str] = Field(default_factory=list)
    methodology_narrative: List[str] = Field(default_factory=list)
    sources_and_versions: Dict[str, Any]


class ValuationBlock(_Base):
    method: Optional[str] = None
    multiple: Optional[float] = None
    multiple_basis: Optional[str] = None
    enterprise_value: Optional[float] = None
    equity_value: Optional[float] = None
    range: Optional[Dict[str, Any]] = None
    confidence: Optional[Any] = None
    hypotheses: Optional[List[Any]] = None
    lineage: Optional[Dict[str, Any]] = None
    dcf: Optional[Dict[str, Any]] = None


class FinancialAnalyzeResponse(_Base):
    master_id: str
    cif_normalized: Optional[str] = None
    identity: Optional[IdentityBrief] = None
    has_financials: Optional[bool] = None
    statements: Optional[Dict[str, Any]] = None
    statements_history: Optional[list[Dict[str, Any]]] = None
    kpis: Optional[Dict[str, Optional[float]]] = None
    ratios: Optional[Dict[str, Any]] = None
    evolution: Optional[Dict[str, Any]] = None
    financial_quality: Optional[Dict[str, Any]] = None
    comparables: Optional[Dict[str, Any]] = None
    valuation: Optional[ValuationBlock] = None
    assessment: Optional[Dict[str, Any]] = None
    explainability: Optional[Dict[str, Any]] = None
    engine_version: Optional[str] = None
    generated_at: Optional[str] = None
    confidence: Optional[float] = None


class FinancialValuationResponse(_Base):
    master_id: str
    cif_normalized: Optional[str] = None
    valuation: Optional[ValuationBlock] = None
    engine_version: Optional[str] = None
    generated_at: Optional[str] = None


class ValuationPackageResponse(_Base):
    master_id: str
    cif_normalized: Optional[str] = None
    valuation: ValuationPackage
    engine_version: Optional[str] = None
    generated_at: Optional[str] = None


class RatioDef(_Base):
    key: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    formula: Optional[str] = None
    explanation: Optional[str] = None


class RatiosCatalogResponse(_Base):
    ratios: List[RatioDef] = Field(default_factory=list)
    source: Optional[str] = None


# ── Signal Intelligence ──────────────────────────────────────────────────────
class SignalItem(_Base):
    signal_id: str
    master_id: Optional[str] = None
    signal_type: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    polarity: Optional[str] = None
    dimensions: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    detected_at: Optional[str] = None
    is_composite: Optional[bool] = None
    source: Optional[Any] = None
    evidence: Optional[Any] = None
    rule: Optional[Any] = None
    recommended_actions: Optional[List[str]] = None


class SignalScore(_Base):
    signal_score: Optional[float] = None
    aggregate_dimensions: Optional[Dict[str, Any]] = None
    method: Optional[str] = None
    formula_version: Optional[str] = None


class SignalAnalyzeResponse(_Base):
    master_id: str
    cif_normalized: Optional[str] = None
    identity: Optional[IdentityBrief] = None
    signals: List[SignalItem] = Field(default_factory=list)
    score: Optional[SignalScore] = None
    counts_by_category: Optional[Dict[str, int]] = None
    dependencies: Optional[List[str]] = None
    windows_evaluated: Optional[List[str]] = None
    engine_version: Optional[str] = None
    taxonomy_version: Optional[str] = None
    thresholds_version: Optional[str] = None
    actions_version: Optional[str] = None
    composites_version: Optional[str] = None
    generated_at: Optional[str] = None
    confidence: Optional[float] = None


class SignalAggregateResponse(_Base):
    criteria: Optional[Dict[str, Optional[str]]] = None
    companies_analyzed: Optional[int] = None
    counts_by_category: Optional[Dict[str, int]] = None
    counts_by_type: Optional[Dict[str, int]] = None
    top_opportunities: List[Any] = Field(default_factory=list)
    engine_version: Optional[str] = None


class SignalOpportunitiesResponse(_Base):
    sorted_by: Optional[str] = None
    count: Optional[int] = None
    opportunities: List[Any] = Field(default_factory=list)
    engine_version: Optional[str] = None


class SignalCatalogResponse(_Base):
    taxonomy_version: Optional[str] = None
    thresholds_version: Optional[str] = None
    actions_version: Optional[str] = None
    composites_version: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    signal_types: List[Dict[str, Any]] = Field(default_factory=list)
    canonical_actions: List[str] = Field(default_factory=list)
    composites: List[Dict[str, Any]] = Field(default_factory=list)


class SignalHistoryResponse(_Base):
    master_id: str
    signals: List[Dict[str, Any]] = Field(default_factory=list)


class SignalRecord(_Base):
    signal_id: str


# ── Semantic Intelligence ────────────────────────────────────────────────────
class SemanticProfileResponse(_Base):
    master_id: str
    cif_normalized: Optional[str] = None
    profile_version: Optional[str] = None
    identity: Optional[IdentityBrief] = None
    semantic_profile: Optional[Dict[str, Any]] = None
    semantic_summary: Optional[Dict[str, Any]] = None
    coverage: Optional[Dict[str, Any]] = None
    embedding: Optional[Dict[str, Any]] = None
    lineage: Optional[Dict[str, Any]] = None
    engine_version: Optional[str] = None
    generated_at: Optional[str] = None
    confidence: Optional[float] = None


class SemanticEmbeddingResponse(_Base):
    master_id: str
    embedding: Optional[Dict[str, Any]] = None
    profile_checksum: Optional[str] = None
    engine_version: Optional[str] = None


class SemanticSimilarResponse(_Base):
    master_id: str
    count: Optional[int] = None
    similar: List[Any] = Field(default_factory=list)
    backend: Optional[str] = None
    blocking: Optional[Dict[str, Any]] = None
    engine_version: Optional[str] = None


class SearchHit(_Base):
    master_id: str
    cif: Optional[str] = None
    name: Optional[str] = None
    cnae_section: Optional[str] = None
    score: Optional[float] = None
    summary: Optional[dict] = None


class SemanticSearchResponse(_Base):
    query: Optional[str] = None
    count: Optional[int] = None
    results: List[SearchHit] = Field(default_factory=list)
    backend: Optional[str] = None
    embedding_model: Optional[str] = None
    engine_version: Optional[str] = None


class SemanticProfileSchemaResponse(_Base):
    profile_version: Optional[str] = None
    dimensions: List[str] = Field(default_factory=list)
    dimension_count: Optional[int] = None
    status_values: List[str] = Field(default_factory=list)
    methods: List[str] = Field(default_factory=list)
    embedding_sources: List[str] = Field(default_factory=list)


class SemanticCatalogResponse(_Base):
    engine_version: Optional[str] = None
    profile_version: Optional[str] = None
    embedding_version: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    vector_search_backend: Optional[str] = None
    dimensions: List[str] = Field(default_factory=list)
    scope_v1: List[str] = Field(default_factory=list)
    deferred: List[str] = Field(default_factory=list)


# ── Recommendation Intelligence ──────────────────────────────────────────────
class RecommendationItem(_Base):
    recommendation_id: Optional[str] = None
    target: Optional[Any] = None
    candidate: Optional[Any] = None
    recommendation_type: Optional[str] = None
    recommendation_role: Optional[str] = None
    score: Optional[float] = None
    fit_dimensions: Optional[Dict[str, Any]] = None
    score_method: Optional[str] = None
    composed_of: Optional[List[Any]] = None
    graph_edges: Optional[List[Any]] = None
    evidence: Optional[Any] = None
    confidence: Optional[Any] = None
    explanation: Optional[Any] = None
    recommended_actions: Optional[List[str]] = None


class RecommendationExplainResponse(RecommendationItem):
    recommendation_method: Optional[str] = None
    recommendation_version: Optional[str] = None
    evidence_version: Optional[EvidenceVersionRef] = None
    engines_used: Optional[List[str]] = None
    generated_at: Optional[str] = None


class RecommendationSetResponse(_Base):
    target: Optional[SubjectRef] = None
    recommendation_type: Optional[str] = None
    status: Optional[str] = None
    count: Optional[int] = None
    recommendations: List[RecommendationItem] = Field(default_factory=list)
    method: Optional[str] = None
    recommendation_version: Optional[str] = None
    evidence_version: Optional[EvidenceVersionRef] = None
    generated_at: Optional[str] = None


class RecommendationUnavailableResponse(_Base):
    recommendation_type: Optional[str] = None
    status: Optional[str] = None
    reason: Optional[str] = None
    recommendations: List[Any] = Field(default_factory=list)
    recommendation_version: Optional[str] = None
    generated_at: Optional[str] = None


class RecommendationMatchingResponse(_Base):
    a: Optional[SubjectRef] = None
    b: Optional[SubjectRef] = None
    recommendation_type: Optional[str] = None
    match: Optional[RecommendationItem] = None
    recommendation_version: Optional[str] = None
    generated_at: Optional[str] = None


class RecommendationMemoryResponse(_Base):
    count: Optional[int] = None
    memory: List[Any] = Field(default_factory=list)


class RecommendationFeedbackResponse(_Base):
    recommendation_id: Optional[str] = None
    event: Optional[str] = None


class RecommendationCatalogResponse(_Base):
    engine_version: Optional[str] = None
    recommendation_method: Optional[str] = None
    weights: Optional[Dict[str, Any]] = None
    fit_dimensions: List[str] = Field(default_factory=list)
    recommendation_types: List[str] = Field(default_factory=list)
    recommendation_roles: List[Optional[str]] = Field(default_factory=list)
    available_types: List[str] = Field(default_factory=list)
    unavailable_types: Optional[Dict[str, Any]] = None
    canonical_actions: List[str] = Field(default_factory=list)
    actions_version: Optional[str] = None
    evidence_version: Optional[EvidenceVersionRef] = None
    lifecycle_states: List[str] = Field(default_factory=list)
    feedback_events: List[str] = Field(default_factory=list)
    deferred: List[str] = Field(default_factory=list)


# ── Strategy Intelligence ────────────────────────────────────────────────────
class ThesisAlternative(_Base):
    thesis_type: Optional[str] = None
    statement: Optional[str] = None
    score: Optional[float] = None
    why_not_preferred: Optional[str] = None


class StrategyThesisResponse(_Base):
    thesis_id: str
    thesis_type: Optional[str] = None
    status: Optional[str] = None
    company_master_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    subject: Optional[SubjectRef] = None
    statement: Optional[str] = None
    rationale: Optional[List[str]] = None
    narrative_method: Optional[str] = None
    hypotheses: Optional[List[Any]] = None
    time_horizon: Optional[Dict[str, Any]] = None
    strategic_dimensions: Optional[Dict[str, Any]] = None
    score: Optional[float] = None
    constraints: Optional[List[str]] = None
    recommendation_ids: Optional[List[str]] = None
    signal_ids: Optional[List[str]] = None
    semantic_profile_version: Optional[str] = None
    financial_snapshot_version: Optional[str] = None
    evidence_tree: Optional[Dict[str, Any]] = None
    graph_edges: Optional[List[Any]] = None
    recommended_actions: Optional[List[str]] = None
    confidence: Optional[ConfidenceScore] = None
    owner: Optional[str] = None
    converts_to: Optional[str] = None
    representation: Optional[Dict[str, Any]] = None
    strategy_version: Optional[str] = None
    strategy_method: Optional[str] = None
    engines_used: Optional[List[str]] = None
    recommendation_version: Optional[str] = None
    evidence_version: Optional[EvidenceVersionRef] = None
    generated_at: Optional[str] = None
    lifecycle: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    alternatives: Optional[List[ThesisAlternative]] = None
    preferred_rationale: Optional[str] = None


class StrategyScenariosResponse(_Base):
    subject: Optional[SubjectRef] = None
    scenario_types_requested: Optional[List[str]] = None
    scenarios: List[Dict[str, Any]] = Field(default_factory=list)
    decision_support: Optional[Dict[str, Any]] = None
    strategy_version: Optional[str] = None
    generated_at: Optional[str] = None


class StrategyDecisionResponse(_Base):
    subject: Optional[Dict[str, Any]] = None
    preferred: Optional[str] = None
    alternative: Optional[str] = None
    comparison: Optional[Dict[str, Any]] = None
    theses: Optional[Dict[str, Any]] = None
    strategy_version: Optional[str] = None
    generated_at: Optional[str] = None


class StrategyMemoryResponse(_Base):
    theses: List[Dict[str, Any]] = Field(default_factory=list)


class StrategyCatalogResponse(_Base):
    engine_version: Optional[str] = None
    strategy_method: Optional[str] = None
    weights: Optional[Dict[str, Any]] = None
    thesis_types: List[str] = Field(default_factory=list)
    strategic_dimensions: List[str] = Field(default_factory=list)
    default_scenarios: List[str] = Field(default_factory=list)
    lifecycle_states: List[str] = Field(default_factory=list)
    convert_targets: List[str] = Field(default_factory=list)
    canonical_actions: List[str] = Field(default_factory=list)
    evidence_version: Optional[EvidenceVersionRef] = None
    canonical_entity: Optional[str] = None


class StrategyConvertResponse(_Base):
    thesis_id: Optional[str] = None
    converts_to: Optional[str] = None


# ── Transaction Intelligence ─────────────────────────────────────────────────
class StageState(_Base):
    stage: Optional[str] = None
    state: Optional[str] = None
    milestones: Optional[List[Any]] = None
    entered_at: Optional[str] = None


class TransactionRecord(_Base):
    transaction_id: str
    organization_id: Optional[str] = None
    visibility: Optional[str] = None
    from_thesis: Optional[str] = None
    target_master_id: Optional[str] = None
    parties: Optional[List[Any]] = None
    workflow_version: Optional[str] = None
    state_machine_version: Optional[str] = None
    os_version: Optional[str] = None
    state: Optional[str] = None
    current_stage: Optional[str] = None
    stages: Optional[List[StageState]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TransactionResponse(TransactionRecord):
    """Transaction query response (same shape as the canonical transaction record)."""


class TransactionEndpointResponse(_Base):
    """Polymorphic /transaction response: canonical record (query) or create wrapper."""
    transaction_id: Optional[str] = None
    organization_id: Optional[str] = None
    visibility: Optional[str] = None
    from_thesis: Optional[str] = None
    target_master_id: Optional[str] = None
    parties: Optional[List[Any]] = None
    workflow_version: Optional[str] = None
    state_machine_version: Optional[str] = None
    os_version: Optional[str] = None
    state: Optional[str] = None
    current_stage: Optional[str] = None
    stages: Optional[List[StageState]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    transaction: Optional[TransactionRecord] = None
    engine_version: Optional[str] = None
    generated_at: Optional[str] = None


class TransactionCreateResponse(_Base):
    transaction: Optional[TransactionRecord] = None
    from_thesis: Optional[str] = None
    engine_version: Optional[str] = None
    generated_at: Optional[str] = None


class WorkflowResponse(_Base):
    transaction_id: Optional[str] = None
    workflow_version: Optional[str] = None
    state_machine_version: Optional[str] = None
    stages: Optional[List[Any]] = None
    current_stage: Optional[str] = None
    version: Optional[str] = None
    side: Optional[str] = None


class StageResponse(_Base):
    current_stage: Optional[str] = None
    stages: Optional[List[StageState]] = None
    state: Optional[str] = None


class TaskItem(_Base):
    task_id: str
    transaction_id: Optional[str] = None
    title: Optional[str] = None
    stage: Optional[str] = None
    assignee: Optional[str] = None
    state: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class TaskResponse(_Base):
    tasks: Optional[List[TaskItem]] = None
    task_id: Optional[str] = None


class NextActionResponse(_Base):
    action_id: Optional[str] = None
    transaction_id: Optional[str] = None
    stage: Optional[str] = None
    action_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    high_risk: Optional[bool] = None
    requires_approval: Optional[bool] = None
    blockers: Optional[List[Any]] = None
    explainability: Optional[Dict[str, Any]] = None
    evidence_refs: Optional[Dict[str, Any]] = None
    recommended_actions: Optional[List[str]] = None
    confidence: Optional[ConfidenceScore] = None
    transaction_version: Optional[str] = None
    workflow_version: Optional[str] = None
    engines_used: Optional[List[str]] = None
    evidence_version: Optional[EvidenceVersionRef] = None
    generated_at: Optional[str] = None


class DealAsideResponse(_Base):
    active: Optional[bool] = None
    persona: Optional[str] = None
    role: Optional[str] = None
    transaction_id: Optional[str] = None
    stage: Optional[str] = None
    state: Optional[str] = None
    next_action: Optional[NextActionResponse] = None
    steps: Optional[List[Dict[str, Any]]] = None
    engine_version: Optional[str] = None
    evidence_version: Optional[EvidenceVersionRef] = None
    generated_at: Optional[str] = None


class TransactionRiskResponse(_Base):
    transaction_id: str
    stage: Optional[str] = None
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    blockers: Optional[List[Any]] = None
    engine_version: Optional[str] = None
    evidence_version: Optional[EvidenceVersionRef] = None
    generated_at: Optional[str] = None


class DocumentItem(_Base):
    document_id: str
    transaction_id: Optional[str] = None
    doc_key: Optional[str] = None
    doc_type: Optional[str] = None
    version: Optional[Any] = None
    content_hash: Optional[str] = None
    permissions: Optional[List[str]] = None
    state: Optional[str] = None
    created_at: Optional[str] = None


class DocumentsResponse(_Base):
    documents: Optional[List[DocumentItem]] = None
    document_id: Optional[str] = None


class ParticipantsResponse(_Base):
    transaction_id: str
    participants: List[Any] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)


class EventItem(_Base):
    event_id: str
    transaction_id: Optional[str] = None
    type: Optional[str] = None
    actor: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    at: Optional[str] = None


class TimelineResponse(_Base):
    transaction_id: str
    events: List[EventItem] = Field(default_factory=list)
    count: Optional[int] = None


class ApprovalItem(_Base):
    approval_id: str
    transaction_id: Optional[str] = None
    action: Optional[str] = None
    requested_by: Optional[str] = None
    decision: Optional[str] = None
    high_risk: Optional[bool] = None
    created_at: Optional[str] = None
    actor: Optional[str] = None
    artifact_version: Optional[str] = None
    decided_at: Optional[str] = None
    evidence_reviewed: Optional[List[Any]] = None
    role: Optional[str] = None


class TransactionDecisionResponse(_Base):
    approvals: Optional[List[ApprovalItem]] = None
    approval_id: Optional[str] = None


class TransactionMemoryResponse(_Base):
    transaction_id: str
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    documents: List[DocumentItem] = Field(default_factory=list)
    tasks: List[TaskItem] = Field(default_factory=list)
    approvals: List[ApprovalItem] = Field(default_factory=list)
    domain_events: List[Dict[str, Any]] = Field(default_factory=list)
    event_count: Optional[int] = None


class WorkspaceResponse(_Base):
    transaction: Optional[TransactionRecord] = None
    stages: Optional[List[StageState]] = None
    current_stage: Optional[str] = None
    tasks: Optional[List[TaskItem]] = None
    approvals: Optional[List[ApprovalItem]] = None
    documents: Optional[List[DocumentItem]] = None
    participants: Optional[List[Any]] = None
    timeline: Optional[List[EventItem]] = None
    next_action: Optional[Dict[str, Any]] = None
    engine_version: Optional[str] = None
    os_version: Optional[str] = None
    generated_at: Optional[str] = None


class TransactionCatalogResponse(_Base):
    engine_version: Optional[str] = None
    os_version: Optional[str] = None
    state_machine_version: Optional[str] = None
    workflow_templates: List[str] = Field(default_factory=list)
    stages_v1: List[str] = Field(default_factory=list)
    stages_deferred: List[str] = Field(default_factory=list)
    global_states: List[str] = Field(default_factory=list)
    terminal_states: List[str] = Field(default_factory=list)
    high_risk_actions: List[str] = Field(default_factory=list)
    domain_events: List[str] = Field(default_factory=list)
    transitions: List[Dict[str, Any]] = Field(default_factory=list)
    canonical_actions: List[str] = Field(default_factory=list)
    evidence_version: Optional[EvidenceVersionRef] = None
    action_types: List[str] = Field(default_factory=list)
    canonical_entities: Optional[str] = None
