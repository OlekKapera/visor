from __future__ import annotations

from pathlib import Path
import copy
import time
from typing import Dict, List, Tuple

from .adapters import PlatformAdapter
from .errors import make_error
from .models import ErrorCode, RunResult, Status, StepResult
from .utils import make_id, signature_for, utc_now_iso


def _run_step(adapter: PlatformAdapter, command: str, args: Dict) -> Dict:
    if command == "tap":
        return adapter.tap(args)
    if command == "navigate":
        return adapter.navigate(args)
    if command == "act":
        return adapter.act(args)
    if command == "screenshot":
        return adapter.screenshot(args)
    if command == "wait":
        return adapter.wait(args)
    if command == "source":
        return adapter.source(args)
    raise ValueError(f"Unsupported command: {command}")


def _evaluate_assertions(adapter: PlatformAdapter, assertions) -> Tuple[List[Dict], bool, List[str]]:
    results: List[Dict] = []
    ok = True
    failed_targets: List[str] = []
    for a in assertions:
        status = "passed"
        details = ""
        if a.type == "visible":
            visible = adapter.exists(a.target)
            if not visible:
                status = "failed"
                details = f"Target not visible: {a.target}"
                ok = False
                failed_targets.append(a.target)
        else:
            status = "failed"
            details = f"Unsupported assertion type: {a.type}"
            ok = False
            failed_targets.append(a.target)

        results.append({"id": a.id, "type": a.type, "target": a.target, "status": status, "details": details})
    return results, ok, failed_targets


def _signature_safe_details(details: Dict) -> Dict:
    safe = copy.deepcopy(details)
    args = safe.get("args")
    if isinstance(args, dict):
        # path includes run-id and varies run-to-run; exclude from determinism signature
        args.pop("path", None)
    return safe


def run_scenario(scenario, adapter: PlatformAdapter, device: str = "local", timeout_ms: int | None = None, artifact_base_dir: str | None = None) -> RunResult:
    started_at = utc_now_iso()
    run_id = make_id("run")
    platform = scenario.meta["platform"]
    step_results: List[StepResult] = []
    artifacts: List[str] = []
    top_error = None

    screenshot_dir: Path | None = None
    source_dir: Path | None = None
    if artifact_base_dir:
        screenshot_dir = Path(artifact_base_dir) / run_id / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        source_dir = Path(artifact_base_dir) / run_id / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)

    try:
        for step in scenario.steps:
            start = time.perf_counter()
            try:
                step_args = dict(step.args)
                if step.command == "screenshot" and screenshot_dir is not None:
                    label = step_args.get("label", step.id)
                    step_args["path"] = str(screenshot_dir / f"{label}.png")
                if step.command == "source" and source_dir is not None:
                    label = step_args.get("label", step.id)
                    step_args["path"] = str(source_dir / f"{label}.xml")

                details = _run_step(adapter, step.command, step_args)
                duration = int((time.perf_counter() - start) * 1000)
                result = StepResult(
                    id=step.id,
                    command=step.command,
                    status=Status.OK,
                    duration_ms=duration,
                    details=details,
                )
                if step.command in {"screenshot", "source"}:
                    artifacts.append(details["args"].get("path", details["args"].get("file", "")))
                if timeout_ms and duration > timeout_ms:
                    result.status = Status.FAIL
                    result.error = make_error(
                        ErrorCode.ACTION_ERROR,
                        f"Step '{step.id}' exceeded timeout",
                        "Device/app was too slow for configured timeout",
                        "Increase --timeout or optimize target action",
                    )
            except Exception as exc:
                duration = int((time.perf_counter() - start) * 1000)
                result = StepResult(
                    id=step.id,
                    command=step.command,
                    status=Status.FAIL,
                    duration_ms=duration,
                    details={},
                    error=make_error(
                        ErrorCode.ACTION_ERROR,
                        f"Step '{step.id}' failed",
                        str(exc),
                        "Inspect step args and platform adapter support",
                    ),
                )
            step_results.append(result)

        assertions, asserts_ok, failed_targets = _evaluate_assertions(adapter, scenario.assertions)

        steps_ok = all(s.status == Status.OK for s in step_results)
        if not steps_ok:
            top_error = make_error(
                ErrorCode.ACTION_ERROR,
                "Run failed due to one or more action step failures",
                "At least one command execution step returned failure",
                "Inspect failed step error payloads in run.steps and retry",
            )
        if not asserts_ok:
            first_failed = failed_targets[0] if failed_targets else "unknown target"
            top_error = make_error(
                ErrorCode.ASSERTION_ERROR,
                "Run failed due to assertion failure",
                f"Expected UI target was not satisfied: {first_failed}",
                "Verify selector correctness and app state before assertion step",
            )

        all_pass = steps_ok and asserts_ok
        ended_at = utc_now_iso()
        signature_input = {
            "platform": platform,
            "steps": [
                {
                    "id": s.id,
                    "command": s.command,
                    "status": s.status.value,
                    "details": _signature_safe_details(s.details),
                }
                for s in step_results
            ],
            "assertions": assertions,
        }

        return RunResult(
            run_id=run_id,
            platform=platform,
            device=device,
            started_at=started_at,
            ended_at=ended_at,
            status=Status.OK if all_pass else Status.FAIL,
            steps=step_results,
            assertions=assertions,
            artifacts=artifacts,
            determinism_signature=signature_for(signature_input),
            seed=scenario.config.get("seed"),
            error=top_error,
        )
    finally:
        adapter.close()


def determinism_check(signatures: List[str]) -> float:
    if not signatures:
        return 0.0
    baseline = signatures[0]
    same = sum(1 for s in signatures if s == baseline)
    return round((same / len(signatures)) * 100, 2)
