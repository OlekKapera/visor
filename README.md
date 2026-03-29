# Visor

Visor is a CLI that gives LLMs eyes into running mobile apps.

AI coding agents are fast, but they still guess UI outcomes from code.

Visor makes those agents evidence-driven: execute real actions, capture real UI evidence (screenshots + UI source), and verify expected vs actual behavior before calling work “done.”

Built for developers who want Claude/Codex-style agents to ship better UI changes with fewer regressions.

## Why this exists

Code can look correct while the UI is still wrong.

Visor helps close that gap by providing:
- real app interactions (`tap`, `act`, `navigate`, `wait`)
- real evidence capture (`screenshot`, `source`)
- structured run output and artifacts for automated comparison
- scenario validation and repeatability checks (`validate`, `benchmark`)

This enables an agent loop like: implement -> run app -> capture evidence -> compare expected vs actual -> fix.

Result: fewer “looks good in code review” failures and higher trust in agent-delivered UI work.

## Who this is for

- mobile app developers using AI coding agents
- teams that want evidence-based UI verification in agentic workflows
- engineers who need repeatable artifacts for debugging and review

## What Visor controls today

- iOS and Android targets via Appium
- native UI selectors and coordinate taps
- scenario-based execution with assertions
- report artifacts under `artifacts/<run-id>/...`

Scope today: mobile apps only.

Web app support is planned and coming soon.

## Why teams adopt it

- Ship faster with AI agents while keeping a verification layer
- Replace guesswork with artifact-backed UI checks
- Debug faster with reproducible run traces and evidence files
- Add determinism gates before merging agent-generated changes

## Install

```bash
pip install .
```

Or isolated install:

```bash
pipx install .
```

Entrypoints:
- `visor ...`
- `python3 -m visor ...`

## Quickstart (LLM verification loop)

Use JSON mode so agents can parse output reliably:

```bash
visor screenshot --platform android --app-id com.example.app --label before --format json
visor tap --platform android --x 0.91 --y 0.94 --normalized --app-id com.example.app --format json
visor wait --platform android --ms 800 --format json
visor source --platform android --app-id com.example.app --label after-ui --format json
visor screenshot --platform android --app-id com.example.app --label after --format json
```

The command response includes artifact paths. An LLM can inspect those files and compare expected vs actual UI state.

If your agent can read files, it can use Visor outputs as ground truth.

## Before/After verification example

Goal: verify that tapping `Increment` changes counter text from `0` to `1`.

1. Capture "before" evidence:
```bash
visor screenshot --platform android --app-id com.example.app --label counter-before --format json
visor source --platform android --app-id com.example.app --label counter-before-ui --format json
```

2. Perform action:
```bash
visor tap --platform android --app-id com.example.app --target Increment --format json
visor wait --platform android --ms 500 --format json
```

3. Capture "after" evidence:
```bash
visor screenshot --platform android --app-id com.example.app --label counter-after --format json
visor source --platform android --app-id com.example.app --label counter-after-ui --format json
```

4. Compare results:
- screenshots: visual change happened in expected region
- source XML: counter node changed from `0` to `1`
- if mismatch: agent updates implementation and reruns

This is the core value of Visor: agents verify real output, not just code intent.

## Scenario workflow

1. Validate scenario input:
```bash
visor validate scenarios/checkout-smoke.json --format json
```

2. Run scenario and write reports:
```bash
visor run scenarios/checkout-smoke.json --platform android --app-id com.example.app --output artifacts --format json
```

3. Check repeatability:
```bash
visor benchmark scenarios/checkout-smoke.json --platform android --app-id com.example.app --runs 20 --threshold 95 --format json
```

4. Print report location guidance:
```bash
visor report artifacts --format json
```

## Commands

- `tap`: tap by selector or coordinates (`--x/--y [--normalized]`)
- `navigate`: navigate to a target route/url (`--to`)
- `act`: action helpers (currently `type` and `back`)
- `screenshot`: save screenshot artifact (`--label`)
- `wait`: delay in milliseconds (`--ms`)
- `source`: dump current UI source as XML
- `validate`: schema and command validation for scenario JSON
- `run`: execute full scenario, assertions, and report generation
- `benchmark`: run scenario N times and compute determinism score
- `report`: show generated report artifact location hints

## Common flags

- `--platform <ios|android>`
- `--device <id|alias>`
- `--server-url <url>`
- `--app-id <identifier>`
- `--output <dir>`
- `--timeout <ms>`
- `--format <text|json>` (recommended: `json`)
- `--mock` (no real Appium target required)

## Selector syntax

`tap --target` and assertion targets support:
- plain text -> accessibility id (default)
- `accessibility=...`
- `id=...`
- `text=...` (maps to contains-style XPath)
- `xpath=...`
- `uiautomator=...` (Android)
- `predicate=...` (iOS)
- `classchain=...` (iOS)

Coordinate mode:
- `tap --x <num> --y <num>`
- add `--normalized` to treat values as 0..1 of screen width/height

## Artifacts and reports

`run` and `benchmark` write data under:

`artifacts/<run-id>/`

Key files:
- `summary.txt`
- `summary.json`
- `junit.xml`
- `timeline.log`
- `report.html`
- `screenshots/...`
- `sources/...`
- `env/runtime.json`
- `env/device.json`

## Runtime prerequisites (non-mock)

- Appium server reachable at `--server-url` (default `http://127.0.0.1:4723`)
- iOS simulator or Android emulator/device available
- Python dependencies installed (`Appium-Python-Client`, `selenium`)

Env overrides:
- `VISOR_ANDROID_APP_PACKAGE`
- `VISOR_ANDROID_APP_ACTIVITY`
- `VISOR_ANDROID_DEVICE`
- `VISOR_IOS_BUNDLE_ID`
- `VISOR_IOS_DEVICE`

## CI-friendly usage

Typical pipeline:
1. Agent implements a UI change.
2. `visor run ... --format json` executes and captures artifacts.
3. Optional `visor benchmark ...` enforces determinism threshold.
4. CI publishes `artifacts/<run-id>/report.html`, `summary.json`, and screenshots for review.

## Exit behavior

- `0`: success
- `1`: input/target/action setup failure
- `2`: `run` finished with failed steps/assertions
- `3`: `benchmark` did not pass threshold or had failures

Error taxonomy in responses:
- `INPUT_ERROR`
- `TARGET_ERROR`
- `ACTION_ERROR`
- `ASSERTION_ERROR`
- `SYSTEM_ERROR`

## Local tests

```bash
python3 -m unittest -v
```
