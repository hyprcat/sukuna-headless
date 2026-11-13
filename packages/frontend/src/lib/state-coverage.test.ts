import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

function read(path: string): string {
  return readFileSync(path, 'utf8');
}

describe('state feedback helpers', () => {
  it('keeps toast notifications free of retained timer state', () => {
    const script = read('public/scripts/lib/toast.js');

    expect(script).not.toContain('var timers');
    expect(script).not.toContain('timers.push');
    expect(script).toContain("container.setAttribute('aria-live', 'polite')");
  });

  it('creates each confirmation dialog per request and restores focus', () => {
    const script = read('public/scripts/lib/confirm.js');

    expect(script).not.toContain('var dialog = null');
    expect(script).not.toContain('var resolve = null');
    expect(script).toContain('document.createElement');
    expect(script).toContain('previousFocus.focus');
    expect(script).toContain("dialog.setAttribute('aria-describedby', 'confirm-message')");
  });
});
