import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { executeCommand } from '../src/cli.js';

function tempOutputDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'visor-output-'));
}

function responseData<T>(value: unknown): T {
  return value as T;
}

describe('typescript cli', () => {
  it('validates a good scenario', async () => {
    const result = await executeCommand(['validate', 'scenarios/checkout-smoke.json']);
    expect(result.code).toBe(0);
    expect(result.response.status).toBe('ok');
    expect(result.response.data.valid).toBe(true);
  });

  it('accepts format flags after validate positionals', async () => {
    const result = await executeCommand([
      'validate',
      'scenarios/checkout-smoke.json',
      '--format',
      'json'
    ]);
    expect(result.code).toBe(0);
    expect(result.response.status).toBe('ok');
  });

  it('accepts action format flags after action options', async () => {
    const result = await executeCommand([
      'wait',
      '--platform',
      'android',
      '--mock',
      '--ms',
      '1',
      '--format',
      'json'
    ]);
    expect(result.code).toBe(0);
    expect(result.response.status).toBe('ok');
  });

  it('runs a scenario in mock mode', async () => {
    const outputDir = tempOutputDir();

    try {
      const result = await executeCommand([
        'run',
        'scenarios/checkout-smoke.json',
        '--output',
        outputDir,
        '--mock'
      ]);
      const data = responseData<{ run: { status: string; determinism_signature: string } }>(
        result.response.data
      );
      expect(result.code).toBe(0);
      expect(result.response.status).toBe('ok');
      expect(data.run.status).toBe('ok');
      expect(data.run.determinism_signature).toBeTruthy();
    } finally {
      fs.rmSync(outputDir, { recursive: true, force: true });
    }
  });

  it('accepts app id on run', async () => {
    const outputDir = tempOutputDir();

    try {
      const result = await executeCommand([
        'run',
        'scenarios/checkout-smoke.json',
        '--output',
        outputDir,
        '--mock',
        '--app-id',
        'com.example.custom'
      ]);
      expect(result.code).toBe(0);
      expect(result.response.status).toBe('ok');
    } finally {
      fs.rmSync(outputDir, { recursive: true, force: true });
    }
  });

  it('returns assertion error for failed assertions', async () => {
    const outputDir = tempOutputDir();

    try {
      const result = await executeCommand([
        'run',
        'scenarios/assertion-fail-smoke.json',
        '--output',
        outputDir,
        '--mock'
      ]);
      const data = responseData<{ run: { status: string } }>(result.response.data);
      expect(result.code).toBe(2);
      expect(result.response.status).toBe('fail');
      expect(result.response.error?.code).toBe('ASSERTION_ERROR');
      expect(data.run.status).toBe('fail');
    } finally {
      fs.rmSync(outputDir, { recursive: true, force: true });
    }
  });

  it('creates a real png artifact in mock mode', async () => {
    const outputDir = tempOutputDir();

    try {
      const result = await executeCommand([
        'run',
        'scenarios/checkout-smoke.json',
        '--output',
        outputDir,
        '--mock'
      ]);
      const data = responseData<{
        run: {
          artifacts: string[];
          steps: Array<{ details: { args: { width: number; height: number } } }>;
        };
      }>(result.response.data);
      expect(result.code).toBe(0);
      const run = data.run;
      const shots = run.artifacts;
      expect(shots.length).toBeGreaterThanOrEqual(1);
      const first = shots[0];
      expect(fs.existsSync(first)).toBe(true);
      expect(fs.readFileSync(first).subarray(0, 8)).toEqual(
        Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
      );
      expect(run.steps[0].details.args.width).toBe(1);
      expect(run.steps[0].details.args.height).toBe(1);
    } finally {
      fs.rmSync(outputDir, { recursive: true, force: true });
    }
  });

  it('meets benchmark determinism threshold in mock mode', async () => {
    const outputDir = tempOutputDir();

    try {
      const result = await executeCommand([
        'benchmark',
        'scenarios/checkout-smoke.json',
        '--platform',
        'android',
        '--mock',
        '--runs',
        '5',
        '--threshold',
        '95',
        '--output',
        outputDir,
        '--format',
        'json'
      ]);
      const data = responseData<{ pass: boolean; determinismScore: number }>(result.response.data);
      expect(result.code).toBe(0);
      expect(data.pass).toBe(true);
      expect(data.determinismScore).toBeGreaterThanOrEqual(95);
    } finally {
      fs.rmSync(outputDir, { recursive: true, force: true });
    }
  });

  it('accepts report positional paths', async () => {
    const result = await executeCommand(['report', 'artifacts-test', '--format', 'json']);
    const data = responseData<{ path: string }>(result.response.data);
    expect(result.code).toBe(0);
    expect(result.response.status).toBe('ok');
    expect(data.path).toBe('artifacts-test');
  });

  it('returns status output for unmanaged appium', async () => {
    const result = await executeCommand(['status', '--server-url', 'http://127.0.0.1:4723']);
    const data = responseData<{ managed: boolean }>(result.response.data);
    expect(result.code).toBe(0);
    expect(result.response.status).toBe('ok');
    expect(data.managed).toBe(false);
  });
});
