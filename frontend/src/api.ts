export const apiBase = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV
    ? ''
    : 'https://everyfan-api.graybay-511bafbd.uaenorth.azurecontainerapps.io')
).replace(/\/$/, '');
export const apiUrl = (path: string) => `${apiBase}${path}`;
export function socketUrl(path: string): string {
  const url = new URL(apiUrl(path), window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.href;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...options,
    signal: options.signal ?? AbortSignal.timeout(20000),
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const data: { detail?: string } = await response.json();
      detail = data.detail || detail;
    } catch {
      /* Non-JSON gateway error. */
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}
