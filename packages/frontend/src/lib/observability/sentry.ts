import * as Sentry from '@sentry/browser';

interface SentryEnv {
  dsn?: string;
  environment: string;
  release?: string;
}

export function initSentry({ dsn, environment, release }: SentryEnv): void {
  if (!dsn) return;
  Sentry.init({
    dsn,
    environment,
    release,
    tracesSampleRate: environment === 'prod' ? 0.1 : 1.0,
    sendDefaultPii: false,
    integrations: [Sentry.browserTracingIntegration()],
  });
}

export function setSentryUser(id: string, email?: string): void {
  Sentry.setUser({ id, email });
}

export function clearSentryUser(): void {
  Sentry.setUser(null);
}
