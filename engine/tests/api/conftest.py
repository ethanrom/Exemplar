"""Fixtures for the API tests: isolated settings/data dir, fake Ring/perception/D/E, and a TestClient wrapper that
validates EVERY JSON response against the response schema of the matching api.yaml operation."""
from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import url2pathname

import jsonschema
import pytest
import yaml
from fastapi.testclient import TestClient
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from exemplar import settings
from exemplar.api import ApiConfig, AppState, Services, create_app
from exemplar.ring import AuthManager

from . import helpers as H

CONTRACTS = Path(__file__).resolve().parents[2] / "exemplar" / "contracts"
API_YAML = CONTRACTS / "api.yaml"
API_URI = API_YAML.as_uri()
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: calls the real Ring API / Bedrock; run with EXEMPLAR_LIVE=1")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("EXEMPLAR_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set EXEMPLAR_LIVE=1 (needs a fresh Playground token / spends Bedrock budget)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


# ================================================================================================== contract validation
SPEC: dict[str, Any] = yaml.safe_load(API_YAML.read_text(encoding="utf-8"))


def _retrieve(uri: str) -> Resource:
    path = Path(url2pathname(urlparse(uri).path))
    return Resource.from_contents(json.loads(path.read_text(encoding="utf-8")), default_specification=DRAFT202012)


REGISTRY = Registry(retrieve=_retrieve).with_resource(API_URI, Resource.from_contents(SPEC, default_specification=DRAFT202012))


def _deref(obj: Any) -> Any:
    """Follow `{$ref: '#/components/...'}` pointers inside api.yaml (for response objects)."""
    while isinstance(obj, dict) and "$ref" in obj and obj["$ref"].startswith("#/"):
        node: Any = SPEC
        for part in obj["$ref"][2:].split("/"):
            node = node[part]
        obj = node
    return obj


def _absolutize(obj: Any) -> Any:
    """Rewrite local `#/...` refs of an inline api.yaml schema to absolute refs into the registered spec."""
    if isinstance(obj, dict):
        return {k: (API_URI + v if k == "$ref" and isinstance(v, str) and v.startswith("#/") else _absolutize(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_absolutize(v) for v in obj]
    return obj


def validate_schema(schema: dict[str, Any], instance: Any) -> None:
    jsonschema.Draft202012Validator(_absolutize(schema), registry=REGISTRY).validate(instance)


def validate_component(name: str, instance: Any) -> None:
    validate_schema({"$ref": f"#/components/schemas/{name}"}, instance)


def _templates() -> list[tuple[re.Pattern[str], str]]:
    out = []
    for tpl in SPEC["paths"]:
        rx = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", tpl) + "$"
        out.append((re.compile(rx), tpl))
    # more literal segments first: '/concepts/{id}/labels/bulk-negative' before '/concepts/{id}/labels'
    out.sort(key=lambda t: (-len(re.sub(r"\{[^}]+\}", "", t[1])), t[1]))
    return out


TEMPLATES = _templates()
EXERCISED: set[tuple[str, str, int]] = set()      # (METHOD, template, status) seen by the validating client


def match_operation(method: str, path: str) -> tuple[str, dict[str, Any]] | None:
    for rx, tpl in TEMPLATES:
        if rx.match(path) and method.lower() in SPEC["paths"][tpl]:
            return tpl, SPEC["paths"][tpl][method.lower()]
    return None


class SchemaClient:
    """A TestClient that checks each response against api.yaml: documented status, JSON body matches the schema
    (undocumented 4xx/5xx must at least be a valid `Error`)."""

    def __init__(self, client: TestClient) -> None:
        self.c = client

    def request(self, method: str, url: str, *, validate: bool = True, **kw: Any):
        r = self.c.request(method, url, **kw)
        if validate:
            self.check(method, url, r)
        return r

    def check(self, method: str, url: str, r: Any) -> None:
        path = urlparse(url).path
        found = match_operation(method, path)
        if found is None:
            if path in ("/openapi.json", "/docs", "/redoc"):
                return
            if r.status_code >= 400:
                self._check_error(r)
                return
            raise AssertionError(f"{method} {path} is not an api.yaml operation")
        tpl, op = found
        EXERCISED.add((method.upper(), tpl, r.status_code))
        resp = _deref(op.get("responses", {}).get(str(r.status_code)))
        if resp is None and r.status_code in (206, 416) and "Range" in r.request.headers:
            return                                  # HTTP Range answers for the media endpoint ("supports Range")
        if resp is None:
            if r.status_code >= 400:
                self._check_error(r)
                return
            raise AssertionError(f"{method} {tpl}: undocumented success status {r.status_code}: {r.text[:200]}")
        ctype = r.headers.get("content-type", "")
        schema = ((resp.get("content") or {}).get("application/json") or {}).get("schema")
        if schema is not None and "application/json" in ctype:
            validate_schema(schema, r.json())
        elif r.status_code >= 400 and "application/json" in ctype:
            self._check_error(r)

    @staticmethod
    def _check_error(r: Any) -> None:
        if "application/json" in r.headers.get("content-type", ""):
            validate_component("Error", r.json())

    def get(self, url: str, **kw: Any): return self.request("GET", url, **kw)
    def post(self, url: str, **kw: Any): return self.request("POST", url, **kw)
    def put(self, url: str, **kw: Any): return self.request("PUT", url, **kw)
    def patch(self, url: str, **kw: Any): return self.request("PATCH", url, **kw)
    def delete(self, url: str, **kw: Any): return self.request("DELETE", url, **kw)

    @contextlib.contextmanager
    def stream(self, method: str, url: str, **kw: Any):
        with self.c.stream(method, url, **kw) as r:
            found = match_operation(method, urlparse(url).path)
            if found is not None:
                EXERCISED.add((method.upper(), found[0], r.status_code))
                assert str(r.status_code) in found[1]["responses"], f"undocumented status {r.status_code} on {found[0]}"
            yield r


# ================================================================================================== environment
@pytest.fixture(autouse=True)
def isolated_env(request, tmp_path, monkeypatch):
    """Offline tests never read the real .env, token file or data dir."""
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path / "data"))
    if request.node.get_closest_marker("live"):
        monkeypatch.delenv("EXEMPLAR_DB", raising=False)         # live tests keep the caller's .env / token, tmp data dir
        settings.get_settings.cache_clear()
        yield tmp_path / "data"
        settings.get_settings.cache_clear()
        return
    monkeypatch.setenv("EXEMPLAR_DOTENV", str(tmp_path / "no.env"))
    for var in ("RING_PLAYGROUND_TOKEN", "RING_CLIENT_ID", "RING_CLIENT_SECRET", "RING_WEBHOOK_SIGNING_KEY", "EXEMPLAR_DB"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_AWS_MODEL_ALIAS", "test-alias")
    settings.get_settings.cache_clear()
    yield tmp_path / "data"
    settings.get_settings.cache_clear()


@pytest.fixture(scope="session")
def video_bytes(tmp_path_factory) -> bytes:
    return H.make_mp4(tmp_path_factory.mktemp("media") / "clip.mp4", seconds=6.0).read_bytes()


@pytest.fixture(scope="session")
def long_video(tmp_path_factory) -> Path:
    """30 s source for the upload / windowing tests."""
    return H.make_mp4(tmp_path_factory.mktemp("media2") / "long.mp4", seconds=30.0, size="320x240", fps=10)


@pytest.fixture(scope="session")
def jpeg_bytes() -> bytes:
    return H.make_jpeg()


# ================================================================================================== the app
class Env:
    """Everything a test needs: the validating client plus handles on the fakes and the state."""

    def __init__(self, client: SchemaClient, state: AppState, ring: H.FakeRing, perceive: H.FakePerceive,
                 cegis: H.FakeCegis, calibrate: H.FakeCalibrate, active: H.FakeActive, services: Services) -> None:
        self.client, self.state, self.ring, self.perceive = client, state, ring, perceive
        self.cegis, self.calibrate, self.active, self.services = cegis, calibrate, active, services

    # convenience -----------------------------------------------------------------------------------------
    def connect(self, minutes: float = 30.0) -> None:
        r = self.client.put("/ring/auth", json={"access_token": H.fresh_jwt(minutes)})
        assert r.status_code == 200, r.text

    def sync(self) -> int:
        r = self.client.post("/ring/sync")
        assert r.status_code == 202, r.text
        return r.json()["new_events"]

    def wait_trace(self, event_id: str, status: str = "ok", timeout: float = 20.0) -> dict[str, Any]:
        def check():
            ev = self.client.get(f"/events/{event_id}").json()
            return ev if ev["trace_status"] == status else None
        return H.wait_until(check, timeout, what=f"trace_status={status} for {event_id[:20]}")

    def seed_fixture_events(self, *names: str, concept_id: str | None = None) -> dict[str, str]:
        """Insert fixture traces as `fixture` events (no media); returns {name: clip_id}."""
        from exemplar.store import ClipRow, EventRow, now_ms
        out = {}
        for i, name in enumerate(names):
            tr = H.load_trace(name)
            eid = f"fx_{name}"
            start = 1_760_000_000_000 + i * 60_000
            self.state.store.events.insert(EventRow(id=eid, source="fixture", start_ms=start, created_at_ms=now_ms(),
                                                    device_id=tr.context.device_id, kind=tr.context.event_kind,
                                                    sub_type=tr.context.sub_type))
            self.state.store.clips.insert(ClipRow(id=name, event_id=eid, created_at_ms=now_ms(), status="not_found"))
            self.state.store.traces.put(name, tr, mode="fixture")
            out[name] = name
        return out

    def new_concept(self, name: str = "package theft", alpha: float = 0.1) -> str:
        r = self.client.post("/concepts", json={"name": name, "nl_hint": "someone takes a package", "alpha": alpha})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def label(self, cid: str, clip_id: str, value: str | None, provenance: str = "example"):
        return self.client.put(f"/concepts/{cid}/labels", json={"clip_id": clip_id, "value": value, "provenance": provenance})


def build_state(tmp_path: Path, services: Services, config: ApiConfig | None = None) -> AppState:
    settings.get_settings.cache_clear()
    s = settings.get_settings()
    cfg = config or ApiConfig(poll_enabled=False, clip_grace_s=0.0)
    from exemplar.store import Store
    store = Store(tmp_path / "db" / "exemplar.sqlite3")
    return AppState(settings=s, config=cfg, store=store, services=services, auth=AuthManager.from_settings(s, store=store.auth))


class _Served:
    """The app on a real uvicorn server in a thread: needed for SSE, because Starlette's TestClient buffers a
    response until the app finishes and so cannot observe a stream while it is still open."""

    def __init__(self, app: Any) -> None:
        import socket
        import threading
        import uvicorn
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning",
                                                    lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        H.wait_until(lambda: self.server.started, 15, what="uvicorn start")
        self.base_url = f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)
        if self.thread.is_alive():                      # a stuck connection: do not hang the suite
            self.server.force_exit = True
            self.thread.join(5)


@pytest.fixture
def make_env(tmp_path, video_bytes, jpeg_bytes) -> Callable[..., Any]:
    """Factory: `make_env(disable=("monitor_cls",))`; the default env has fakes for D, E, perception and Ring.
    `serve=True` runs the app on a real server (httpx client) for SSE tests."""
    closers: list[Callable[[], None]] = []

    def factory(*, disable: tuple[str, ...] = (), config: ApiConfig | None = None, start_background: bool = False,
                default_trace: str = "unattended_package", ring_factory: Callable[[Any], Any] | None = None,
                serve: bool = False) -> Env:
        ring = H.FakeRing(video_bytes, jpeg_bytes)
        perceive = H.FakePerceive(default_trace)
        cegis, cal, active = H.FakeCegis(), H.FakeCalibrate(), H.FakeActive()
        H.FakeMonitor.instances.clear()
        svc_kw: dict[str, Any] = dict(
            perceive=perceive, run_cegis=cegis, example_cls=H.Example, candidate_cls=H.Candidate,
            build_committee=active.build_committee, select_query=active.select_query, calibrate=cal,
            monitor_cls=H.FakeMonitor, deployed_rule_cls=H.DeployedRule, event_input_cls=H.EventInput)
        services = Services(disable=disable, ring_factory=ring_factory or (lambda auth: ring), **svc_kw)
        state = build_state(tmp_path, services, config)
        app = create_app(state=state, start_background=start_background)
        if serve:
            import httpx
            served = _Served(app)
            client: Any = httpx.Client(base_url=served.base_url, timeout=30.0)
            closers.append(served.close)
            closers.append(client.close)
        else:
            client = TestClient(app)
            client.__enter__()
            closers.append(lambda c=client: c.__exit__(None, None, None))
        return Env(SchemaClient(client), state, ring, perceive, cegis, cal, active, services)

    yield factory
    for close in reversed(closers):
        close()


@pytest.fixture
def env(make_env) -> Env:
    return make_env()


@pytest.fixture
def renv(make_env) -> Env:
    """Concept (alpha 0.2) taught from 3 example labels; the 7 remaining fixture clips random-labelled negative."""
    env = make_env()
    env.seed_fixture_events(*H.ALL_FIXTURES)
    env.seed_fixture_events("perception_failed")
    env.cid = env.new_concept(alpha=0.2)
    return H.teach_and_calibrate(env)
