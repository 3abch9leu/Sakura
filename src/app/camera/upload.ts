/* Upload contract of the camera page (from the `camera` branch), pointed at the INBETWEEN API by default. */

export interface UploadTarget {
  url: string;
  key: string;
}

export interface PhotoMeta {
  takenAt: number;
  fileName: string;
  cell?: number | null;
}

export interface UploadResult {
  ok: boolean;
  status: number;
  error?: string;
}

const URL_KEY = 'inbetween.camera.url';
const TOKEN_KEY = 'inbetween.camera.key';
const TIMEOUT_MS = 45_000;

/** Receive route on the INBETWEEN API (api.py). */
export const PHOTO_PATH = '/api/camera/photos';

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
    /* private mode: the setting lasts for this session only */
  }
}

/** The API this site already talks to; photos go there unless the user points the page elsewhere. */
export function defaultTarget(apiBase: string): UploadTarget {
  return { url: apiBase.replace(/\/$/, '') + PHOTO_PATH, key: '' };
}

/**
 * Turns whatever was pasted into the exact POST URL. A bare origin (e.g. a tunnel address) gets
 * /api/camera/photos appended; `?key=<token>` is lifted out and returned separately.
 */
export function normalizeEndpoint(raw: string): UploadTarget | null {
  const value = (raw ?? '').trim();
  if (!value) return null;
  let parsed: URL;
  try {
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

/** ?upload=<url>[&key=] in the address bar (saved), then the saved value, then the site's own API. */
export function loadTarget(apiBase: string): UploadTarget {
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
  return url ? { url, key: read(TOKEN_KEY) } : defaultTarget(apiBase);
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
 * POST the photo as multipart/form-data (a CORS "simple request": no preflight).
 * Fields: photo, takenAt, takenAtMs, fileName, timezone, device, cell (planting cell, optional), key (optional).
 */
export async function sendPhoto(target: UploadTarget, photo: Blob, meta: PhotoMeta): Promise<UploadResult> {
  const form = new FormData();
  form.append('photo', photo, meta.fileName);
  form.append('takenAt', new Date(meta.takenAt).toISOString());
  form.append('takenAtMs', String(meta.takenAt));
  form.append('fileName', meta.fileName);
  form.append('timezone', Intl.DateTimeFormat().resolvedOptions().timeZone ?? '');
  form.append('device', navigator.userAgent);
  if (meta.cell != null) form.append('cell', String(meta.cell));
  if (target.key) form.append('key', target.key);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(target.url, { method: 'POST', body: form, mode: 'cors', credentials: 'omit', cache: 'no-store', signal: controller.signal });
    return res.ok ? { ok: true, status: res.status } : { ok: false, status: res.status, error: `HTTP ${res.status}` };
  } catch (e: unknown) {
    const err = e as { name?: string; message?: string };
    return { ok: false, status: 0, error: err?.name === 'AbortError' ? 'Timed out' : err?.message ?? 'Network error' };
  } finally {
    clearTimeout(timer);
  }
}
