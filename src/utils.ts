import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export interface ParsedServerUrl {
  server_url: string;
  protocol: string;
  host: string;
  port: number;
  pathname: string;
}

export function utcNowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function makeId(prefix: string): string {
  return `${prefix}_${randomUUID().replace(/-/g, '').slice(0, 12)}`;
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sortValue(item));
  }

  if (value && typeof value === 'object') {
    const input = value as Record<string, unknown>;
    return Object.keys(input)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        acc[key] = sortValue(input[key]);
        return acc;
      }, {});
  }

  return value;
}

export function canonicalJson(data: unknown): string {
  return JSON.stringify(sortValue(data));
}

export function signatureFor(data: unknown): string {
  return createHash('sha256').update(canonicalJson(data), 'utf8').digest('hex');
}

export function ensureDir(targetPath: string): string {
  fs.mkdirSync(targetPath, { recursive: true });
  return targetPath;
}

export async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export function parseServerUrl(serverUrl: string): ParsedServerUrl {
  const parsed = new URL(serverUrl);
  return {
    server_url: serverUrl,
    protocol: parsed.protocol.replace(':', '') || 'http',
    host: parsed.hostname || '127.0.0.1',
    port: Number(parsed.port || 4723),
    pathname: parsed.pathname && parsed.pathname !== '' ? parsed.pathname : '/'
  };
}

export function readJsonFile(filePath: string): unknown {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}

export function resolveExecutable(baseName: string): string | null {
  const pathValue = process.env.PATH ?? '';
  const pathEntries = pathValue.split(path.delimiter).filter(Boolean);
  const candidates = process.platform === 'win32'
    ? [baseName, `${baseName}.cmd`, `${baseName}.exe`, `${baseName}.bat`]
    : [baseName];

  for (const entry of pathEntries) {
    for (const candidate of candidates) {
      const fullPath = path.join(entry, candidate);
      try {
        fs.accessSync(fullPath, fs.constants.X_OK);
        return fullPath;
      } catch {
        continue;
      }
    }
  }

  return null;
}

export function splitCommandLine(command: string): string[] {
  const parts: string[] = [];
  let current = '';
  let quote: "'" | '"' | null = null;
  let escaping = false;

  for (const char of command) {
    if (escaping) {
      current += char;
      escaping = false;
      continue;
    }

    if (char === '\\') {
      escaping = true;
      continue;
    }

    if (quote) {
      if (char === quote) {
        quote = null;
      } else {
        current += char;
      }
      continue;
    }

    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }

    if (/\s/.test(char)) {
      if (current !== '') {
        parts.push(current);
        current = '';
      }
      continue;
    }

    current += char;
  }

  if (current !== '') {
    parts.push(current);
  }

  return parts;
}
