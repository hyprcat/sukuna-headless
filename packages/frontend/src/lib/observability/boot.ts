import { initPostHog } from './posthog';
import { initSentry } from './sentry';

function telemetryEnabled(): boolean {
  const flag = import.meta.env.PUBLIC_MS_TELEMETRY as string | undefined;
  if (flag === 'off') return false;
  if (flag) return true;
  const env = (import.meta.env.PUBLIC_ENVIRONMENT as string) || 'dev';
  return env !== 'dev';
}

export function bootObservability(): void {
  if (!telemetryEnabled()) return;
  try {
    initSentry({
      dsn: import.meta.env.PUBLIC_MS_SENTRY_DSN as string | undefined,
      environment: (import.meta.env.PUBLIC_ENVIRONMENT as string) || 'dev',
      release: import.meta.env.PUBLIC_RELEASE as string | undefined,
    });
  } catch {
    /* non-blocking — app must boot even if Sentry fails */
  }
  try {
    initPostHog({
      apiKey: import.meta.env.PUBLIC_MS_POSTHOG_KEY as string | undefined,
      host: (import.meta.env.PUBLIC_MS_POSTHOG_HOST as string) || 'https://us.i.posthog.com',
    });
  } catch {
    /* non-blocking — app must boot even if PostHog fails */
  }
}
