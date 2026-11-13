export function safeReturnTo(raw: string): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || /[\r\n]/.test(raw)) {
    return '/dashboard';
  }

  try {
    const url = new URL(raw, 'http://midsphere.local');
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return '/dashboard';
  }
}
