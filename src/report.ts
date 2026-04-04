import fs from 'node:fs';
import path from 'node:path';

import type { RunResult } from './types.js';
import { canonicalJson, ensureDir } from './utils.js';

function escapeXml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

function junitXml(run: RunResult): string {
  const tests = run.steps.length;
  const failures = run.steps.filter((step) => step.status !== 'ok').length;
  const lines: string[] = [
    `<testsuite name="${escapeXml(run.run_id)}" tests="${tests}" failures="${failures}">`
  ];

  for (const step of run.steps) {
    lines.push(
      `  <testcase name="${escapeXml(step.id)}" classname="visor.${escapeXml(run.platform)}" time="${(
        step.duration_ms / 1000
      ).toFixed(3)}">`
    );
    if (step.status !== 'ok') {
      const message = step.error?.message ?? 'step failed';
      lines.push(`    <failure message="${escapeXml(message)}" />`);
    }
    lines.push('  </testcase>');
  }

  lines.push('</testsuite>');
  return `${lines.join('\n')}\n`;
}

function materializeArtifacts(root: string, artifactPaths: string[]): string[] {
  const screenshotsDir = ensureDir(path.join(root, 'screenshots'));
  const sourcesDir = ensureDir(path.join(root, 'sources'));
  const persisted: string[] = [];

  artifactPaths.forEach((artifactPath, index) => {
    if (!fs.existsSync(artifactPath)) {
      return;
    }

    const sourcePath = path.resolve(artifactPath);
    const destinationRoot = sourcePath.toLowerCase().endsWith('.png') ? screenshotsDir : sourcesDir;
    const destinationPath = path.join(destinationRoot, `${String(index + 1).padStart(3, '0')}-${path.basename(sourcePath)}`);

    if (sourcePath !== path.resolve(destinationPath)) {
      fs.copyFileSync(sourcePath, destinationPath);
    }

    persisted.push(destinationPath);
  });

  return persisted;
}

export function writeReports(result: RunResult, reportDir: string): Record<string, string> {
  const root = ensureDir(path.join(reportDir, result.run_id));
  const env = ensureDir(path.join(root, 'env'));
  const payload = structuredClone(result);
  const persistedArtifacts = materializeArtifacts(root, result.artifacts);

  payload.artifacts = persistedArtifacts;
  result.artifacts = persistedArtifacts;

  const summaryTxt = path.join(root, 'summary.txt');
  const summaryJson = path.join(root, 'summary.json');
  const junitPath = path.join(root, 'junit.xml');
  const timelinePath = path.join(root, 'timeline.log');
  const htmlPath = path.join(root, 'report.html');

  fs.writeFileSync(
    summaryTxt,
    [
      `run_id: ${result.run_id}`,
      `platform: ${result.platform}`,
      `device: ${result.device}`,
      `status: ${result.status}`,
      `determinism_signature: ${result.determinism_signature}`,
      `artifact_count: ${result.artifacts.length}`,
      ''
    ].join('\n'),
    'utf8'
  );

  fs.writeFileSync(summaryJson, `${canonicalJson(payload)}\n`, 'utf8');
  fs.writeFileSync(junitPath, junitXml(payload), 'utf8');
  fs.writeFileSync(
    timelinePath,
    `${payload.steps
      .map((step, index) => `${String(index + 1).padStart(3, '0')} ${step.id} ${step.command} ${step.status} ${step.duration_ms}ms`)
      .join('\n')}\n`,
    'utf8'
  );
  fs.writeFileSync(
    path.join(env, 'runtime.json'),
    `${JSON.stringify(
      {
        seed: result.seed,
        started_at: result.started_at,
        ended_at: result.ended_at
      },
      null,
      2
    )}\n`,
    'utf8'
  );
  fs.writeFileSync(
    path.join(env, 'device.json'),
    `${JSON.stringify(
      {
        platform: result.platform,
        device: result.device
      },
      null,
      2
    )}\n`,
    'utf8'
  );
  fs.writeFileSync(
    htmlPath,
    `<html><body><h1>${escapeXml(result.run_id)}</h1><p>Status: ${escapeXml(result.status)}</p><p>Artifacts: ${result.artifacts.length}</p></body></html>\n`,
    'utf8'
  );

  return {
    summary: summaryTxt,
    json: summaryJson,
    junit: junitPath,
    timeline: timelinePath,
    html: htmlPath
  };
}
