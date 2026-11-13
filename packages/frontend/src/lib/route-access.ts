const PUBLIC_PATHS: readonly string[] = [
  '/',
  '/login',
  '/signup',
  '/forgot-password',
  '/verify-email',
  '/reset-password',
];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(path + '/'));
}
