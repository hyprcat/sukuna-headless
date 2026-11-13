import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

function read(path: string): string {
  return readFileSync(path, 'utf8');
}

describe('empty states', () => {
  it('keeps insight empty states actionable and marked', () => {
    const page = read('src/pages/insights.astro');

    expect(page).toContain('heading="Nothing to report yet"');
    expect(page).toContain('<Button variant="accent" href="/runs">');
    expect(page).toContain('View runs');
    expect(page).toContain('heading="No dismissed insights"');
    expect(page).toContain('<span class="hl">action insights</span>');
    expect(page).toContain('<Button variant="accent" href="/insights">');
    expect(page).toContain('View active insights');
  });

  it('keeps the members empty state tied to the invite action', () => {
    const page = read('src/pages/workspace/members.astro');
    const script = read('public/scripts/members.js');

    expect(page).toContain('heading="No members yet"');
    expect(page).toContain('<span class="hl">collaborate</span>');
    expect(page).toContain('id="btn-show-invite-empty"');
    expect(script).toContain("document.getElementById('btn-show-invite-empty')");
  });
});
