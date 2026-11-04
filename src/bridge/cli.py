"""Command line: demo, bench, manifest, serve."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from typing import TextIO

import uvicorn

from bridge.api import create_app
from bridge.config import Settings, load_dotenv
from bridge.container import build_container
from bridge.models import Decision, Principal, Role, TelemetryEvent
from bridge.salesforce import InMemorySalesforce, SalesforceClient
from bridge.samples import ACCOUNTS, SAMPLE_EVENTS

APPROVER = Principal(name="demo-approver", role=Role.APPROVER)


def _settings(live: bool) -> Settings | None:
    s = Settings.from_env()
    if live:
        return s if s.salesforce_enabled else None
    return dataclasses.replace(s, sf_client_id="", sf_client_secret="")


async def _demo(live: bool, out: TextIO) -> int:
    settings = _settings(live)
    if settings is None:
        print("--live needs SF_CLIENT_ID and SF_CLIENT_SECRET", file=out)
        return 2
    gateway = None if live else InMemorySalesforce(ACCOUNTS)
    c = build_container(settings, gateway=gateway)
    mode = "LIVE Salesforce" if live else "offline (in-memory CRM)"
    print(f"== Agentforce Enterprise Bridge demo [{mode}] ==", file=out)
    try:
        for raw in SAMPLE_EVENTS:
            r = await c.pipeline.process(TelemetryEvent.model_validate(raw))
            o = r.outcome
            print(
                f"[{r.account_key:<8}] action={r.action} "
                f"decision={o.decision.value if o else '-'} "
                f"{r.latency_ms:.2f}ms | {r.rationale}",
                file=out,
            )
            if o and o.decision is Decision.PENDING_APPROVAL:
                d = await c.tower.decide(
                    APPROVER, o.approval_id or "", True, "demo"
                )
                print(
                    f"    human approval -> {d.decision.value}: {d.detail}",
                    file=out,
                )
        await c.audit.flush()
        print(
            f"audit records: {len(c.audit.recent(500))}, "
            f"unsynced: {c.audit.pending_sync}",
            file=out,
        )
        print(c.metrics.render(), file=out, end="")
    finally:
        await c.aclose()
    return 0


async def _auth_check(out: TextIO) -> int:
    settings = Settings.from_env()
    if not settings.salesforce_enabled:
        print(
            "Salesforce is not configured: set SF_CLIENT_ID plus either "
            "SF_USERNAME + SF_PRIVATE_KEY[_PATH] (JWT) or SF_CLIENT_SECRET.",
            file=out,
        )
        return 2
    client = SalesforceClient(settings)
    try:
        info = await client.verify()
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=out)
        return 1
    finally:
        await client.aclose()
    print(f"OK: {json.dumps(info)}", file=out)
    return 0


async def _bench(n: int, out: TextIO) -> int:
    settings = dataclasses.replace(
        _settings(False) or Settings(),
        queue_capacity=n + 1,
        max_pending_approvals=n + 1,
    )
    c = build_container(settings, gateway=InMemorySalesforce(ACCOUNTS))
    await c.bus.start()
    start = time.perf_counter()
    for i in range(n):
        c.bus.publish_raw(dict(SAMPLE_EVENTS[i % len(SAMPLE_EVENTS)]))
    await c.bus.drain()
    elapsed = time.perf_counter() - start
    await c.bus.stop()
    print(
        f"events={n} throughput={n / elapsed:,.0f}/s "
        f"p50={c.metrics.percentile(50) * 1000:.3f}ms "
        f"p95={c.metrics.percentile(95) * 1000:.3f}ms "
        f"dlq={len(c.bus.dlq)}",
        file=out,
    )
    return 0


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    out = out or sys.stdout
    p = argparse.ArgumentParser(prog="bridge")
    p.add_argument("--env-file", default=".env", help="dotenv file to load")
    sub = p.add_subparsers(dest="cmd", required=True)
    demo = sub.add_parser("demo", help="run sample events end to end")
    demo.add_argument(
        "--live",
        action="store_true",
        help="use the real Salesforce org from SF_* env vars",
    )
    bench = sub.add_parser("bench", help="measure throughput and latency")
    bench.add_argument("-n", type=int, default=2000)
    sub.add_parser("auth-check", help="verify Salesforce credentials")
    sub.add_parser("manifest", help="print the Agentforce action catalog")
    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    args = p.parse_args(argv)
    load_dotenv(args.env_file)
    if args.cmd == "demo":
        return asyncio.run(_demo(args.live, out))
    if args.cmd == "auth-check":
        return asyncio.run(_auth_check(out))
    if args.cmd == "bench":
        return asyncio.run(_bench(args.n, out))
    if args.cmd == "manifest":
        c = build_container(Settings())
        print(json.dumps(c.registry.manifest(), indent=2), file=out)
        return 0
    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
