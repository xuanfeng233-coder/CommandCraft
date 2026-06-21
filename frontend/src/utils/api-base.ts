/**
 * Resolve the backend API base URL.
 * Web mode uses relative paths (same origin via Nginx proxy).
 */
export function getApiBase(): string {
  return ''
}

/**
 * Always false — standalone mode has been removed.
 * Kept as a stub for compatibility.
 */
export function isStandalone(): boolean {
  return false
}
