export interface UploadTarget {
  url: string;
  key: string;
}

export interface PhotoMeta {
  takenAt: number;
  fileName: string;
}

export interface UploadResult {
  ok: boolean;
  status: number;
  error?: string;
}

const URL_KEY = 'molka.upload.url';
const TOKEN_KEY = 'molka.upload.key';
const TIMEOUT_MS = 45_000;

/** The receive route of the relay backend (see server.js). */
export const PHOTO_PATH = '/api/camera/photos';

/**
 * Backend this build ships pointed at: the Cloudflare quick tunnel running
 * server.js. Photos start flowing with no setup step on the phone; `?upload=`
 * or the in-app Change button overrides it (e.g. after the tunnel restarts).
 */
export const DEFAULT_ENDPOINT = 'https://ten-then-museums-aud.trycloudflare.com/api/camera/photos';

export function defaultTarget(): UploadTarget {
  return normalizeEndpoint(DEFAULT_ENDPOINT) ?? { url: DEFAULT_ENDPOINT, key: '' };
}

function read(key: string): string {
  try {
    return localStorage.getItem(key) ?? '';
  } catch {
    return '';
  }
}

function write(key: string, value: string) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* private mode — config stays for this session only */
  }
}

/**
 * Turns whatever was pasted into the exact POST URL.
 *
 * A bare tunnel origin ("https://foo-bar.trycloudflare.com") is normalised to
 * "https://foo-bar.trycloudflare.com/api/camera/photos", so the tunnel address
 * alone is enough — no path to type. A full path is kept as given.
 * `?key=<token>` is lifted out of the URL and returned separately.
 */
export function normalizeEndpoint(raw: string): UploadTarget | null {
  const value = (raw ?? '').trim();
  if (!value) return null;

  let parsed: URL;
  try {
    // Accept "host.trycloudflare.com" too — https is the only sane default.
    parsed = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? value : `https://${value}`);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;

  const key = parsed.searchParams.get('key') ?? '';
  parsed.searchParams.delete('key');
  parsed.hash = '';
  if (!parsed.pathname || parsed.pathname === '/') parsed.pathname = PHOTO_PATH;

  return { url: parsed.toString(), key };
}

/**
 * Endpoint resolution, highest priority first:
 *   1. ?upload=<url>[&key=<token>] in the address bar (saved for later visits)
 *   2. the last saved value in localStorage
 *   3. DEFAULT_ENDPOINT, so an unconfigured phone still sends
 */
export function loadTarget(): UploadTarget | null {
  try {
    const params = new URLSearchParams(location.search);
    const fromQuery = params.get('upload');
    const normalized = fromQuery ? normalizeEndpoint(fromQuery) : null;
    if (normalized) {
      const target: UploadTarget = { url: normalized.url, key: params.get('key') ?? normalized.key };
      saveTarget(target);
      params.delete('upload');
      params.delete('key');
      const qs = params.toString();
      history.replaceState(null, '', location.pathname + (qs ? `?${qs}` : '') + location.hash);
      return target;
    }
  } catch {
    /* no readable query string */
  }

  const url = read(URL_KEY);
  if (!url) return defaultTarget();
  return { url, key: read(TOKEN_KEY) };
}

export function saveTarget(target: UploadTarget): UploadTarget {
  write(URL_KEY, target.url);
  write(TOKEN_KEY, target.key);
  return target;
}

export function clearTarget() {
  write(URL_KEY, '');
  write(TOKEN_KEY, '');
}

/**
 * POST the photo as multipart/form-data.
 *
 * Fields sent to your backend:
 *   photo       image/jpeg file (the field to read on the receiving side)
 *   takenAt     ISO 8601 timestamp of the capture
 *   takenAtMs   same instant in epoch milliseconds (for cheap sorting)
 *   fileName    photo-YYYYMMDD-HHMMSS.jpg
 *   timezone    the phone's IANA timezone, e.g. "Africa/Cairo"
 *   device      the phone's user agent
 *   key         only when a token was supplied with ?key=...
 *
 * No custom headers are set on purpose: a plain multipart POST is a CORS
 * "simple request", so the browser sends no preflight OPTIONS. Your backend
 * only has to return Access-Control-Allow-Origin.
 */
export async function sendPhoto(
  target: UploadTarget,
  photo: Blob,
  meta: PhotoMeta
): Promise<UploadResult> {
  const form = new FormData();
  form.append('photo', photo, meta.fileName);
  form.append('takenAt', new Date(meta.takenAt).toISOString());
  form.append('takenAtMs', String(meta.takenAt));
  form.append('fileName', meta.fileName);
  form.append('timezone', Intl.DateTimeFormat().resolvedOptions().timeZone ?? '');
  form.append('device', navigator.userAgent);
  if (target.key) form.append('key', target.key);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(target.url, {
      method: 'POST',
      body: form,
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      signal: controller.signal,
    });

    if (!res.ok) {
      return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    }
    return { ok: true, status: res.status };
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      return { ok: false, status: 0, error: 'Timed out' };
    }
    return { ok: false, status: 0, error: e?.message ?? 'Network error' };
  } finally {
    clearTimeout(timer);
  }
}
