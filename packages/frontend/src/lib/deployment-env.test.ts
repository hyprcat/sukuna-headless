import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const repoRoot = resolve(import.meta.dirname, '../../../..');

function readRepoFile(path: string): string {
  return readFileSync(resolve(repoRoot, path), 'utf8');
}

function extractImportMetaEnvNames(source: string): Set<string> {
  return new Set([...source.matchAll(/import\.meta\.env\.([A-Z0-9_]+)/g)].map((match) => match[1]));
}

function expectEnvDeclared(envName: string, source: string): void {
  expect(source).toContain(`readonly ${envName}?: string`);
}

describe('deployment environment contract', () => {
  it('keeps frontend public telemetry vars consistent across code, Docker, and App Platform', () => {
    const boot = readRepoFile('packages/frontend/src/lib/observability/boot.ts');
    const envTypes = readRepoFile('packages/frontend/src/env.d.ts');
    const dockerfile = readRepoFile('packages/frontend/Dockerfile');
    const appSpec = readRepoFile('deploy/digitalocean/app.yaml');

    const publicVars = [...extractImportMetaEnvNames(boot)].filter((name) =>
      name.startsWith('PUBLIC_'),
    );

    for (const envName of publicVars) {
      expectEnvDeclared(envName, envTypes);
      expect(dockerfile).toContain(`ARG ${envName}`);
      expect(appSpec).toContain(`key: ${envName}`);
    }
  });
});
