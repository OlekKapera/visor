# Visor

Visor is a TypeScript CLI for verified interaction with running mobile apps.

Instead of inferring UI behavior from code alone, Visor captures evidence from the live app: interactions, screenshots, UI source, assertions, and run artifacts.

## What Visor does

- interacts with iOS and Android apps through Appium
- captures screenshots and UI source from live app state
- executes repeatable scenarios with ordered steps
- evaluates visibility assertions after execution
- writes artifacts and reports for review and automation
- measures determinism across repeated runs

## Why teams use it

- reduce guesswork in agent-driven UI work
- verify real app behavior instead of code intent alone
- keep reproducible evidence for debugging and review
- add a repeatable verification layer around mobile UI changes

## Scope

Visor is focused on mobile app verification.

Supported today:

- Android
- iOS
- real Appium-backed runs
- mock runs for predictable dry-run behavior

## Install

Visor ships as the npm package `visor-ai` and requires Node `20` or later.

For a published install:

```bash
npm install -g visor-ai
visor --help
```

For a source checkout:

```bash
npm install
npm run build
node dist/main.js --help
```

## Release automation

GitHub Actions publishes tagged releases of `visor-ai` to the npm registry.

Maintainer requirements:

- repository secret `NPM_TOKEN`
- release tags in the form `v<package.json version>`

The release workflow verifies the package with `npm ci`, `npm run build`, `npm test`, and `npm pack --dry-run` before publishing.

## Documentation

Comprehensive product documentation lives in [the docs site](https://na-ca6c7a2b.mintlify.app).
