/**
 * Combine a caller-supplied AbortSignal with a timeout into one signal.
 *
 * Returns the merged signal plus a `clear()` to cancel the timer once the
 * request settles (so a finished request never fires a late abort).
 */
export function withTimeout(
  signal: AbortSignal | undefined,
  timeoutMs: number,
): { signal: AbortSignal | undefined; clear: () => void } {
  if (!timeoutMs || timeoutMs <= 0) {
    return { signal, clear: () => {} };
  }

  const controller = new AbortController();
  const onAbort = () => controller.abort(signal?.reason);
  if (signal) {
    if (signal.aborted) {
      controller.abort(signal.reason);
    } else {
      signal.addEventListener('abort', onAbort, { once: true });
    }
  }
  const timer = setTimeout(() => {
    controller.abort(new DOMException('Request timed out', 'TimeoutError'));
  }, timeoutMs);

  return {
    signal: controller.signal,
    clear: () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    },
  };
}
