#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from urllib.parse import urlparse

from framework.adapters import DEFAULT_SERVER_URL, get_adapter
from framework.appium_lifecycle import (
    DEFAULT_STARTUP_TIMEOUT_SECONDS,
    is_appium_reachable,
    start_managed_appium,
    status_managed_appium,
    stop_managed_appium,
)
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
    auto_start_appium = not bool(getattr(args, "no_auto_start_appium", False))
    appium_cmd = getattr(args, "appium_cmd", None)
    startup_timeout = float(getattr(args, "startup_timeout", DEFAULT_STARTUP_TIMEOUT_SECONDS))
    scenario.meta["platform"] = platform
    return (
        platform,
        device,
        timeout,
        output_dir,
        server_url,
        use_mock,
        app_id,
        attach_to_running,
        auto_start_appium,
        appium_cmd,
        startup_timeout,
    )


def _ensure_non_mock_runtime(
    platform: str,
    device: str,
    server_url: str,
    auto_start_appium: bool,
    appium_cmd: str | None,
    startup_timeout: float,
):
    parsed = urlparse(server_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4723

    if is_appium_reachable(server_url, timeout=2.0):
        return {"serverUrl": server_url, "started": False}

    if not auto_start_appium:
        raise RuntimeError(
            f"Cannot reach Appium server at {host}:{port}. "
            f"Start Appium and ensure {platform} target '{device}' is booted."
        )

    return start_managed_appium(
        server_url=server_url,
        appium_cmd=appium_cmd,
        startup_timeout_s=startup_timeout,
    )


def _stop_auto_started_appium(runtime_state: dict | None) -> None:
    if not runtime_state or not runtime_state.get("started"):
        return
    server_url = runtime_state.get("serverUrl")
    if not server_url:
        return

    try:
        stop_managed_appium(server_url=server_url, force=False)
    except Exception:
        stop_managed_appium(server_url=server_url, force=True)


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

    (
        platform,
        device,
        timeout,
        output_dir,
        server_url,
        use_mock,
        app_id,
        attach_to_running,
        auto_start_appium,
        appium_cmd,
        startup_timeout,
    ) = _resolved_runtime(args, scenario)

    runtime_state = None
    cleanup_error = None

    try:
        if not use_mock:
            runtime_state = _ensure_non_mock_runtime(platform, device, server_url, auto_start_appium, appium_cmd, startup_timeout)
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
            (
                "For local non-mock runs: install Appium runtime, "
                "run `visor start` (or remove --no-auto-start-appium), "
                "boot target emulator/simulator, and install runtime deps from requirements.txt"
            ),
        )
        print(json.dumps(asdict(response), indent=2))
        return 1

    try:
        result = run_scenario(scenario, adapter=adapter, device=device, timeout_ms=timeout, artifact_base_dir=output_dir)
        outputs = write_reports(result, output_dir)
    finally:
        if runtime_state and runtime_state.get("started"):
            try:
                _stop_auto_started_appium(runtime_state)
            except Exception as exc:
                cleanup_error = exc

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

    if cleanup_error is not None:
        response = _envelope_fail(
            command_id,
            started_at,
            ErrorCode.TARGET_ERROR,
            "Scenario completed but failed to stop auto-started Appium",
            str(cleanup_error),
            "Inspect .visor/appium logs and stop Appium manually",
        )
        response.artifacts = list(outputs.values())
        response.data = {"run": asdict(result), "warnings": [asdict(i) for i in issues if i.severity == "warning"]}
        print(json.dumps(asdict(response), indent=2))
        return 1

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

    (
        platform,
        device,
        timeout,
        output_dir,
        server_url,
        use_mock,
        app_id,
        attach_to_running,
        auto_start_appium,
        appium_cmd,
        startup_timeout,
    ) = _resolved_runtime(args, scenario)

    signatures = []
    run_ids = []
    failures = 0

    runtime_state = None
    cleanup_error = None

    if not use_mock:
        try:
            runtime_state = _ensure_non_mock_runtime(platform, device, server_url, auto_start_appium, appium_cmd, startup_timeout)
        except Exception as exc:
            response = _envelope_fail(
                command_id,
                started_at,
                ErrorCode.TARGET_ERROR,
                "Failed benchmark preflight for non-mock runtime",
                str(exc),
                "Start Appium (or allow auto-start), verify local device target, then rerun benchmark",
            )
            print(json.dumps(asdict(response), indent=2))
            return 1

    try:
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
    finally:
        if runtime_state and runtime_state.get("started"):
            try:
                _stop_auto_started_appium(runtime_state)
            except Exception as exc:
                cleanup_error = exc

    score = determinism_check(signatures)
    pass_gate = score >= args.threshold and failures == 0

    if cleanup_error is not None:
        response = _envelope_fail(
            command_id,
            started_at,
            ErrorCode.TARGET_ERROR,
            "Benchmark completed but failed to stop auto-started Appium",
            str(cleanup_error),
            "Inspect .visor/appium logs and stop Appium manually",
        )
        response.data = {
            "runs": args.runs,
            "threshold": args.threshold,
            "determinismScore": score,
            "pass": False,
            "failures": failures,
            "runIds": run_ids,
        }
        print(json.dumps(asdict(response), indent=2))
        return 1

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
    runtime_state = None
    cleanup_error = None
    payload = {}
    artifacts = []
    action_error = None
    adapter = None
    try:
        if not args.mock:
            runtime_state = _ensure_non_mock_runtime(
                args.platform,
                args.device or ("emulator-5554" if args.platform == "android" else "iPhone 17 Pro"),
                args.server_url,
                not bool(getattr(args, "no_auto_start_appium", False)),
                getattr(args, "appium_cmd", None),
                float(getattr(args, "startup_timeout", DEFAULT_STARTUP_TIMEOUT_SECONDS)),
            )

        adapter = get_adapter(
            args.platform,
            server_url=args.server_url,
            device=args.device,
            use_mock=args.mock,
            app_id=args.app_id,
            attach_to_running=args.attach,
        )
    except Exception as exc:
        action_error = exc
    else:
        try:
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
                        "appium_cmd",
                        "startup_timeout",
                        "no_auto_start_appium",
                    }
                    and v is not None
                }
            )
        except Exception as exc:
            action_error = exc
        finally:
            adapter.close()

        if isinstance(payload, dict):
            maybe_path = payload.get("args", {}).get("path")
            if maybe_path:
                artifacts.append(maybe_path)
    finally:
        if runtime_state and runtime_state.get("started"):
            try:
                _stop_auto_started_appium(runtime_state)
            except Exception as exc:
                cleanup_error = exc

    if action_error is not None:
        cause = str(action_error)
        if cleanup_error is not None:
            cause = f"{cause}; additionally failed to stop auto-started Appium: {cleanup_error}"
        response = _envelope_fail(command_id, started_at, ErrorCode.ACTION_ERROR, f"{command} failed", cause, "Check command args and retry")
        response.data = payload if isinstance(payload, dict) else {}
        print(json.dumps(asdict(response), indent=2))
        return 1

    if cleanup_error is not None:
        response = _envelope_fail(
            command_id,
            started_at,
            ErrorCode.TARGET_ERROR,
            f"{command} completed but failed to stop auto-started Appium",
            str(cleanup_error),
            "Inspect .visor/appium logs and stop Appium manually",
        )
        response.data = payload if isinstance(payload, dict) else {}
        print(json.dumps(asdict(response), indent=2))
        return 1

    response = _envelope_ok(command_id, started_at, artifacts=artifacts, next_action="run")
    response.data = payload
    print(json.dumps(asdict(response), indent=2))
    return 0


def cmd_start(args) -> int:
    command_id = make_id("cmd")
    started_at = utc_now_iso()
    try:
        status = start_managed_appium(
            server_url=args.server_url,
            appium_cmd=args.appium_cmd,
            startup_timeout_s=args.startup_timeout,
        )
        response = _envelope_ok(command_id, started_at, next_action="run")
        response.data = status
        print(json.dumps(asdict(response), indent=2))
        return 0
    except Exception as exc:
        response = _envelope_fail(
            command_id,
            started_at,
            ErrorCode.TARGET_ERROR,
            "Failed to start Appium",
            str(exc),
            "Install Appium, check --appium-cmd, and inspect .visor/appium/*.log",
        )
        print(json.dumps(asdict(response), indent=2))
        return 1


def cmd_status(args) -> int:
    command_id = make_id("cmd")
    started_at = utc_now_iso()
    status = status_managed_appium(server_url=args.server_url)
    response = _envelope_ok(command_id, started_at, next_action="run" if status["reachable"] else "start")
    response.data = status
    print(json.dumps(asdict(response), indent=2))
    return 0


def cmd_stop(args) -> int:
    command_id = make_id("cmd")
    started_at = utc_now_iso()
    try:
        result = stop_managed_appium(server_url=args.server_url, force=bool(args.force))
        response = _envelope_ok(command_id, started_at, next_action="none")
        response.data = result
        print(json.dumps(asdict(response), indent=2))
        return 0
    except Exception as exc:
        response = _envelope_fail(
            command_id,
            started_at,
            ErrorCode.TARGET_ERROR,
            "Failed to stop managed Appium",
            str(exc),
            "Retry with --force or check process state manually",
        )
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
    p.add_argument("--appium-cmd", default=None)
    p.add_argument("--startup-timeout", type=float, default=DEFAULT_STARTUP_TIMEOUT_SECONDS)
    p.add_argument("--no-auto-start-appium", action="store_true")
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
        sp.add_argument("--appium-cmd", default=None)
        sp.add_argument("--startup-timeout", type=float, default=DEFAULT_STARTUP_TIMEOUT_SECONDS)
        sp.add_argument("--no-auto-start-appium", action="store_true")
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
    spr.add_argument("--appium-cmd")
    spr.add_argument("--startup-timeout", type=float, default=DEFAULT_STARTUP_TIMEOUT_SECONDS)
    spr.add_argument("--no-auto-start-appium", action="store_true")
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
    spb.add_argument("--appium-cmd")
    spb.add_argument("--startup-timeout", type=float, default=DEFAULT_STARTUP_TIMEOUT_SECONDS)
    spb.add_argument("--no-auto-start-appium", action="store_true")
    spb.add_argument("--attach", action="store_true")
    spb.add_argument("--mock", action="store_true")
    spb.set_defaults(func=cmd_benchmark)

    spp = sub.add_parser("report")
    spp.add_argument("path", nargs="?", default="artifacts")
    spp.add_argument("--format", choices=["text", "json"], default="json")
    spp.set_defaults(func=cmd_report)

    sps = sub.add_parser("start")
    sps.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    sps.add_argument("--appium-cmd")
    sps.add_argument("--startup-timeout", type=float, default=DEFAULT_STARTUP_TIMEOUT_SECONDS)
    sps.add_argument("--format", choices=["text", "json"], default="json")
    sps.set_defaults(func=cmd_start)

    spt = sub.add_parser("status")
    spt.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    spt.add_argument("--format", choices=["text", "json"], default="json")
    spt.set_defaults(func=cmd_status)

    spx = sub.add_parser("stop")
    spx.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    spx.add_argument("--force", action="store_true")
    spx.add_argument("--format", choices=["text", "json"], default="json")
    spx.set_defaults(func=cmd_stop)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
