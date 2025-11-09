from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from pydantic import ConfigDict

# Versions supported per the new spec
SchemaVer = Literal["tpa.run/0.2", "tpa.run/0.3"]


class EvidenceLink(BaseModel):
    id: str
    kind: str
    source_type: Literal["document", "policy", "spatial", "manual"]
    uri: str
    pointer: str
    hash: str
    hash_algo: Literal["sha256"] = "sha256"
    captured_at: str
    snippet: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class Case(BaseModel):
    id: str
    type: str
    lpa_code: Optional[str] = None
    reference: Optional[str] = None


class Site(BaseModel):
    id: str
    geometry: Optional[Dict[str, Any]] = None
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    geometry_ref: Optional[str] = None
    uprn: Optional[str] = None


class Document(BaseModel):
    id: str
    kind: str
    uri: str
    mime: Optional[str] = None


class Goal(BaseModel):
    id: str
    target: Optional[float] = None
    weight: float = 1.0


class ConsultationItem(BaseModel):
    id: str
    topic: Optional[str] = None
    text_ref: Optional[str] = None


class AssessmentEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: SchemaVer = Field(alias="schema")
    case: Case
    site: Site
    documents: List[Document] = []
    policy_scope: List[str] = []
    constraints_layers: List[str] = []
    goals: List[Goal] = []
    consultation: List[ConsultationItem] = []
    figures: List[Dict[str, Any]] = []
    client_run_id: Optional[str] = None
    options: Dict[str, Any] = {}


class PolicyFinding(BaseModel):
    policy_id: Optional[str] = None
    title: Optional[str] = None
    rag: Optional[Literal["red", "amber", "green", "n/a"]] = None
    explanation: Optional[str] = None
    evidence: List[EvidenceLink] = []
    citations: List[str] = []
    score: Optional[float] = None


class SpatialFinding(BaseModel):
    layer: str
    hit: bool
    impact: Optional[Literal["low", "med", "high"]] = None
    detail: Dict[str, Any] = {}
    feature_ids: List[str] = []
    geometry: Optional[Dict[str, Any]] = None
    bbox: Optional[List[float]] = None
    evidence: List[EvidenceLink] = []


class ChecklistItem(BaseModel):
    item: str
    status: Literal["pass", "fail", "n/a", "needs_review"]
    note: Optional[str] = None


class TraceStep(BaseModel):
    t: Literal[
        "retrieve_policy",
        "spatial_query",
        "doc_parse",
        "reason",
        "report_map",
        "overlay_emit",
        "tool_execute",
    ]
    at: Optional[str] = None
    tool: Optional[str] = None
    inputs_ref: Optional[str] = None
    outputs_ref: Optional[str] = None
    notes: Optional[str] = None


class KnowledgeBaseSnapshot(BaseModel):
    corpus_version: Optional[str] = None
    policy_docs: Optional[List[str]] = None
    spatial_registry: Optional[str] = None


class Trace(BaseModel):
    inputs_hash: str
    steps: List[TraceStep]
    model_ref: Optional[str] = None
    prompt_ref: Optional[str] = None
    kb_snapshot: Optional[KnowledgeBaseSnapshot] = None
    latency_ms: Optional[int] = None


class Recommendation(BaseModel):
    outcome: Optional[Literal["approve", "refuse", "seek_changes", "not_applicable"]] = None
    confidence: Optional[float] = None


class ArtifactRef(BaseModel):
    type: str
    uri: str
    size_bytes: Optional[int] = None
    meta: Optional[Dict[str, Any]] = None


class AssessmentResult(BaseModel):
    recommendation: Optional[Recommendation] = None
    policies: List[PolicyFinding] = []
    spatial: List[SpatialFinding] = []
    checklist: List[ChecklistItem] = []
    draft_report_md: Optional[str] = None
    report_template_id: Optional[str] = None
    report_fields: Dict[str, str] = {}
    report_field_provenance: Dict[str, List[EvidenceLink]] = {}
    artifacts: Dict[str, ArtifactRef] = {}
    trace: Trace


class ValidationErrorItem(BaseModel):
    path: str
    message: str


class ValidationResponse(BaseModel):
    ok: bool
    errors: List[ValidationErrorItem] = []
