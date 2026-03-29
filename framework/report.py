from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from .utils import canonical_json, ensure_dir


def _junit_xml(run: Dict) -> str:
    tests = len(run["steps"])
    failures = sum(1 for s in run["steps"] if s["status"] != "ok")
    lines: List[str] = []
    lines.append(f'<testsuite name="{run["run_id"]}" tests="{tests}" failures="{failures}">')
    for s in run["steps"]:
        lines.append(f'  <testcase name="{s["id"]}" classname="visor.{run["platform"]}" time="{s["duration_ms"] / 1000:.3f}">')
        if s["status"] != "ok":
            msg = (s.get("error") or {}).get("message", "step failed")
            lines.append(f"    <failure message=\"{msg}\" />")
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def _materialize_artifacts(root: Path, artifact_paths: List[str]) -> List[str]:
    screenshots_dir = ensure_dir(root / "screenshots")
    sources_dir = ensure_dir(root / "sources")
    persisted: List[str] = []
    for i, artifact in enumerate(artifact_paths, start=1):
        src = Path(artifact)
        if not src.exists():
            continue
        base_dir = screenshots_dir if src.suffix.lower() == ".png" else sources_dir
        dest = base_dir / f"{i:03d}-{src.name}"
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        persisted.append(str(dest))
    return persisted


def write_reports(result, report_dir: str) -> Dict[str, str]:
    root = ensure_dir(Path(report_dir) / result.run_id)
    env = ensure_dir(root / "env")

    payload = asdict(result)
    persisted_artifacts = _materialize_artifacts(root, result.artifacts)
    payload["artifacts"] = persisted_artifacts
    result.artifacts = persisted_artifacts

    summary_txt = root / "summary.txt"
    summary_json = root / "summary.json"
    junit_xml = root / "junit.xml"
    timeline_log = root / "timeline.log"

    summary_txt.write_text(
        "\n".join(
            [
                f"run_id: {result.run_id}",
                f"platform: {result.platform}",
                f"device: {result.device}",
                f"status: {result.status.value}",
                f"determinism_signature: {result.determinism_signature}",
                f"artifact_count: {len(result.artifacts)}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary_json.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    junit_xml.write_text(_junit_xml(payload), encoding="utf-8")

    timeline_lines = [f"{i + 1:03d} {s.id} {s.command} {s.status.value} {s.duration_ms}ms" for i, s in enumerate(result.steps)]
    timeline_log.write_text("\n".join(timeline_lines) + "\n", encoding="utf-8")

    (env / "runtime.json").write_text(
        json.dumps({"seed": result.seed, "started_at": result.started_at, "ended_at": result.ended_at}, indent=2) + "\n",
        encoding="utf-8",
    )
    (env / "device.json").write_text(json.dumps({"platform": result.platform, "device": result.device}, indent=2) + "\n", encoding="utf-8")

    report_html = root / "report.html"
    report_html.write_text(
        f"<html><body><h1>{result.run_id}</h1><p>Status: {result.status.value}</p><p>Artifacts: {len(result.artifacts)}</p></body></html>\n",
        encoding="utf-8",
    )

    return {
        "summary": str(summary_txt),
        "json": str(summary_json),
        "junit": str(junit_xml),
        "timeline": str(timeline_log),
        "html": str(report_html),
    }
