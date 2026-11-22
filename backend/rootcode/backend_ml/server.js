
// InBetween photo relay
// Receives photos from the camera web app (multipart POST), stores them,
// and pushes each new photo to every open Angular page via Server-Sent Events.
import express from 'express';
import multer from 'multer';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 3000;
const KEY = process.env.CAMERA_KEY || ''; // optional: must match "&key=..." set in the camera app
const DIR = path.join(__dirname, 'photos');
fs.mkdirSync(DIR, { recursive: true });

const app = express();

// CORS: the camera app and the Angular app are both on other origins.
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 10 * 1024 * 1024 } });

/* ---------- photo index (newest first), rebuilt from disk on start ---------- */
const toPhoto = (id, takenAtMs, fileName) => ({
  id,
  url: `/photos/${encodeURIComponent(id)}`,
  takenAtMs,
  takenAt: new Date(takenAtMs).toISOString(),
  fileName,
});

const photos = fs
  .readdirSync(DIR)
  .map((f) => /^(\d+)_(.+)$/.exec(f))
  .filter(Boolean)
  .map((m) => toPhoto(m[0], Number(m[1]), m[2]))
  .sort((a, b) => b.takenAtMs - a.takenAtMs);

/* ---------- live stream (SSE) ---------- */
const clients = new Set();

function broadcast(event, data) {
  for (const c of clients) c.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

app.get('/api/camera/stream', (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.write('retry: 3000\n\n');
  clients.add(res);
  req.on('close', () => clients.delete(res));
});

setInterval(() => {
  for (const c of clients) c.write(': ping\n\n');
}, 25000);

/* ---------- receive a photo from the camera app ---------- */
app.post('/api/camera/photos', upload.single('photo'), async (req, res) => {
  if (KEY && req.body.key !== KEY) return res.status(401).json({ ok: false, error: 'bad key' });
  if (!req.file) return res.status(400).json({ ok: false, error: 'photo missing' });

  const takenAtMs = Number(req.body.takenAtMs) || Date.parse(req.body.takenAt) || Date.now();
  const safe = path
    .basename(req.body.fileName || `photo-${takenAtMs}.jpg`)
    .replace(/[^\w.-]/g, '_');
  const id = `${takenAtMs}_${safe}`;

  // The camera retries failed sends; never store or announce the same photo twice.
  if (photos.some((p) => p.id === id)) return res.status(200).json({ ok: true, duplicate: true });

  await fs.promises.writeFile(path.join(DIR, id), req.file.buffer);
  const photo = toPhoto(id, takenAtMs, safe);
  photos.push(photo);
  photos.sort((a, b) => b.takenAtMs - a.takenAtMs);
  broadcast('photo', photo);

  console.log(`photo received: ${id} (${req.file.size} bytes, ${clients.size} viewer(s))`);
  res.status(201).json({ ok: true });
});

/* ---------- read APIs ---------- */
app.get('/api/camera/photos', (_req, res) => res.json(photos.slice(0, 100)));
app.use('/photos', express.static(DIR, { maxAge: '1d' }));

app.listen(PORT, () => console.log(`Photo relay listening on http://localhost:${PORT}`));
