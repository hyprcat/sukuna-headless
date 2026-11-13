import { afterEach, describe, expect, it, vi } from 'vitest';

import { formatDuration, formatSize, initial, timeAgo } from './format';

describe('formatDuration', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('formats seconds and minute spans', () => {
    expect(formatDuration('2026-05-07T00:00:00.000Z', '2026-05-07T00:00:09.500Z')).toBe('9.5s');
    expect(formatDuration('2026-05-07T00:00:00.000Z', '2026-05-07T00:02:05.000Z')).toBe('2m 5s');
  });

  it('uses the current time for running spans', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-05-07T00:00:42.000Z'));

    expect(formatDuration('2026-05-07T00:00:40.000Z', null)).toBe('2.0s');
  });
});

describe('timeAgo', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('uses compact relative labels', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-05-07T12:00:00.000Z'));

    expect(timeAgo('2026-05-07T11:59:45.000Z')).toBe('just now');
    expect(timeAgo('2026-05-07T11:15:00.000Z')).toBe('45 min ago');
    expect(timeAgo('2026-05-07T09:00:00.000Z')).toBe('3h ago');
    expect(timeAgo('2026-05-05T12:00:00.000Z')).toBe('2d ago');
  });
});

describe('initial', () => {
  it('extracts and uppercases the first character', () => {
    expect(initial('alice')).toBe('A');
    expect(initial('Bob')).toBe('B');
  });

  it('returns ? for null/undefined/empty', () => {
    expect(initial(null)).toBe('?');
    expect(initial(undefined)).toBe('?');
    expect(initial('')).toBe('?');
  });
});

describe('formatSize', () => {
  it('formats byte counts with stable units', () => {
    expect(formatSize(null)).toBe('—');
    expect(formatSize(512)).toBe('512 B');
    expect(formatSize(2048)).toBe('2.0 KB');
    expect(formatSize(3 * 1048576)).toBe('3.0 MB');
  });
});
