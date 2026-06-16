/* Thin fetch wrapper so a 401 anywhere in the app surfaces the login screen instead of a silent error.
 * The AuthGate registers a handler; every data fetch (feed/scan/detail) goes through `apiFetch`, which
 * fires that handler on a 401 and still returns the Response so existing per-call error handling is
 * unchanged. `getMe` deliberately uses raw fetch — an anonymous 401 there is EXPECTED, not a session
 * drop, so it must not trigger the global redirect. */

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const r = await fetch(input, init);
  if (r.status === 401 && onUnauthorized) onUnauthorized();
  return r;
}
