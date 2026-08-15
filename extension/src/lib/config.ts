/**
 * Where this build expects to find its API.
 *
 * Baked in at build time from `STOCKWATCH_API_URL` rather than hard-coded,
 * because the address differs per deployment and a store build must never ship
 * pointing at a developer's laptop — `scripts/build.mjs` refuses a release build
 * that is not https, and writes the matching `host_permissions` into the
 * manifest so the two can never disagree.
 *
 * A self-hoster can still override it at runtime; `setBaseUrl` asks for the host
 * permission that entails.
 */

declare const __API_BASE_URL__: string | undefined;

/** Reached only by an unconfigured local build. Release builds are checked. */
const LOCAL_FALLBACK = 'http://localhost:8000/api';

export const DEFAULT_API_BASE_URL =
  typeof __API_BASE_URL__ === 'string' && __API_BASE_URL__ ? __API_BASE_URL__ : LOCAL_FALLBACK;

/**
 * The `chrome.permissions` match pattern that covers an API base URL, or null
 * if the address is not one the extension could ever fetch.
 *
 * Match patterns are host-scoped and carry no port, so `:8000` is dropped:
 * granting `http://localhost/*` covers every port on that host.
 */
export function apiOriginPattern(baseUrl: string): string | null {
  let url: URL;
  try {
    url = new URL(baseUrl);
  } catch {
    return null;
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  return `${url.protocol}//${url.hostname}/*`;
}
