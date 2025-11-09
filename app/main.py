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
    result = AssessmentResult(
        recommendation=Recommendation(outcome="seek_changes", confidence=0.5),
        policies=[],
        spatial=[],
        draft_report_md="## Summary\nStub draft.",
        trace=Trace(
            inputs_hash=_hash_inputs(env),
            steps=[
                TraceStep(t="retrieve_policy", at=_now_iso(), notes="stub"),
                TraceStep(t="reason", at=_now_iso(), notes="stub"),
            ],
            model_ref="stub",
            prompt_ref="assess/0.1",
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
