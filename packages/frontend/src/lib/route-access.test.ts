import { describe, expect, it } from 'vitest';

import { isPublicPath } from './route-access';

describe('isPublicPath', () => {
  it('allows auth and token routes without a session', () => {
    expect(isPublicPath('/login')).toBe(true);
    expect(isPublicPath('/signup')).toBe(true);
    expect(isPublicPath('/forgot-password')).toBe(true);
    expect(isPublicPath('/verify-email/uid/token')).toBe(true);
    expect(isPublicPath('/reset-password/uid/token')).toBe(true);
  });

  it('treats the root as public', () => {
    expect(isPublicPath('/')).toBe(true);
  });

  it('keeps dashboard routes behind auth', () => {
    expect(isPublicPath('/dashboard')).toBe(false);
    expect(isPublicPath('/agents/new')).toBe(false);
    expect(isPublicPath('/runs')).toBe(false);
    expect(isPublicPath('/settings')).toBe(false);
  });
});
