import posthog from 'posthog-js';

interface PostHogEnv {
  apiKey?: string;
  host: string;
}

export function initPostHog({ apiKey, host }: PostHogEnv): void {
  if (!apiKey) return;
  posthog.init(apiKey, {
    api_host: host,
    capture_pageview: true,
    capture_pageleave: 'if_capture_pageview',
    persistence: 'localStorage+cookie',
    autocapture: false,
  });
}

/**
 * Identify the signed-in operator. Per FRONTEND_CODING_STANDARDS.md, identify
 * runs only after auth completes — never on a logged-out route.
 */
export function identifyUser(distinctId: string, properties?: Record<string, unknown>): void {
  posthog.identify(distinctId, properties);
}

export function resetPostHog(): void {
  posthog.reset();
}
