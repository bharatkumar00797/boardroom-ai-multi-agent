"""FastAPI application: REST endpoints for board decisions plus the static dashboard."""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from fastapi import status as http
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from boardroom import __version__
from boardroom.agents.roles import DEFAULT_ROLES, get_roles
from boardroom.api.jobs import DecisionManager, DecisionRecord, QueueFull, RunFn, default_run
from boardroom.api.middleware import BodyLimitMiddleware, SecurityHeadersMiddleware
from boardroom.api.schemas import (
    ConfigOut,
    DecisionCreate,
    DecisionCreatedOut,
    DecisionDetailOut,
    DecisionListOut,
    DecisionSummaryOut,
    EventOut,
    EventsOut,
    HealthOut,
    RoleListOut,
    RoleOut,
    ScenarioListOut,
    ScenarioOut,
)
from boardroom.api.security import ApiKeyAuth, RateLimiter
from boardroom.api.settings import ApiSettings
from boardroom.config import Settings
from boardroom.engine import MAX_ROUNDS, DebateConfig
from boardroom.memo import render_markdown
from boardroom.models import Scenario
from boardroom.scenario import list_scenarios, load_packaged

STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY_BYTES = 64 * 1024
IdParam = Annotated[str, PathParam(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


@dataclass(frozen=True)
class Caller:
    """``owner`` tags new decisions, ``scope`` limits visibility (``None`` = all),
    ``client`` keys rate limits and ``trusted`` unlocks custom scenarios and real providers."""

    owner: str
    scope: str | None
    client: str
    trusted: bool


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        # The right-most hop is the one appended by the trusted edge proxy; anything to its
        # left is client-supplied and can be forged.
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        hops = [h for h in hops if h]
        if hops:
            return hops[-1][:64]
    return request.client.host if request.client else "unknown"


def presented_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key and key.strip():
        return key.strip()
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _retry_after(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


@dataclass(frozen=True)
class AccessGuard:
    """Authenticates a request and applies the general per-caller rate limit."""

    settings: ApiSettings
    auth: ApiKeyAuth
    limiter: RateLimiter

    def identify(self, request: Request) -> Caller | None:
        if self.auth.enabled:
            fp = self.auth.verify(presented_key(request))
            return Caller(f"key:{fp}", f"key:{fp}", f"key:{fp}", True) if fp else None
        ip = client_ip(request, self.settings.trust_proxy)
        if self.settings.dev_mode:
            return Caller("dev", None, f"ip:{ip}", True)
        anon = "anon:" + hashlib.sha256(ip.encode()).hexdigest()[:12]
        return Caller(anon, anon, f"ip:{ip}", False)

    def __call__(self, request: Request) -> Caller:
        who = self.identify(request)
        if who is None:
            raise HTTPException(
                http.HTTP_401_UNAUTHORIZED,
                "Missing or invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        retry = self.limiter.check(who.client)
        if retry is not None:
            raise HTTPException(
                http.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded", headers=_retry_after(retry)
            )
        return who


def get_caller(request: Request) -> Caller:
    guard: AccessGuard = request.app.state.guard
    return guard(request)


CallerDep = Annotated[Caller, Depends(get_caller)]


def _summary(record: DecisionRecord) -> DecisionSummaryOut:
    with record.lock:
        memo, state, finished = record.memo, record.state, record.finished_at
    return DecisionSummaryOut(
        id=record.id,
        state=state,
        scenario_id=record.scenario.id,
        title=record.scenario.title,
        provider=record.provider,
        rounds=record.rounds,
        recommendation=memo.recommendation if memo else None,
        confidence=memo.confidence if memo else None,
        created_at=record.created_at,
        finished_at=finished,
    )


def _detail(record: DecisionRecord) -> DecisionDetailOut:
    with record.lock:
        memo, error, started, count = (
            record.memo,
            record.error,
            record.started_at,
            len(record.events),
        )
    return DecisionDetailOut(
        **_summary(record).model_dump(),
        started_at=started,
        error=error,
        event_count=count,
        memo=memo,
    )


def create_app(
    settings: ApiSettings | None = None,
    base_settings: Settings | None = None,
    *,
    run_fn: RunFn = default_run,
) -> FastAPI:
    cfg = settings or ApiSettings.from_env()
    base = base_settings or Settings.from_env()
    auth = ApiKeyAuth(cfg.api_keys)
    decision_limiter = RateLimiter(cfg.decision_limit_per_minute)
    manager = DecisionManager(
        max_workers=cfg.max_concurrent_runs,
        max_active=cfg.max_queued_runs,
        max_kept=cfg.max_decisions_kept,
        run_fn=run_fn,
        inline=cfg.sync_runs,
    )
    scenario_ids = list_scenarios()
    default_rounds = max(0, min(base.rounds, MAX_ROUNDS))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        manager.shutdown()

    app = FastAPI(
        title="BoardRoom AI API",
        version=__version__,
        description=(
            "AI multi-agent business decision engine: executive role agents debate, critique "
            "and vote on a decision and return an auditable decision memo."
        ),
        lifespan=lifespan,
    )
    app.state.guard = AccessGuard(cfg, auth, RateLimiter(cfg.rate_limit_per_minute))
    app.state.manager = manager

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key", "Authorization"],
            allow_credentials=False,
            max_age=600,
        )
    app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(SecurityHeadersMiddleware)

    def load(decision_id: str, who: Caller) -> DecisionRecord:
        record = manager.get(decision_id, who.scope)
        if record is None:
            raise HTTPException(http.HTTP_404_NOT_FOUND, "Decision not found")
        return record

    def resolve_scenario(body: DecisionCreate, who: Caller) -> Scenario:
        if (body.scenario_id is None) == (body.scenario is None):
            raise HTTPException(
                http.HTTP_422_UNPROCESSABLE_CONTENT, "Provide exactly one of scenario_id/scenario"
            )
        if body.scenario_id is not None:
            try:
                return load_packaged(body.scenario_id)
            except KeyError as exc:
                raise HTTPException(
                    http.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown scenario {body.scenario_id!r}"
                ) from exc
        if not who.trusted:
            raise HTTPException(
                http.HTTP_403_FORBIDDEN,
                "Public demo: only packaged scenarios are enabled (custom ones need an API key)",
            )
        assert body.scenario is not None
        return body.scenario

    # ------------------------------------------------------------------ meta
    @app.get("/healthz", response_model=HealthOut, tags=["meta"])
    def healthz() -> HealthOut:
        return HealthOut(version=__version__, active_debates=manager.active_count())

    @app.get("/api/config", response_model=ConfigOut, tags=["meta"])
    def config(request: Request) -> ConfigOut:
        guard: AccessGuard = request.app.state.guard
        who = guard.identify(request)
        return ConfigOut(
            version=__version__,
            auth_required=cfg.auth_enabled,
            access_mode=cfg.access_mode,
            authenticated=who is not None and cfg.auth_enabled,
            custom_scenarios_allowed=not cfg.public_demo,
            providers=["mock"] if cfg.public_demo else sorted({"mock", base.provider}),
            default_provider="mock" if cfg.public_demo else base.provider,
            default_rounds=default_rounds,
            max_rounds=MAX_ROUNDS,
            sync_runs=cfg.sync_runs,
            scenarios=scenario_ids,
        )

    @app.get("/api/scenarios", response_model=ScenarioListOut, tags=["meta"])
    def scenarios(_: CallerDep) -> ScenarioListOut:
        out = []
        for sid in scenario_ids:
            sc = load_packaged(sid)
            out.append(
                ScenarioOut(
                    id=sc.id,
                    title=sc.title,
                    question=sc.question,
                    options=[{"id": o.id, "title": o.title} for o in sc.options],
                )
            )
        return ScenarioListOut(scenarios=out)

    @app.get("/api/scenarios/{scenario_id}", response_model=Scenario, tags=["meta"])
    def scenario_detail(scenario_id: IdParam, _: CallerDep) -> Scenario:
        try:
            return load_packaged(scenario_id)
        except KeyError as exc:
            raise HTTPException(http.HTTP_404_NOT_FOUND, "Scenario not found") from exc

    @app.get("/api/roles", response_model=RoleListOut, tags=["meta"])
    def roles(_: CallerDep) -> RoleListOut:
        return RoleListOut(
            roles=[
                RoleOut(
                    id=r.id,
                    name=r.name,
                    title=r.title,
                    mandate=r.mandate,
                    vote_weight=r.vote_weight,
                    can_block=r.can_block,
                    priorities=dict(r.priorities),
                )
                for r in DEFAULT_ROLES
            ]
        )

    # ------------------------------------------------------------- decisions
    @app.post(
        "/api/decisions",
        response_model=DecisionCreatedOut,
        status_code=http.HTTP_202_ACCEPTED,
        tags=["decisions"],
        responses={200: {"description": "Finished debate (sync mode)"}},
    )
    def create_decision(
        body: DecisionCreate, who: CallerDep, response: Response
    ) -> DecisionCreatedOut:
        use_configured = body.provider == "configured" or (
            body.provider is None and not cfg.public_demo
        )
        provider = base.provider if use_configured else "mock"
        if provider != "mock" and not who.trusted:
            raise HTTPException(
                http.HTTP_403_FORBIDDEN, "Only the offline mock provider is enabled here"
            )
        scenario = resolve_scenario(body, who)
        try:
            get_roles(body.roles)
            debate = DebateConfig(
                rounds=default_rounds if body.rounds is None else body.rounds, roles=body.roles
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(http.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)[:300]) from exc
        # Only well-formed requests count towards the stricter decision-creation limit.
        retry = decision_limiter.check(who.client)
        if retry is not None:
            raise HTTPException(
                http.HTTP_429_TOO_MANY_REQUESTS,
                "Decision creation limit exceeded",
                headers=_retry_after(retry),
            )
        try:
            record = manager.submit(
                owner=who.owner,
                scenario=scenario,
                settings=replace(base, provider=provider),
                config=debate,
            )
        except QueueFull as exc:
            raise HTTPException(
                http.HTTP_503_SERVICE_UNAVAILABLE, str(exc), headers={"Retry-After": "10"}
            ) from exc
        detail = _detail(record).model_dump()
        if not manager.inline:
            return DecisionCreatedOut(**detail)  # 202: poll the events endpoint
        response.status_code = http.HTTP_200_OK
        events = [EventOut(**e) for e in record.events_since(0)]
        return DecisionCreatedOut(**detail, events=events)

    @app.get("/api/decisions", response_model=DecisionListOut, tags=["decisions"])
    def list_decisions(
        who: CallerDep, limit: Annotated[int, Query(ge=1, le=100)] = 25
    ) -> DecisionListOut:
        return DecisionListOut(decisions=[_summary(r) for r in manager.list(who.scope, limit)])

    @app.get("/api/decisions/{decision_id}", response_model=DecisionDetailOut, tags=["decisions"])
    def get_decision(decision_id: IdParam, who: CallerDep) -> DecisionDetailOut:
        return _detail(load(decision_id, who))

    @app.get("/api/decisions/{decision_id}/events", response_model=EventsOut, tags=["decisions"])
    def get_events(
        decision_id: IdParam,
        who: CallerDep,
        since: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> EventsOut:
        record = load(decision_id, who)
        with record.lock:
            state, done = record.state, record.done
            events = record.events_since(since)
        return EventsOut(
            id=record.id,
            state=state,
            done=done,
            next_cursor=since + len(events),
            events=[EventOut(**e) for e in events],
        )

    @app.get(
        "/api/decisions/{decision_id}/memo.md",
        response_class=PlainTextResponse,
        tags=["decisions"],
        responses={200: {"content": {"text/markdown": {}}}},
    )
    def get_memo_markdown(decision_id: IdParam, who: CallerDep) -> PlainTextResponse:
        record = load(decision_id, who)
        if record.memo is None:
            raise HTTPException(http.HTTP_409_CONFLICT, "Debate has not finished yet")
        return PlainTextResponse(
            render_markdown(record.memo), media_type="text/markdown; charset=utf-8"
        )

    # ------------------------------------------------------------- dashboard
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
