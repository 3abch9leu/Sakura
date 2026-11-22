/**
 * Tiny local relay for Punica Live.
 *
 * Punica requires the API key to stay on a server: it has no CORS headers on
 * POST /api/v1/live/sessions, and a key in the browser bundle is a leaked key.
 * This process creates the single-use session and hands the browser only the
 * short-lived WebSocket URL + ticket.
 *
 *   server/.env   ->  PUNICA_API_KEY=pk_live_...
 *   npm run voice:server
 *
 * It is a development relay, not a production backend: keep the same shape
 * (POST /api/live/session + GET /health) when you host the site for real.
 */
import { createServer } from 'node:http';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

function loadEnv() {
  const file = join(here, '.env');
  if (!existsSync(file)) return;
  for (const raw of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq < 1) continue;
    const name = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!(name in process.env)) process.env[name] = value;
  }
}

loadEnv();

// A dedicated name: generic PORT is often already taken by other tooling.
const PORT = Number(process.env.VOICE_PORT || 8787);
const ALLOWED = (
  process.env.ALLOWED_ORIGINS ||
  'http://localhost:4200,http://127.0.0.1:4200,http://[::1]:4200'
)
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);

const apiKey = () => (process.env.PUNICA_API_KEY || '').trim();
const geminiApiKey = () => (process.env.GEMINI_API_KEY || '').trim();

/** Two rapid clicks must not open two billed calls. */
let lastSessionAt = 0;
const MIN_GAP_MS = 1_200;

const corsHeaders = (origin) =>
  origin && ALLOWED.includes(origin)
    ? {
        'Access-Control-Allow-Origin': origin,
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Max-Age': '600',
        Vary: 'Origin',
      }
    : {};

function reply(res, status, body, origin) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(payload),
    ...corsHeaders(origin),
  });
  res.end(payload);
}

async function readJson(req) {
  let body = '';
  for await (const chunk of req) {
    body += chunk;
    if (body.length > 8_192) throw new Error('body_too_large');
  }
  if (!body) return {};
  return JSON.parse(body);
}

const server = createServer(async (req, res) => {
  const origin = req.headers.origin;
  const url = new URL(req.url || '/', `http://127.0.0.1:${PORT}`);

  if (req.method === 'OPTIONS') {
    res.writeHead(204, corsHeaders(origin));
    res.end();
    return;
  }

  if (url.pathname === '/health' && req.method === 'GET') {
    reply(res, 200, {
      configured: Boolean(apiKey()),
      punicaConfigured: Boolean(apiKey()),
      geminiConfigured: Boolean(geminiApiKey()),
      origins: ALLOWED,
    }, origin);
    return;
  }

  if (url.pathname === '/api/gemini/live-token' && req.method === 'POST') {
    if (!origin || !ALLOWED.includes(origin)) {
      reply(res, 403, { error: 'origin_not_allowed', message: 'This app origin is not allowed.' }, origin);
      return;
    }
    if (!geminiApiKey()) {
      reply(res, 503, {
        error: 'missing_key',
        message: 'GEMINI_API_KEY is not set. Add it to server/.env and restart npm run voice:server.',
      }, origin);
      return;
    }

    try {
      const now = Date.now();
      const upstream = await fetch('https://generativelanguage.googleapis.com/v1beta/auth_tokens', {
        method: 'POST',
        headers: {
          'x-goog-api-key': geminiApiKey(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          uses: 1,
          expireTime: new Date(now + 30 * 60_000).toISOString(),
          newSessionExpireTime: new Date(now + 60_000).toISOString(),
        }),
        signal: AbortSignal.timeout(15_000),
      });
      const data = await upstream.json().catch(() => null);
      if (!upstream.ok || !data?.name) {
        console.error('[gemini-live] token refused', upstream.status, data?.error?.status ?? '');
        reply(res, upstream.ok ? 502 : upstream.status, {
          error: 'token_failed',
          message: data?.error?.message ?? 'Gemini could not create a live voice session.',
        }, origin);
        return;
      }
      reply(res, 200, { token: data.name }, origin);
    } catch (error) {
      console.error('[gemini-live] token request failed:', error?.message ?? error);
      reply(res, 502, { error: 'upstream_unreachable', message: 'Could not reach Gemini. Check the network and try again.' }, origin);
    }
    return;
  }

  if (url.pathname === '/api/live/session' && req.method === 'POST') {
    if (!origin || !ALLOWED.includes(origin)) {
      reply(
        res,
        403,
        {
          error: 'origin_not_allowed',
          message: `Origin ${origin || '(none)'} is not allowed. Start the app on http://localhost:4200.`,
        },
        origin,
      );
      return;
    }

    if (!apiKey()) {
      reply(
        res,
        503,
        {
          error: 'missing_key',
          message:
            'PUNICA_API_KEY is not set. Add it to server/.env and restart npm run voice:server.',
        },
        origin,
      );
      return;
    }

    const now = Date.now();
    if (now - lastSessionAt < MIN_GAP_MS) {
      reply(
        res,
        429,
        {
          error: 'too_fast',
          message: 'A voice call was just created. Wait a moment before the next one.',
        },
        origin,
      );
      return;
    }

    let body;
    try {
      body = await readJson(req);
    } catch {
      reply(res, 400, { error: 'invalid_json', message: 'Send a JSON body.' }, origin);
      return;
    }

    if (body?.model && body.model !== 'punica-live') {
      reply(
        res,
        400,
        { error: 'invalid_model', message: 'This relay only opens punica-live calls.' },
        origin,
      );
      return;
    }

    lastSessionAt = now;

    try {
      const upstream = await fetch('https://punica.tn/api/v1/live/sessions', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${apiKey()}`,
          'Content-Type': 'application/json',
        },
        // `origin` binds the single-use ticket to this exact app origin.
        body: JSON.stringify({ model: 'punica-live', origin }),
        signal: AbortSignal.timeout(15_000),
      });

      const data = await upstream.json().catch(() => null);

      if (!upstream.ok) {
        console.error('[live] refused', upstream.status, data?.code ?? '');
        reply(
          res,
          upstream.status,
          {
            error: data?.code ?? 'session_failed',
            message: data?.message ?? `Punica answered ${upstream.status}.`,
          },
          origin,
        );
        return;
      }

      if (!data?.url || !data?.client_secret) {
        console.error('[live] response had no url/client_secret');
        reply(
          res,
          502,
          { error: 'bad_session', message: 'Punica returned no connection details.' },
          origin,
        );
        return;
      }

      console.log('[live] session created for', origin);
      reply(
        res,
        200,
        {
          url: data.url,
          client_secret: data.client_secret,
          expires_at: data.expires_at ?? null,
        },
        origin,
      );
    } catch (error) {
      console.error('[live] upstream failed:', error?.message ?? error);
      reply(
        res,
        502,
        {
          error: 'upstream_unreachable',
          message: 'Could not reach Punica. Check the network and try again.',
        },
        origin,
      );
    }
    return;
  }

  reply(
    res,
    404,
    {
      error: 'not_found',
      message: 'Use POST /api/live/session or GET /health.',
    },
    origin,
  );
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Punica Live relay: http://127.0.0.1:${PORT}`);
  if (!apiKey()) {
    console.log('PUNICA_API_KEY missing: add it to server/.env, then restart.');
  }
  if (!geminiApiKey()) {
    console.log('GEMINI_API_KEY missing: Japanese Gemini Live voice is unavailable until it is added to server/.env.');
  }
});
