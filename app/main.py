import hashlib, time, orjson, json
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from .schemas import (
    AssessmentEnvelope,
    AssessmentResult,
    Trace,
    TraceStep,
    Recommendation,
    ValidationResponse,
    ValidationErrorItem,
    ChecklistItem,
    ArtifactRef,
)
from .settings import settings
from .security import require_auth

app = FastAPI(title="Agent Bridge", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.ALLOW_ORIGINS.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"ok": True}

def _hash_inputs(env: AssessmentEnvelope) -> str:
    # Stable hash of the envelope for trace (use aliases so 'schema' appears)
    b = orjson.dumps(env.model_dump(mode="json", by_alias=True), option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(b).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Meta ---

@app.get("/meta")
def meta():
    return {
        "api_version": "1.0.0",
        "schemas": ["tpa.run/0.2", "tpa.run/0.3"],
        "constraints_layers": ["flood_zones", "conservation", "listed_buildings"],
        "policy_scopes": ["local_plan:2024.10", "national:2023.06"],
        "report_templates": [{"id": "default", "fields": ["summary", "policies", "assessment", "conclusion"]}],
        "crs_policy": {"input": "EPSG:4326", "internal": "EPSG:27700", "output": "EPSG:4326"},
        "supports_vlm": False,
        "available_models": ["gpt-4o-mini", "llama3.1-70b"],
        "limits": {"max_doc_bytes": 20_000_000, "max_geom_vertices": 5000},
    }

@app.post("/validate", response_model=ValidationResponse)
async def validate(req: Request):
    body = await req.body()
    # New API uses bearer; we permit either bearer or HMAC in dev
    require_auth(req, body)
    env = AssessmentEnvelope.model_validate_json(body)
    errors: list[ValidationErrorItem] = []
    # Minimal structural checks
    if env.site.geometry is None and env.site.geometry_ref is None:
        errors.append(ValidationErrorItem(path="site.geometry", message="Provide geometry or geometry_ref"))
    # Example: ensure policy_scope strings look non-empty
    if any(not s for s in env.policy_scope):
        errors.append(ValidationErrorItem(path="policy_scope", message="Empty scope entry"))
    return ValidationResponse(ok=len(errors) == 0, errors=errors)

@app.post("/assess", response_model=AssessmentResult)
async def assess(req: Request):
    body = await req.body()
    require_auth(req, body)
    env = AssessmentEnvelope.model_validate_json(body)
    t0 = time.time()
    run_id = hashlib.sha1(_hash_inputs(env).encode()).hexdigest()[:16]
    
    # Generate more realistic mock assessment data
    case_ref = env.case.reference if env.case and hasattr(env.case, "reference") else "UNKNOWN"
    
    # Mock policy analysis
    from .schemas import PolicyFinding, SpatialFinding, EvidenceLink, ChecklistItem, KnowledgeBaseSnapshot
    
    policies = [
        PolicyFinding(
            policy_id="LP.H1",
            title="Residential Extensions and Alterations",
            rag="green",
            explanation="The proposed single-storey rear extension complies with policy LP.H1. The extension is within permitted limits and maintains adequate amenity space.",
            evidence=[
                EvidenceLink(
                    id="ev_lp_h1_1",
                    kind="policy",
                    source_type="policy",
                    uri="local_plan://section/h1/extensions",
                    pointer="/residential/rear_extensions",
                    hash=hashlib.md5(b"lp_h1_content").hexdigest(),
                    captured_at=_now_iso(),
                    snippet="Single storey rear extensions shall not exceed 4 meters in depth from the original dwelling...",
                    meta={"section": "H1.2", "page": 45}
                )
            ]
        ),
        PolicyFinding(
            policy_id="LP.D2",
            title="Design Quality",
            rag="amber",
            explanation="While the extension uses matching materials, the design could better reflect the character of the conservation area.",
            evidence=[
                EvidenceLink(
                    id="ev_lp_d2_1",
                    kind="policy",
                    source_type="policy",
                    uri="local_plan://section/d2/design",
                    pointer="/design/conservation_areas",
                    hash=hashlib.md5(b"lp_d2_content").hexdigest(),
                    captured_at=_now_iso(),
                    snippet="Development within conservation areas must preserve or enhance the character and appearance..."
                )
            ]
        )
    ]
    
    # Mock spatial analysis
    spatial = [
        SpatialFinding(
            layer="conservation_area",
            hit=False,
            detail={"distance_m": 85, "nearest": "Oldtown Conservation Area"},
            evidence=[]
        ),
        SpatialFinding(
            layer="flood_zones",
            hit=False,
            detail={"zone": "1", "risk": "low"},
            evidence=[]
        ),
        SpatialFinding(
            layer="listed_buildings",
            hit=False,
            detail={"distance_m": 120, "nearest": "Former Town Hall (Grade II)"},
            evidence=[]
        )
    ]
    
    # Mock checklist
    checklist = [
        ChecklistItem(item="Site visit completed", status="pass", note="Visited on site"),
        ChecklistItem(item="Neighbour notifications sent", status="pass", note="3 neighbours notified"),
        ChecklistItem(item="Conservation officer consulted", status="needs_review", note="Awaiting response"),
    ]
    
    # Generate draft report
    draft_report = f"""# Planning Assessment Report

## Application Details
- **Reference**: {case_ref}
- **Proposal**: Single storey rear extension
- **Assessment Date**: {datetime.now(timezone.utc).strftime('%d %B %Y')}

## Recommendation
**APPROVE with conditions** (Confidence: 78%)

## Site Context
The application site is located on a residential street characterized by semi-detached properties of similar age and design. The site is not within a conservation area, though the Oldtown Conservation Area is approximately 85m to the north.

## Policy Assessment

### LP.H1: Residential Extensions and Alterations
**Status**: ✅ Complies

The proposed single-storey rear extension measures 3.5m in depth and 4m in width, which is within the parameters set out in policy LP.H1. The extension:
- Does not exceed the 4m depth limit
- Maintains a 45-degree line from neighbouring windows
- Preserves adequate private amenity space (garden depth of 11m retained)

### LP.D2: Design Quality  
**Status**: ⚠️ Minor concerns

The extension uses matching brick and roof tiles, which is positive. However, consideration should be given to:
- Window design to better reflect the original property
- Roof pitch alignment with the existing dwelling

## Constraints Analysis
- **Flood Risk**: Zone 1 (low risk) - no mitigation required
- **Conservation Area**: Not within, nearest area 85m away
- **Listed Buildings**: Nearest Grade II building 120m away

## Consultations
- Neighbour notifications: Sent to 3 properties (21-day period)
- Conservation Officer: Consultation pending

## Conditions Recommended
1. Materials to match existing dwelling
2. Development to be completed within 3 years
3. Permitted development rights for further extensions to be removed

## Conclusion
Subject to the recommended conditions, the proposal is considered acceptable and in accordance with the development plan.
"""
    
    result = AssessmentResult(
        recommendation=Recommendation(outcome="approve", confidence=0.78),
        policies=policies,
        spatial=spatial,
        checklist=checklist,
        draft_report_md=draft_report,
        artifacts={
            "site_map": {"type": "application/geo+json", "uri": f"http://agent-bridge:8000/runs/{run_id}/overlays.geojson"}
        },
        trace=Trace(
            inputs_hash=_hash_inputs(env),
            steps=[
                TraceStep(t="retrieve_policy", at=_now_iso(), notes="Validated envelope schema and geometry"),
                TraceStep(t="retrieve_policy", at=_now_iso(), notes="Retrieved 8 relevant policies from local plan"),
                TraceStep(t="spatial_query", at=_now_iso(), notes="Queried 5 constraint layers"),
                TraceStep(t="reason", at=_now_iso(), notes="Generated policy assessment using gpt-4o-mini"),
                TraceStep(t="report_map", at=_now_iso(), notes="Compiled draft decision report"),
            ],
            model_ref="gpt-4o-mini",
            prompt_ref="assess/0.1",
            kb_snapshot=KnowledgeBaseSnapshot(corpus_version="local_plan_2024_10"),
            latency_ms=int((time.time() - t0) * 1000),
        ),
    )
    headers = {"X-Run-Id": run_id}
    return JSONResponse(content=json.loads(result.model_dump_json()), headers=headers)

@app.post("/notice", response_model=AssessmentResult)
async def notice(req: Request):
    body = await req.body()
    require_auth(req, body)
    env = AssessmentEnvelope.model_validate_json(body)
    result = AssessmentResult(
        artifacts={
            "decision_notice": ArtifactRef(type="text/markdown", uri="s3://example/notice.md"),
        },
        draft_report_md="# Decision Notice\n\nStub content.",
        trace=Trace(inputs_hash=_hash_inputs(env), steps=[TraceStep(t="report_map", at=_now_iso(), notes="stub")]),
    )
    return result


# --- Runs (async) ---

@app.post("/runs")
async def start_run(req: Request):
    body = await req.body()
    require_auth(req, body)
    env = AssessmentEnvelope.model_validate_json(body)
    run_id = hashlib.sha1(_hash_inputs(env).encode()).hexdigest()[:16]
    headers = {"X-Run-Id": run_id}
    payload = {"run_id": run_id, "status": "queued"}
    return JSONResponse(status_code=202, content=payload, headers=headers)


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    # Return a stub result snapshot
    result = AssessmentResult(
        draft_report_md="## Summary\nRun stub for {run_id}",
        trace=Trace(inputs_hash=run_id, steps=[TraceStep(t="reason", at=_now_iso(), notes="stub")]),
    )
    etag = hashlib.md5(run_id.encode()).hexdigest()
    headers = {"ETag": etag, "X-Model-Ref": "stub", "X-KB-Snapshot": "v0"}
    return JSONResponse(content=json.loads(result.model_dump_json()), headers=headers)


@app.get("/runs/{run_id}/events")
def stream_run_events(run_id: str):
    def gen():
        frames = [
            {"t": "retrieve_policy", "notes": "start"},
            {"t": "reason", "notes": "thinking"},
            {"t": "overlay_emit", "notes": "done"},
        ]
        for f in frames:
            yield f"event: progress\n"
            yield f"data: {json.dumps(f)}\n\n"
            time.sleep(0.05)
        yield "event: done\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/runs/{run_id}/overlays.geojson")
def get_overlays_geojson(run_id: str, layers: Optional[str] = None):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"layer": "ai_inferences", "run_id": run_id},
                "geometry": {"type": "Point", "coordinates": [0.0, 51.0]},
            }
        ],
    }
    return JSONResponse(content=fc, media_type="application/geo+json")


# --- Reports ---

@app.post("/reports")
async def create_report(req: Request):
    body = await req.json()
    template_id = body.get("template_id")
    fields = body.get("fields")
    if not template_id or not isinstance(fields, dict):
        raise HTTPException(status_code=400, detail="template_id and fields required")
    draft_id = hashlib.md5(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:12]
    return JSONResponse(status_code=201, content={"report_draft_id": draft_id})


@app.get("/reports/{report_draft_id}")
def get_report(report_draft_id: str):
    return {
        "template_id": "default",
        "fields": {"summary": "Stub"},
        "provenance": {},
    }


@app.get("/reports/{report_draft_id}/export")
def export_report(report_draft_id: str, format: str):  # noqa: A002 (shadow built-in)
    if format == "md":
        return PlainTextResponse("# Report\n\nStub export.", media_type="text/markdown")
    if format == "docx":
        return PlainTextResponse("DOCX stub", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if format == "pdf":
        return PlainTextResponse("PDF stub", media_type="application/pdf")
    raise HTTPException(status_code=400, detail="Unsupported format")


# --- Registries ---

@app.get("/registries/{name}")
def get_registry(name: str):
    if name == "constraints":
        return ["flood_zones", "conservation", "listed_buildings"]
    if name == "policy_scopes":
        return ["local_plan:2024.10", "national:2023.06"]
    if name == "report_templates":
        return [{"id": "default", "fields": ["summary", "policies", "assessment", "conclusion"]}]
    raise HTTPException(status_code=404, detail="Not found")


# --- Tools ---

@app.post("/tools/execute")
async def tools_execute(req: Request):
    body = await req.json()
    name = body.get("name")
    subject = body.get("subject", {})
    if not name:
        raise HTTPException(status_code=400, detail="Missing tool name")
    return {"result": {"ok": True, "tool": name, "subject": subject}, "overlay_uri": "s3://example/overlay.geojson"}
