#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from dataclasses import asdict
from urllib.parse import urlparse

from framework.adapters import DEFAULT_SERVER_URL, get_adapter
from framework.errors import make_error
from framework.models import CommandResponse, ErrorCode, Status
from framework.report import write_reports
from framework.runner import determinism_check, run_scenario
from framework.utils import make_id, utc_now_iso
from framework.validator import parse_and_validate


def _envelope_ok(command_id: str, started_at: str, artifacts=None, next_action: str = "") -> CommandResponse:
    return CommandResponse(
        status=Status.OK,
        command_id=command_id,
        started_at=started_at,
        ended_at=utc_now_iso(),
        artifacts=artifacts or [],
        next_action=next_action,
    )


def _envelope_fail(command_id: str, started_at: str, code: ErrorCode, message: str, cause: str, next_step: str) -> CommandResponse:
    return CommandResponse(
        status=Status.FAIL,
        command_id=command_id,
        started_at=started_at,
        ended_at=utc_now_iso(),
        artifacts=[],
        next_action=next_step,
        error=make_error(code, message, cause, next_step),
    )


def cmd_validate(args) -> int:
    command_id = make_id("cmd")
    started_at = utc_now_iso()
    try:
        scenario, issues = parse_and_validate(args.scenario)
    except Exception as exc:
        response = _envelope_fail(command_id, started_at, ErrorCode.INPUT_ERROR, "Validation failed", str(exc), "Fix scenario JSON and rerun validate")
        print(json.dumps(asdict(response), indent=2))
        return 1

    response = _envelope_ok(command_id, started_at, next_action="run")
    response.data = {
        "valid": scenario is not None,
        "issues": [asdict(i) for i in issues],
    }
    print(json.dumps(asdict(response), indent=2))
    return 0 if scenario is not None else 1


def _resolved_runtime(args, scenario):
    platform = args.platform or scenario.meta["platform"]
    device = args.device or ("emulator-5554" if platform == "android" else "iPhone 17 Pro")
    timeout = args.timeout or scenario.config.get("timeoutMs", 2500)
    output_dir = args.output or scenario.config.get("artifactsDir", "artifacts")
    server_url = args.server_url or DEFAULT_SERVER_URL
    use_mock = bool(args.mock)
    app_id = args.app_id
    attach_to_running = bool(args.attach)
    scenario.meta["platform"] = platform
    return platform, device, timeout, output_dir, server_url, use_mock, app_id, attach_to_running


def _non_mock_preflight(platform: str, device: str, server_url: str):
    parsed = urlparse(server_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4723

    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError as exc:
        raise RuntimeError(
            f"Cannot reach Appium server at {host}:{port} ({exc}). "
            f"Start Appium and ensure {platform} target '{device}' is booted."
        )


def cmd_run(args) -> int:
    command_id = make_id("cmd")
    started_at = utc_now_iso()

    scenario, issues = parse_and_validate(args.scenario)
    if scenario is None:
        response = _envelope_fail(
            command_id,
            started_at,
            ErrorCode.INPUT_ERROR,
            "Scenario validation failed",
            "One or more schema violations",
            "Run `visor validate <file>` and resolve errors",
        )
        response.data = {"issues": [asdict(i) for i in issues]}
        print(json.dumps(asdict(response), indent=2))
        return 1

    platform, device, timeout, output_dir, server_url, use_mock, app_id, attach_to_running = _resolved_runtime(args, scenario)

    try:
        if not use_mock:
            _non_mock_preflight(platform, device, server_url)
        adapter = get_adapter(
            platform,
            server_url=server_url,
            device=device,
            use_mock=use_mock,
            app_id=app_id,
            attach_to_running=attach_to_running,
        )
    except Exception as exc:
        response = _envelope_fail(
            command_id,
            started_at,
            ErrorCode.TARGET_ERROR,
            "Failed to initialize platform target",
            str(exc),
            "For local non-mock runs: start Appium on --server-url, boot target emulator/simulator, and install runtime deps from requirements.txt",
        )
        print(json.dumps(asdict(response), indent=2))
        return 1

    result = run_scenario(scenario, adapter=adapter, device=device, timeout_ms=timeout, artifact_base_dir=output_dir)
    outputs = write_reports(result, output_dir)

    if result.status == Status.FAIL and result.error is not None:
        response = _envelope_fail(
            command_id,
            started_at,
            result.error.code,
            result.error.message,
            result.error.likely_cause,
            result.error.next_step,
        )
        response.artifacts = list(outputs.values())
    else:
        response = _envelope_ok(command_id, started_at, artifacts=list(outputs.values()), next_action="report")

    response.data = {"run": asdict(result), "warnings": [asdict(i) for i in issues if i.severity == "warning"]}
    print(json.dumps(asdict(response), indent=2))
    return 0 if result.status == Status.OK else 2


def cmd_benchmark(args) -> int:
    command_id = make_id("cmd")
    started_at = utc_now_iso()
    scenario, issues = parse_and_validate(args.scenario)
    if scenario is None:
        response = _envelope_fail(command_id, started_at, ErrorCode.INPUT_ERROR, "Scenario validation failed", "Invalid scenario", "Fix schema errors before benchmark")
        response.data = {"issues": [asdict(i) for i in issues]}
        print(json.dumps(asdict(response), indent=2))
        return 1

    platform, device, timeout, output_dir, server_url, use_mock, app_id, attach_to_running = _resolved_runtime(args, scenario)

    signatures = []
    run_ids = []
    failures = 0

    if not use_mock:
        try:
            _non_mock_preflight(platform, device, server_url)
        except Exception as exc:
            response = _envelope_fail(
                command_id,
                started_at,
                ErrorCode.TARGET_ERROR,
                "Failed benchmark preflight for non-mock runtime",
                str(exc),
                "Start Appium, verify local device target, then rerun benchmark",
            )
            print(json.dumps(asdict(response), indent=2))
            return 1

    for _ in range(args.runs):
        try:
            adapter = get_adapter(
                platform,
                server_url=server_url,
                device=device,
                use_mock=use_mock,
                app_id=app_id,
                attach_to_running=attach_to_running,
            )
            result = run_scenario(scenario, adapter=adapter, device=device, timeout_ms=timeout, artifact_base_dir=output_dir)
            write_reports(result, output_dir)
            signatures.append(result.determinism_signature)
            run_ids.append(result.run_id)
            if result.status != Status.OK:
                failures += 1
        except Exception:
            failures += 1

    score = determinism_check(signatures)
    pass_gate = score >= args.threshold and failures == 0

    response = _envelope_ok(command_id, started_at, next_action="report")
    response.data = {
        "runs": args.runs,
        "threshold": args.threshold,
        "determinismScore": score,
        "pass": pass_gate,
        "failures": failures,
        "runIds": run_ids,
    }
    print(json.dumps(asdict(response), indent=2))
    return 0 if pass_gate else 3


def cmd_report(args) -> int:
    command_id = make_id("cmd")
    started_at = utc_now_iso()
    response = _envelope_ok(command_id, started_at, next_action="none")
    response.data = {
        "message": f"Use output under {args.path}/<run-id>/summary.txt|summary.json|junit.xml|report.html",
        "path": args.path,
        "format": args.format,
    }
    print(json.dumps(asdict(response), indent=2))
    return 0


def cmd_action(command: str, args) -> int:
    command_id = make_id("cmd")
    started_at = utc_now_iso()
    try:
        adapter = get_adapter(
            args.platform,
            server_url=args.server_url,
            device=args.device,
            use_mock=args.mock,
            app_id=args.app_id,
            attach_to_running=args.attach,
        )
        fn = getattr(adapter, command)
        payload = fn(
            {
                k: v
                for k, v in vars(args).items()
                if k
                not in {
                    "command",
                    "platform",
                    "format",
                    "output",
                    "timeout",
                    "verbose",
                    "func",
                    "server_url",
                    "device",
                    "mock",
                    "seed",
                    "app_id",
                    "attach",
                }
                and v is not None
            }
        )
        adapter.close()
        artifacts = []
        if isinstance(payload, dict):
            maybe_path = payload.get("args", {}).get("path")
            if maybe_path:
                artifacts.append(maybe_path)
        response = _envelope_ok(command_id, started_at, artifacts=artifacts, next_action="run")
        response.data = payload
        print(json.dumps(asdict(response), indent=2))
        return 0
    except Exception as exc:
        response = _envelope_fail(command_id, started_at, ErrorCode.ACTION_ERROR, f"{command} failed", str(exc), "Check command args and retry")
        print(json.dumps(asdict(response), indent=2))
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="visor", description="Visor CLI for LLM-driven mobile interaction and artifact capture")
    p.add_argument("--platform", choices=["ios", "android"], default="android")
    p.add_argument("--device", default=None)
    p.add_argument("--timeout", type=int, default=None)
    p.add_argument("--output", default=None)
    p.add_argument("--format", choices=["text", "json"], default="json")
    p.add_argument("--seed", type=int)
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    p.add_argument("--app-id", default=None)
    p.add_argument("--attach", action="store_true")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--verbose", action="store_true")

    sub = p.add_subparsers(dest="command", required=True)

    for c in ["tap", "navigate", "act", "screenshot", "wait", "source"]:
        sp = sub.add_parser(c)
        sp.add_argument("--platform", choices=["ios", "android"], default="android")
        sp.add_argument("--device", default=None)
        sp.add_argument("--server-url", default=DEFAULT_SERVER_URL)
        sp.add_argument("--app-id", default=None)
        sp.add_argument("--attach", action="store_true")
        sp.add_argument("--format", choices=["text", "json"], default="json")
        sp.add_argument("--mock", action="store_true")
        if c == "tap":
            sp.add_argument("--target")
            sp.add_argument("--x", type=float)
            sp.add_argument("--y", type=float)
            sp.add_argument("--normalized", action="store_true")
        elif c == "navigate":
            sp.add_argument("--to", required=True)
        elif c == "act":
            sp.add_argument("--name", required=True)
            sp.add_argument("--target")
            sp.add_argument("--value")
        elif c == "screenshot":
            sp.add_argument("--label", required=True)
        elif c == "wait":
            sp.add_argument("--ms", required=True, type=int)
        elif c == "source":
            sp.add_argument("--label", default="source")
            sp.add_argument("--path")
        sp.set_defaults(func=lambda a, _c=c: cmd_action(_c, a))

    spv = sub.add_parser("validate")
    spv.add_argument("scenario")
    spv.add_argument("--format", choices=["text", "json"], default="json")
    spv.set_defaults(func=cmd_validate)

    spr = sub.add_parser("run")
    spr.add_argument("scenario")
    spr.add_argument("--platform", choices=["ios", "android"])
    spr.add_argument("--device")
    spr.add_argument("--timeout", type=int)
    spr.add_argument("--output")
    spr.add_argument("--format", choices=["text", "json"], default="json")
    spr.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    spr.add_argument("--app-id")
    spr.add_argument("--attach", action="store_true")
    spr.add_argument("--mock", action="store_true")
    spr.set_defaults(func=cmd_run)

    spb = sub.add_parser("benchmark")
    spb.add_argument("scenario")
    spb.add_argument("--runs", type=int, default=20)
    spb.add_argument("--threshold", type=float, default=95.0)
    spb.add_argument("--platform", choices=["ios", "android"])
    spb.add_argument("--device")
    spb.add_argument("--timeout", type=int)
    spb.add_argument("--output")
    spb.add_argument("--format", choices=["text", "json"], default="json")
    spb.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    spb.add_argument("--app-id")
    spb.add_argument("--attach", action="store_true")
    spb.add_argument("--mock", action="store_true")
    spb.set_defaults(func=cmd_benchmark)

    spp = sub.add_parser("report")
    spp.add_argument("path", nargs="?", default="artifacts")
    spp.add_argument("--format", choices=["text", "json"], default="json")
    spp.set_defaults(func=cmd_report)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
