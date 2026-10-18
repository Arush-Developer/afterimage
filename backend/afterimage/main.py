"""FastAPI application: wires the services together and exposes the REST API.

Run locally (from the backend/ directory):
    uvicorn afterimage.main:create_app --factory --reload --port 8000
Interactive API docs are served at http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Literal

from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .common import AfterimageError, ConflictError, ValidationFailure, utc_now
from .config import Settings, load_settings
from .db import Database, dumps, loads
from .investigator import INCIDENT_STATUSES, Investigator
from .policy import CHANGE_CATALOG
from .policy_store import PolicyStore
from .recorder import EventRecorder, RedactingLogFilter, deserialize_event
from .recovery import VAULT_FILES, RecoveryVault
from .experiment import ExperimentService
from .explainer import IncidentExplainer
from .providers import ProviderConfigError, ProviderError as LLMProviderError, build_provider, provider_status
from .replay import ReplayService
from .runs import SCENARIOS, RunService

log = logging.getLogger("afterimage")

RUN_ID = Path(pattern=r"^run_[0-9a-f]{16}$")
INC_ID = Path(pattern=r"^inc_[0-9a-f]{16}$")
RPL_ID = Path(pattern=r"^rpl_[0-9a-f]{16}$")
SNP_ID = Path(pattern=r"^snp_[0-9a-f]{16}$")
EXP_ID = Path(pattern=r"^exp_[0-9a-f]{16}$")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
RESET_PHRASE = "ARCHIVE AND RESET"

ChangeId = Literal["restrict-read-scope", "deny-secret-class", "require-approval-sensitive", "disable-write-tool"]


# -- request bodies -------------------------------------------------------------
class LLMRunRequest(BaseModel):
    provider: Literal["anthropic", "ollama", "simulated"] | None = None
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:/-]{1,100}$")
    enforcement: Literal["protected", "baseline"] = "protected"


class ExperimentRequest(BaseModel):
    provider: Literal["anthropic", "ollama", "simulated"] | None = None
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:/-]{1,100}$")
    trials: int = Field(default=1, ge=1, le=20)


class ExplainRequest(BaseModel):
    provider: Literal["anthropic", "ollama", "simulated"] | None = None
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:/-]{1,100}$")


class PolicyPreviewRequest(BaseModel):
    change_ids: list[ChangeId] = Field(min_length=1, max_length=4)


class PolicyApplyRequest(PolicyPreviewRequest):
    base_version: int = Field(ge=1)
    confirm: Literal[True]


class PolicyRevertRequest(BaseModel):
    target_version: int = Field(ge=1)
    base_version: int = Field(ge=1)
    confirm: Literal[True]


class ReplayRequest(BaseModel):
    baseline_run_id: str | None = Field(default=None, pattern=r"^run_[0-9a-f]{16}$")
    incident_id: str | None = Field(default=None, pattern=r"^inc_[0-9a-f]{16}$")
    trials: int = Field(default=1, ge=1, le=20)


class SnapshotRequest(BaseModel):
    path: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="manual snapshot", min_length=1, max_length=200)


class SimulateChangeRequest(BaseModel):
    path: str = Field(min_length=1, max_length=256)


class RestoreRequest(BaseModel):
    confirm: Literal[True]


class AnnotationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    status: Literal["open", "investigating", "contained", "exposure_confirmed", "resolved"] | None = None


class ResetRequest(BaseModel):
    mode: Literal["demo", "full"]
    confirm_text: str = Field(max_length=64)


# -- application context --------------------------------------------------------
class AppContext:
    """Holds all services. Re-created after a full reset."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.mutation_lock = threading.RLock()
        self._open()

    def _open(self) -> None:
        s = self.settings
        s.data_dir.mkdir(parents=True, exist_ok=True)
        s.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(s.db_path)
        self.recorder = EventRecorder(self.db)
        self.policies = PolicyStore(self.db, self.recorder)
        self.policies.ensure_baseline()
        self.runs = RunService(s, self.db, self.recorder, self.policies)
        self.investigator = Investigator(self.db, self.recorder, self.policies)
        self.replays = ReplayService(self.db, self.runs, self.investigator)
        self.experiments = ExperimentService(self.db, self.runs, s, self.investigator)
        self.explainer = IncidentExplainer(self.db, self.recorder, self.investigator)
        self.vault = RecoveryVault(s.vault_dir, self.db, self.recorder)
        self.vault.ensure()

    def close(self) -> None:
        self.db.close()

    def full_reset(self) -> dict[str, Any]:
        s = self.settings
        s.archives_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = s.archives_dir / f"afterimage-{stamp}.db"
        with self.db.lock:
            target = sqlite3.connect(str(archive))
            self.db._conn.backup(target)
            target.close()
        self.close()
        for suffix in ("", "-wal", "-shm"):
            p = s.db_path.with_name(s.db_path.name + suffix)
            if p.exists():
                p.unlink()
        shutil.rmtree(s.workspaces_dir, ignore_errors=True)
        shutil.rmtree(s.vault_dir, ignore_errors=True)
        self._open()
        self.recorder.record(event_type="environment_reset", actor="operator", action="full_reset", outcome="success",
                             severity="info", summary=f"Full reset. Previous evidence archived to archives/{archive.name}.",
                             evidence={"archive": archive.name})
        return {"mode": "full", "archive": archive.name}

    def demo_reset(self) -> dict[str, Any]:
        policy = self.policies.reset_to_baseline()
        restored = []
        for item in self.vault.list_files():
            if not item["matches_original"]:
                self.vault.snapshot(item["path"], "automatic snapshot before demo reset")
                restored.append(item["path"])
        self.vault.ensure(reset=True)
        removed = 0
        for child in self.settings.workspaces_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        self.recorder.record(event_type="environment_reset", actor="operator", action="demo_reset", outcome="success",
                             severity="info",
                             summary=("Demo environment reset: baseline policy restored, vault files reset, "
                                      f"{removed} run workspace(s) removed. Evidence records were kept."),
                             evidence={"policy_version": self.policies.active_version(), "vault_files_reset": restored,
                                       "workspaces_removed": removed, "policy_changed": policy is not None})
        return {"mode": "demo", "policy_version": self.policies.active_version(), "vault_files_reset": restored,
                "workspaces_removed": removed}


def _install_log_redaction() -> None:
    """Scrub the synthetic canary from every log record handled by existing handlers."""
    redactor = RedactingLogFilter()
    for name in ("", "afterimage", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingLogFilter) for f in logger.filters):
            logger.addFilter(redactor)
        for handler in logger.handlers:
            if not any(isinstance(f, RedactingLogFilter) for f in handler.filters):
                handler.addFilter(redactor)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    _install_log_redaction()
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.ctx.close()

    app = FastAPI(title="AFTERIMAGE API", version=__version__, lifespan=lifespan,
                  description="AI-agent incident forensics, policy enforcement and recovery (hackathon prototype).")
    app.state.ctx = AppContext(settings)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key"])

    @app.exception_handler(AfterimageError)
    async def _handle_known(_: Request, exc: AfterimageError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(LLMProviderError)
    async def _handle_provider(_: Request, exc: LLMProviderError) -> JSONResponse:
        # Config/credential/model problems are the caller's to fix (400); transient
        # provider problems (timeout, rate limit, 5xx) are 503. The message is safe to
        # surface and never contains key material.
        status = 400 if isinstance(exc, ProviderConfigError) else (503 if exc.retryable else 502)
        return JSONResponse(status_code=status, content={"detail": exc.message, "code": f"provider_{exc.kind}"})

    @app.exception_handler(Exception)
    async def _handle_unknown(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "internal server error", "code": "internal_error"})

    def ctx() -> AppContext:
        return app.state.ctx

    def idempotent(c: AppContext, key: str | None, endpoint: str, fn: Callable[[], Any], status: int = 200) -> JSONResponse:
        """Serialize state changes; replay the stored response for a repeated Idempotency-Key."""
        if key is not None and not IDEMPOTENCY_RE.match(key):
            raise ValidationFailure("Idempotency-Key must be 8-64 characters of [A-Za-z0-9_-]")
        with c.mutation_lock:
            if key:
                row = c.db.query_one("SELECT * FROM idempotency_keys WHERE idem_key = ?", (key,))
                if row:
                    if row["endpoint"] != endpoint:
                        raise ConflictError("Idempotency-Key was already used for a different request")
                    return JSONResponse(status_code=row["status_code"], content=loads(row["response_json"]),
                                        headers={"Idempotent-Replay": "true"})
            result = fn()
            if key:
                c.db.execute("INSERT INTO idempotency_keys (idem_key, endpoint, status_code, response_json, created_at) "
                             "VALUES (?,?,?,?,?)", (key, endpoint, status, dumps(result), utc_now()))
            return JSONResponse(status_code=status, content=result)

    # -- health / dashboard ---------------------------------------------------------
    @app.get("/api/health")
    def health(c: AppContext = Depends(ctx)) -> dict[str, Any]:
        c.db.scalar("SELECT 1")
        return {"status": "ok", "version": __version__, "database": "ok", "time": utc_now()}

    @app.get("/api/dashboard")
    def dashboard(c: AppContext = Depends(ctx)) -> dict[str, Any]:
        db = c.db
        unauthorized_blocked = db.scalar(
            "SELECT COUNT(*) FROM events WHERE event_type = 'policy_decision' AND outcome != 'allowed' "
            "AND json_extract(evidence_metadata, '$.resource_sensitivity') IN ('restricted', 'outside_workspace')")
        policy = c.policies.describe()
        return {
            "metrics": {
                "runs": db.scalar("SELECT COUNT(*) FROM runs"),
                "scenario_runs": db.scalar("SELECT COUNT(*) FROM runs WHERE kind = 'scenario'"),
                "replay_runs": db.scalar("SELECT COUNT(*) FROM runs WHERE kind = 'replay'"),
                "incidents": db.scalar("SELECT COUNT(*) FROM incidents"),
                "unauthorized_blocked": unauthorized_blocked,
                "denied_total": db.scalar("SELECT COUNT(*) FROM policy_decisions WHERE allowed = 0"),
                "exposures": db.scalar("SELECT COUNT(*) FROM events WHERE event_type = 'sensitive_data_exposed'"),
                "verified_replays": db.scalar("SELECT COUNT(*) FROM replays WHERE verified = 1"),
                "replays": db.scalar("SELECT COUNT(*) FROM replays"),
                "events": db.scalar("SELECT COUNT(*) FROM events"),
                "llm_runs": db.scalar("SELECT COUNT(*) FROM runs WHERE agent_kind = 'llm'"),
                "experiments": db.scalar("SELECT COUNT(*) FROM experiments"),
                "experiments_protected": db.scalar("SELECT COUNT(*) FROM experiments WHERE status = 'protected'"),
            },
            "recent_experiments": c.experiments.list()[:5],
            "recent_incidents": c.investigator.list()[:5],
            "recent_runs": c.runs.list(limit=6),
            "policy": {"version": policy["version"], "name": policy["document"]["name"],
                       "rule_count": len(policy["document"]["rules"]),
                       "disabled_tools": policy["document"]["disabled_tools"],
                       "change_summary": policy["change_summary"], "created_at": policy["created_at"]},
            "sync": {"local": {"status": "ok", "label": "Local SQLite database"},
                     "cloud": {"status": "not_configured",
                               "label": "Cloud sync not configured (optional; not implemented in this prototype)"}},
        }

    # -- runs -----------------------------------------------------------------------
    @app.get("/api/scenarios")
    def scenarios() -> dict[str, Any]:
        return SCENARIOS

    @app.get("/api/runs")
    def list_runs(limit: int = Query(50, ge=1, le=200), c: AppContext = Depends(ctx)) -> list[dict[str, Any]]:
        return c.runs.list(limit)

    def _start_run(c: AppContext, scenario: Literal["benign", "attack"]) -> dict[str, Any]:
        run = c.runs.execute(scenario)
        c.investigator.detect(run["run_id"])
        return c.runs.get(run["run_id"])

    @app.post("/api/runs/benign", status_code=201)
    def run_benign(idempotency_key: str | None = Header(default=None), c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "runs/benign", lambda: _start_run(c, "benign"), 201)

    @app.post("/api/runs/attack", status_code=201)
    def run_attack(idempotency_key: str | None = Header(default=None), c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "runs/attack", lambda: _start_run(c, "attack"), 201)

    def _start_llm_run(c: AppContext, body: "LLMRunRequest") -> dict[str, Any]:
        run = c.runs.execute(scenario="llm", agent_kind="llm", enforcement=body.enforcement,
                             provider=body.provider, model=body.model)
        c.investigator.detect(run["run_id"])
        return c.runs.get(run["run_id"])

    @app.post("/api/runs/llm", status_code=201)
    def run_llm(body: LLMRunRequest, idempotency_key: str | None = Header(default=None),
                c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "runs/llm", lambda: _start_llm_run(c, body), 201)

    @app.get("/api/providers")
    def providers(c: AppContext = Depends(ctx)) -> dict[str, Any]:
        from .providers import DEFAULT_MODELS, provider_status
        return {"providers": provider_status(c.settings), "default_provider": c.settings.llm_provider,
                "default_models": DEFAULT_MODELS, "configured_model": c.settings.llm_model,
                "max_trials": c.settings.llm_max_trials, "max_steps": c.settings.llm_max_steps}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str = RUN_ID, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.runs.get(run_id)

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: str = RUN_ID, c: AppContext = Depends(ctx)) -> list[dict[str, Any]]:
        return c.runs.events(run_id)

    @app.get("/api/runs/{run_id}/transcript")
    def run_transcript(run_id: str = RUN_ID, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return {"run_id": run_id, "transcript": c.runs.transcript(run_id)}

    # -- prompt-injection experiment -----------------------------------------------------
    @app.get("/api/experiments")
    def list_experiments(c: AppContext = Depends(ctx)) -> list[dict[str, Any]]:
        return c.experiments.list()

    @app.post("/api/experiments", status_code=201)
    def create_experiment(body: ExperimentRequest, idempotency_key: str | None = Header(default=None),
                          c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "experiments",
                          lambda: c.experiments.create(body.provider, body.model, body.trials), 201)

    @app.get("/api/experiments/{experiment_id}")
    def get_experiment(experiment_id: str = EXP_ID, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.experiments.get(experiment_id)

    # -- incidents ------------------------------------------------------------------
    @app.get("/api/incidents")
    def list_incidents(c: AppContext = Depends(ctx)) -> list[dict[str, Any]]:
        return c.investigator.list()

    @app.get("/api/incidents/{incident_id}")
    def get_incident(incident_id: str = INC_ID, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.investigator.report(incident_id)

    @app.get("/api/incidents/{incident_id}/events")
    def incident_events(incident_id: str = INC_ID, c: AppContext = Depends(ctx)) -> list[dict[str, Any]]:
        return c.investigator.incident_events(incident_id)

    @app.get("/api/incidents/{incident_id}/graph")
    def incident_graph(incident_id: str = INC_ID, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.investigator.graph(incident_id)

    @app.post("/api/incidents/{incident_id}/notes", status_code=201)
    def annotate(body: AnnotationRequest, incident_id: str = INC_ID,
                 idempotency_key: str | None = Header(default=None), c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, f"incidents/{incident_id}/notes",
                          lambda: c.investigator.annotate(incident_id, body.text, body.status), 201)

    @app.post("/api/incidents/{incident_id}/explain", status_code=201)
    def explain_incident(body: ExplainRequest, incident_id: str = INC_ID,
                         idempotency_key: str | None = Header(default=None), c: AppContext = Depends(ctx)) -> JSONResponse:
        def run() -> dict[str, Any]:
            provider = build_provider(body.provider or c.settings.llm_provider, body.model, c.settings)
            return c.explainer.explain(incident_id, provider, max_tokens=c.settings.llm_max_tokens,
                                       timeout=c.settings.llm_timeout_s)
        return idempotent(c, idempotency_key, f"incidents/{incident_id}/explain", run, 201)

    @app.get("/api/incidents/{incident_id}/explanation")
    def incident_explanation(incident_id: str = INC_ID, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return {"explanation": c.explainer.latest(incident_id)}

    # -- policies -------------------------------------------------------------------
    @app.get("/api/policies")
    def policies(c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return {"active": c.policies.describe(), "history": c.policies.history(), "catalog": c.policies.catalog()}

    @app.get("/api/policies/{version}")
    def policy_version(version: int = Path(ge=1), c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.policies.describe(version)

    @app.post("/api/policies/preview")
    def preview(body: PolicyPreviewRequest, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.policies.preview(list(dict.fromkeys(body.change_ids)))

    @app.post("/api/policies/apply")
    def apply(body: PolicyApplyRequest, idempotency_key: str | None = Header(default=None),
              c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "policies/apply",
                          lambda: c.policies.apply(list(dict.fromkeys(body.change_ids)), body.base_version))

    @app.post("/api/policies/revert")
    def revert(body: PolicyRevertRequest, idempotency_key: str | None = Header(default=None),
               c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "policies/revert",
                          lambda: c.policies.revert(body.target_version, body.base_version))

    # -- replays --------------------------------------------------------------------
    @app.get("/api/replays")
    def list_replays(c: AppContext = Depends(ctx)) -> list[dict[str, Any]]:
        return c.replays.list()

    @app.post("/api/replays", status_code=201)
    def create_replay(body: ReplayRequest, idempotency_key: str | None = Header(default=None),
                      c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "replays",
                          lambda: c.replays.create(body.baseline_run_id, body.incident_id, body.trials), 201)

    @app.get("/api/replays/{replay_id}")
    def get_replay(replay_id: str = RPL_ID, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.replays.get(replay_id)

    # -- recovery vault ------------------------------------------------------------------
    @app.get("/api/recovery/files")
    def vault_files(c: AppContext = Depends(ctx)) -> list[dict[str, Any]]:
        return c.vault.list_files()

    @app.post("/api/recovery/simulate-change", status_code=201)
    def simulate_change(body: SimulateChangeRequest, idempotency_key: str | None = Header(default=None),
                        c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "recovery/simulate-change", lambda: c.vault.simulate_change(body.path), 201)

    @app.get("/api/snapshots")
    def list_snapshots(path: str | None = Query(default=None, max_length=256), c: AppContext = Depends(ctx)) -> list[dict[str, Any]]:
        return c.vault.list(path)

    @app.post("/api/snapshots", status_code=201)
    def create_snapshot(body: SnapshotRequest, idempotency_key: str | None = Header(default=None),
                        c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, "snapshots", lambda: c.vault.snapshot(body.path, body.reason), 201)

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: str = SNP_ID, c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.vault.get(snapshot_id, include_content=True)

    @app.post("/api/snapshots/{snapshot_id}/restore")
    def restore_snapshot(body: RestoreRequest, snapshot_id: str = SNP_ID,
                         idempotency_key: str | None = Header(default=None), c: AppContext = Depends(ctx)) -> JSONResponse:
        return idempotent(c, idempotency_key, f"snapshots/{snapshot_id}/restore", lambda: c.vault.restore(snapshot_id))

    # -- events ---------------------------------------------------------------------
    @app.get("/api/events")
    def list_events(
        run_id: str | None = Query(default=None, pattern=r"^run_[0-9a-f]{16}$"),
        incident_id: str | None = Query(default=None, pattern=r"^inc_[0-9a-f]{16}$"),
        event_type: str | None = Query(default=None, max_length=64),
        resource: str | None = Query(default=None, max_length=256),
        outcome: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=200, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        c: AppContext = Depends(ctx),
    ) -> dict[str, Any]:
        where, params = [], []
        if run_id:
            where.append("run_id = ?"); params.append(run_id)  # noqa: E702
        if incident_id:
            where.append("(incident_id = ? OR event_id IN (SELECT event_id FROM incident_events WHERE incident_id = ?))")
            params += [incident_id, incident_id]
        if event_type:
            where.append("event_type = ?"); params.append(event_type)  # noqa: E702
        if resource:
            where.append("resource_id LIKE ? ESCAPE '\\'")
            params.append("%" + resource.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if outcome:
            where.append("outcome = ?"); params.append(outcome)  # noqa: E702
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        total = c.db.scalar(f"SELECT COUNT(*) FROM events {clause}", tuple(params))
        rows = c.db.query(f"SELECT * FROM events {clause} ORDER BY seq DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        return {"total": total, "limit": limit, "offset": offset, "events": [deserialize_event(r) for r in rows]}

    @app.get("/api/events/facets")
    def event_facets(c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return {
            "event_types": [r["event_type"] for r in c.db.query("SELECT DISTINCT event_type FROM events ORDER BY 1")],
            "outcomes": [r["outcome"] for r in c.db.query("SELECT DISTINCT outcome FROM events ORDER BY 1")],
            "runs": [r["run_id"] for r in c.db.query("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 100")],
            "incidents": [r["incident_id"] for r in c.db.query("SELECT incident_id FROM incidents ORDER BY created_at DESC")],
        }

    @app.get("/api/events/verify")
    def verify_events(c: AppContext = Depends(ctx)) -> dict[str, Any]:
        return c.recorder.verify_chain()

    # -- settings ---------------------------------------------------------------------
    @app.get("/api/settings")
    def get_settings(c: AppContext = Depends(ctx)) -> dict[str, Any]:
        s = c.settings
        size = sum(p.stat().st_size for p in s.data_dir.glob("afterimage.db*") if p.is_file())
        archives = sorted(p.name for p in s.archives_dir.glob("*.db")) if s.archives_dir.exists() else []
        return {
            "version": __version__,
            "database": {"engine": "SQLite", "file": s.db_path.name, "size_bytes": size,
                         "events": c.db.scalar("SELECT COUNT(*) FROM events"),
                         "hash_chain": c.recorder.verify_chain()},
            "demo_environment": {"synthetic_only": True, "vault_files": list(VAULT_FILES),
                                 "scenarios": list(SCENARIOS), "policy_changes": list(CHANGE_CATALOG),
                                 "run_workspaces": sum(1 for p in s.workspaces_dir.iterdir() if p.is_dir()),
                                 "scripted_agent": "deterministic, no LLM (used for regression tests)"},
            "llm": {"default_provider": s.llm_provider, "default_model": s.llm_model,
                    "effort": s.llm_effort, "max_steps": s.llm_max_steps, "max_tokens": s.llm_max_tokens,
                    "timeout_s": s.llm_timeout_s, "max_trials": s.llm_max_trials,
                    "providers": provider_status(s),
                    "note": "Credentials live only in the backend environment and are never returned by the API."},
            "cors_origins": s.cors_origins,
            "cloud_sync": {"status": "not_configured",
                           "detail": "Optional Supabase sync is not implemented in this prototype. All data stays local."},
            "archives": archives,
            "incident_statuses": INCIDENT_STATUSES,
            "reset_phrase": RESET_PHRASE,
        }

    @app.post("/api/settings/reset")
    def reset(body: ResetRequest, c: AppContext = Depends(ctx)) -> JSONResponse:
        with c.mutation_lock:
            if body.mode == "full":
                if body.confirm_text != RESET_PHRASE:
                    raise ValidationFailure(f"type '{RESET_PHRASE}' to confirm a full reset")
                return JSONResponse(content=c.full_reset())
            if body.confirm_text != "RESET DEMO":
                raise ValidationFailure("type 'RESET DEMO' to confirm a demo reset")
            return JSONResponse(content=c.demo_reset())

    return app
