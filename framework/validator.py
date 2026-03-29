from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .models import Assertion, Scenario, Step


ALLOWED_TOP = {"meta", "config", "steps", "assertions", "output"}
ALLOWED_META = {"name", "version", "platform", "tags"}
ALLOWED_CONFIG = {"timeoutMs", "seed", "artifactsDir"}
ALLOWED_STEP = {"id", "command", "args"}
ALLOWED_ASSERT = {"id", "type", "target"}
ALLOWED_OUTPUT = {"report"}
SUPPORTED_COMMANDS = {"tap", "navigate", "act", "screenshot", "wait", "source"}


def _validate_tap_args(args: Dict[str, Any], path: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    has_target = "target" in args
    has_x = "x" in args
    has_y = "y" in args

    if has_target:
        if has_x or has_y:
            issues.append(ValidationIssue("error", "ARG_ERROR", "tap cannot mix args.target with args.x/args.y", path))
        return issues

    if has_x != has_y:
        issues.append(ValidationIssue("error", "ARG_ERROR", "tap coordinate mode requires both args.x and args.y", path))
        return issues

    if not has_x and not has_y:
        issues.append(ValidationIssue("error", "ARG_ERROR", "tap requires args.target or args.x/args.y", path))
        return issues

    if "normalized" in args and not isinstance(args["normalized"], bool):
        issues.append(ValidationIssue("error", "ARG_ERROR", "tap args.normalized must be boolean", path))
    return issues


@dataclass
class ValidationIssue:
    severity: str  # error | warning
    code: str
    message: str
    path: str


def _unknown_fields(obj: Dict[str, Any], allowed: set[str], path: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for key in obj.keys():
        if key not in allowed:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="UNKNOWN_FIELD",
                    message=f"Unknown field '{key}'",
                    path=f"{path}.{key}" if path else key,
                )
            )
    return issues


def _required(obj: Dict[str, Any], fields: List[str], path: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for f in fields:
        if f not in obj:
            issues.append(ValidationIssue("error", "MISSING_REQUIRED", f"Missing required field '{f}'", path))
    return issues


def parse_and_validate(path: str) -> Tuple[Scenario | None, List[ValidationIssue]]:
    issues: List[ValidationIssue] = []
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        return None, [ValidationIssue("error", "TYPE_ERROR", "Scenario root must be object", "$")]

    issues.extend(_unknown_fields(raw, ALLOWED_TOP, "$"))
    issues.extend(_required(raw, ["meta", "config", "steps"], "$"))

    meta = raw.get("meta", {})
    config = raw.get("config", {})
    steps_raw = raw.get("steps", [])
    asserts_raw = raw.get("assertions", [])
    output = raw.get("output", {})

    if isinstance(meta, dict):
        issues.extend(_unknown_fields(meta, ALLOWED_META, "$.meta"))
        issues.extend(_required(meta, ["name", "version", "platform"], "$.meta"))
    else:
        issues.append(ValidationIssue("error", "TYPE_ERROR", "meta must be object", "$.meta"))

    if isinstance(config, dict):
        issues.extend(_unknown_fields(config, ALLOWED_CONFIG, "$.config"))
    else:
        issues.append(ValidationIssue("error", "TYPE_ERROR", "config must be object", "$.config"))

    steps: List[Step] = []
    if not isinstance(steps_raw, list) or not steps_raw:
        issues.append(ValidationIssue("error", "TYPE_ERROR", "steps must be non-empty list", "$.steps"))
    else:
        for i, s in enumerate(steps_raw):
            p = f"$.steps[{i}]"
            if not isinstance(s, dict):
                issues.append(ValidationIssue("error", "TYPE_ERROR", "step must be object", p))
                continue
            issues.extend(_unknown_fields(s, ALLOWED_STEP, p))
            issues.extend(_required(s, ["id", "command", "args"], p))
            cmd = s.get("command")
            if isinstance(cmd, str) and cmd not in SUPPORTED_COMMANDS:
                issues.append(ValidationIssue("error", "UNSUPPORTED_COMMAND", f"Unsupported command '{cmd}'", f"{p}.command"))
            if cmd == "tap" and isinstance(s.get("args"), dict):
                issues.extend(_validate_tap_args(s["args"], f"{p}.args"))
            if cmd == "navigate" and isinstance(s.get("args"), dict) and "to" not in s["args"]:
                issues.append(ValidationIssue("error", "ARG_ERROR", "navigate requires args.to", f"{p}.args"))
            if cmd == "screenshot" and isinstance(s.get("args"), dict) and "label" not in s["args"]:
                issues.append(ValidationIssue("warning", "DETERMINISM_WARNING", "screenshot missing label may reduce determinism", f"{p}.args"))
            if cmd == "wait" and isinstance(s.get("args"), dict) and "ms" not in s["args"]:
                issues.append(ValidationIssue("error", "ARG_ERROR", "wait requires args.ms", f"{p}.args"))
            if isinstance(s.get("id"), str) and isinstance(cmd, str) and isinstance(s.get("args"), dict):
                steps.append(Step(id=s["id"], command=cmd, args=s["args"]))

    assertions: List[Assertion] = []
    if asserts_raw is None:
        asserts_raw = []
    if isinstance(asserts_raw, list):
        for i, a in enumerate(asserts_raw):
            p = f"$.assertions[{i}]"
            if not isinstance(a, dict):
                issues.append(ValidationIssue("error", "TYPE_ERROR", "assertion must be object", p))
                continue
            issues.extend(_unknown_fields(a, ALLOWED_ASSERT, p))
            issues.extend(_required(a, ["id", "type", "target"], p))
            if all(k in a for k in ["id", "type", "target"]):
                assertions.append(Assertion(id=a["id"], type=a["type"], target=a["target"]))
    else:
        issues.append(ValidationIssue("error", "TYPE_ERROR", "assertions must be list", "$.assertions"))

    if isinstance(output, dict):
        issues.extend(_unknown_fields(output, ALLOWED_OUTPUT, "$.output"))
    else:
        issues.append(ValidationIssue("error", "TYPE_ERROR", "output must be object", "$.output"))

    platform = meta.get("platform") if isinstance(meta, dict) else None
    if platform not in {"ios", "android"}:
        issues.append(ValidationIssue("error", "INPUT_ERROR", "meta.platform must be ios|android", "$.meta.platform"))

    if isinstance(config, dict) and "seed" not in config:
        issues.append(ValidationIssue("warning", "DETERMINISM_WARNING", "config.seed is missing", "$.config"))

    if any(i.severity == "error" for i in issues):
        return None, issues

    scenario = Scenario(
        meta=meta,
        config=config,
        steps=steps,
        assertions=assertions,
        output=output,
    )
    return scenario, issues
