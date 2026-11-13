/// <reference types="astro/client" />

interface ImportMetaEnv {
  readonly PUBLIC_MS_TELEMETRY?: string;
  readonly PUBLIC_MS_SENTRY_DSN?: string;
  readonly PUBLIC_MS_POSTHOG_KEY?: string;
  readonly PUBLIC_MS_POSTHOG_HOST?: string;
  readonly PUBLIC_ENVIRONMENT?: string;
  readonly PUBLIC_RELEASE?: string;
}

interface MsConfirmOptions {
  title?: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'primary';
}

interface MsToastApi {
  success(message: string, duration?: number): void;
  error(message: string, duration?: number): void;
  info(message: string, duration?: number): void;
}

interface Window {
  msConfirm?: (options: MsConfirmOptions) => Promise<boolean>;
  msToast?: MsToastApi;
}

declare namespace App {
  interface Locals {
    user: { id: number; email: string; full_name: string; email_verified: boolean } | null;
    workspaceSlug: string | null;
    workspaces: { slug: string; name: string; role: string }[];
    layout: 'classic' | 'new';
  }
}
