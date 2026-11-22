import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api } from '../api';
import {
  PHOTO_PATH,
  UploadTarget,
  clearTarget,
  defaultTarget,
  loadTarget,
  normalizeEndpoint,
  saveTarget,
  sendPhoto,
} from './upload';

type UploadState = 'pending' | 'sending' | 'sent' | 'failed';

interface Shot {
  id: number;
  ts: number;
  thumbUrl: string;
  upload: UploadState;
  error?: string;
}

type Bits = Blob | ArrayBuffer;

interface ShotRecord {
  id: number;
  ts: number;
  thumb: Bits;
  full: Bits;
  upload?: UploadState;
  attempts?: number;
  error?: string;
}

/**
 * Photos are written as raw bytes, not Blobs: iOS Safari can accept a Blob into
 * IndexedDB and hand back a record without it, which left uploads with nothing
 * to send ("photo missing from local storage"). ArrayBuffers round-trip reliably.
 */
function asBlob(v: Bits | undefined | null): Blob | undefined {
  if (!v) return undefined;
  if (v instanceof Blob) return v.size ? v : undefined;
  return v.byteLength ? new Blob([v], { type: 'image/jpeg' }) : undefined;
}

const DB_NAME = 'inbetween-camera';
const STORE = 'photos';
const INTERVAL_MS = 120_000; // one photo every two minutes
const RETRY_STEPS = [8_000, 20_000, 45_000, 120_000];

@Component({
  selector: 'app-camera',
  imports: [RouterLink],
  template: `
    <div class="cam">
      <header class="top">
        <a routerLink="/dashboard" class="back">← Digital twin</a>
        <span class="brand"><b>INBETWEEN</b> plant camera</span>
      </header>

      <h1>Plant camera</h1>
      <p class="lead">
        Point the back camera at {{ cell() != null ? 'planting cell #' + cell() : 'your plants' }}. A photo is taken every
        two minutes and sent to the digital twin, where any leaf can be checked for spots.
      </p>

      <div class="hud">
        <div class="rec">
          <span class="dot" [class.live]="live()"></span>
          <span>{{ statusLabel() }}</span>
        </div>
        <div class="pill" [class.muted]="!live()">{{ live() ? 'next ' + countdown() : '—' }}</div>
      </div>

      <div class="stage">
        <video #video playsinline muted autoplay></video>
        <canvas #canvas hidden></canvas>

        @if (!live()) {
          <div class="gate">
            @if (needsTap()) {
              <p class="gate-title">Allow the back camera</p>
              <p class="gate-text">Phones only open the camera after a tap. After this one, photos are taken on their own.</p>
              <button (click)="retry()">Allow camera</button>
            } @else if (error()) {
              <p class="gate-title">Camera unavailable</p>
              <p class="gate-text">{{ error() }}</p>
              <button (click)="retry()">Try again</button>
            } @else {
              <p class="gate-text">Opening the back camera…</p>
            }
          </div>
        }
        <div class="badge" [class.on]="live()">every 2 min · back camera</div>
      </div>

      <div class="actions">
        <button (click)="snapNow()" [disabled]="!live()">Take a photo now</button>
      </div>

      @if (editing()) {
        <section class="setup">
          <p class="setup-title">Where should the photos go?</p>
          <p class="setup-text">
            By default they go to the INBETWEEN engine this site uses. To send them through a tunnel instead, paste its
            address: the path {{ photoPath() }} is added for you.
          </p>
          <input #endpoint type="url" inputmode="url" autocapitalize="off" autocorrect="off" spellcheck="false"
                 placeholder="https://your-tunnel.trycloudflare.com" [value]="uploadTarget()?.url ?? ''" />
          <button (click)="connect(endpoint.value)">Use this address</button>
          @if (setupError()) { <p class="note">{{ setupError() }}</p> }
          <button class="link" (click)="cancelEdit()">Keep the current address</button>
          <button class="link" (click)="useDefaultTarget()">Back to the INBETWEEN engine</button>
        </section>
      } @else {
        <div class="sync">
          <span class="sync-dot" [class.sent]="syncState() === 'sent'" [class.fail]="syncState() === 'failed'"></span>
          <span class="sync-text">{{ uploadLine() }}</span>
          <button class="link" (click)="forgetTarget()">Change</button>
        </div>
        @if (lastError()) { <p class="note">{{ lastError() }}</p> }
      }

      <section class="roll">
        <div class="roll-head">
          <h2>Photos</h2>
          <span>{{ shots().length }} {{ shots().length === 1 ? 'photo' : 'photos' }} on this phone</span>
        </div>
        @if (!shots().length) {
          <p class="empty">The first photo is taken a few seconds after the camera opens.</p>
        }
        <div class="grid">
          @for (s of roll(); track s.id) {
            <button class="thumb" (click)="open(s)" [attr.aria-label]="'Preview photo ' + time(s.ts)">
              <img [src]="s.thumbUrl" [alt]="'Photo taken at ' + time(s.ts)" loading="lazy" />
              <span class="stamp">{{ time(s.ts) }}</span>
              <span class="mark" [class.sent]="s.upload === 'sent'" [class.fail]="s.upload === 'failed'" [title]="markLabel(s)">{{ mark(s) }}</span>
            </button>
          }
        </div>
        @if (storageNote()) { <p class="note">{{ storageNote() }}</p> }
      </section>

      @if (viewing(); as v) {
        <div class="viewer" (click)="closeViewer()">
          <div class="viewer-top" (click)="$event.stopPropagation()">
            <button class="ghost" (click)="closeViewer()">Close</button>
            <span class="viewer-when">{{ day(v.shot.ts) }} · {{ time(v.shot.ts) }}</span>
            <button class="ghost danger" (click)="remove()">Delete</button>
          </div>
          <img class="viewer-img" [src]="v.url" [alt]="'Photo from ' + time(v.shot.ts)" (click)="$event.stopPropagation()" />
          <div class="viewer-bottom" (click)="$event.stopPropagation()">
            <button class="ghost" (click)="saveOne()">Save to Photos</button>
            @if (v.shot.upload !== 'sent') { <button (click)="resend()">Send now</button> } @else { <button disabled>Sent</button> }
          </div>
        </div>
      }

      @if (toast()) { <div class="toast">{{ toast() }}</div> }
    </div>
  `,
  styles: [
    `
      :host {
        --ivory: #f5f1e8; --paper: #fbf9f4; --olive: #414b30; --sage: #a8b39b; --terra: #b77b59; --ink: #292c25;
        --muted: #6a6d63; --line: rgba(41, 44, 37, 0.13);
        display: block; min-height: 100dvh; background: var(--ivory); color: var(--ink);
        font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; -webkit-font-smoothing: antialiased;
        -webkit-tap-highlight-color: transparent;
      }
      .cam { max-width: 640px; margin: 0 auto; padding: calc(env(safe-area-inset-top, 0px) + 14px) 18px calc(env(safe-area-inset-bottom, 0px) + 36px); }
      .top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 26px; font-size: 13px; }
      .back { color: var(--olive); text-decoration: none; }
      .brand { color: var(--muted); }
      .brand b { letter-spacing: 0.24em; font-weight: 600; color: var(--olive); font-size: 11.5px; margin-right: 6px; }
      h1 { margin: 0 0 8px; font-family: 'Cormorant Garamond', Georgia, serif; font-weight: 500; font-size: 38px; line-height: 1.05; }
      .lead { margin: 0 0 20px; font-size: 14.5px; line-height: 1.6; color: var(--muted); }

      .hud { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 0 2px 10px; font-size: 13.5px; }
      .rec { display: flex; align-items: center; gap: 8px; color: var(--muted); }
      .dot { width: 8px; height: 8px; border-radius: 50%; background: #b9b4a8; }
      .dot.live { background: var(--terra); box-shadow: 0 0 0 4px rgba(183, 123, 89, 0.18); }
      .pill { font-variant-numeric: tabular-nums; font-size: 13px; padding: 4px 11px; border-radius: 999px; border: 1px solid var(--line); }
      .pill.muted { opacity: 0.5; }

      .stage { position: relative; border-radius: 2px; overflow: hidden; background: #1d1f1a; aspect-ratio: 4 / 3; }
      video { width: 100%; height: 100%; object-fit: cover; display: block; }
      .badge { position: absolute; left: 10px; bottom: 10px; padding: 4px 9px; border-radius: 2px; font-size: 11px;
        background: rgba(41, 44, 37, 0.6); color: #cfcabe; }
      .badge.on { color: #f5f1e8; }
      .gate { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
        padding: 22px; text-align: center; background: #22251f; color: #f5f1e8; }
      .gate-title { margin: 0; font-family: 'Cormorant Garamond', Georgia, serif; font-size: 24px; font-weight: 500; }
      .gate-text { margin: 0; max-width: 34ch; font-size: 13.5px; line-height: 1.55; color: #c9c4b8; }
      .gate button { margin-top: 6px; background: var(--ivory); color: var(--olive); }

      button { min-height: 44px; padding: 0 20px; border: 1px solid var(--olive); border-radius: 2px; background: var(--olive); color: var(--ivory);
        font: inherit; font-size: 14.5px; font-weight: 500; cursor: pointer; }
      button:active { opacity: 0.8; }
      button:disabled { opacity: 0.4; }
      .actions { display: flex; gap: 8px; margin-top: 12px; }
      .actions button { flex: 1; }

      .setup { margin-top: 14px; padding: 16px; border: 1px solid var(--line); border-radius: 2px; background: var(--paper); }
      .setup-title { margin: 0 0 4px; font-weight: 600; font-size: 14px; }
      .setup-text { margin: 0 0 10px; font-size: 12.5px; line-height: 1.55; color: var(--muted); }
      .setup input { width: 100%; box-sizing: border-box; min-height: 44px; padding: 0 12px; margin-bottom: 8px; border: 1px solid var(--line);
        border-radius: 2px; background: #fff; color: var(--ink); font: inherit; font-size: 14px; }
      .setup button { width: 100%; }

      .sync { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 2px;
        background: var(--paper); font-size: 12.5px; color: var(--muted); }
      .sync-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .sync-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: #b9b4a8; }
      .sync-dot.sent { background: #5f8a4a; }
      .sync-dot.fail { background: #b8452f; }
      .link { min-height: 0; padding: 0; border: 0; background: transparent; color: var(--olive); font-size: 12.5px; font-weight: 500;
        text-decoration: underline; text-underline-offset: 3px; flex: none; margin-top: 8px; }
      .sync .link { margin-top: 0; }
      .setup .link { display: block; width: auto; }

      .roll { margin-top: 26px; }
      .roll-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
      .roll-head h2 { margin: 0; font-family: 'Cormorant Garamond', Georgia, serif; font-size: 24px; font-weight: 500; }
      .roll-head span, .empty { font-size: 12.5px; color: var(--muted); }
      .empty { margin: 0 0 12px; line-height: 1.5; }
      .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
      .thumb { position: relative; padding: 0; border: 0; border-radius: 2px; overflow: hidden; background: #e4ddcf; aspect-ratio: 1; min-height: 0; }
      .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
      .stamp { position: absolute; left: 6px; bottom: 6px; padding: 2px 6px; border-radius: 2px; font-size: 10.5px; font-variant-numeric: tabular-nums;
        background: rgba(41, 44, 37, 0.66); color: var(--ivory); }
      .mark { position: absolute; right: 6px; top: 6px; width: 18px; height: 18px; display: flex; align-items: center; justify-content: center;
        border-radius: 50%; font-size: 11px; font-weight: 700; line-height: 1; background: rgba(41, 44, 37, 0.66); color: #e0c38a; }
      .mark.sent { color: #a8d18b; }
      .mark.fail { color: #f0a38f; }
      .note { margin: 12px 0 0; font-size: 12.5px; color: #9a4a2c; }

      .viewer { position: fixed; inset: 0; z-index: 20; display: flex; flex-direction: column; background: rgba(29, 31, 26, 0.97);
        padding: calc(env(safe-area-inset-top, 0px) + 8px) 10px calc(env(safe-area-inset-bottom, 0px) + 12px); }
      .viewer-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 2px 10px; }
      .viewer-when { font-size: 12.5px; color: #c9c4b8; font-variant-numeric: tabular-nums; }
      .ghost { min-height: 38px; padding: 0 12px; border: 0; background: transparent; color: var(--ivory); font-size: 14px; }
      .ghost.danger { color: #f0a38f; }
      .viewer-img { flex: 1; min-height: 0; width: 100%; object-fit: contain; }
      .viewer-bottom { display: flex; gap: 8px; padding: 10px 2px 0; }
      .viewer-bottom button { flex: 1; background: var(--ivory); color: var(--olive); border-color: var(--ivory); }
      .viewer-bottom .ghost { background: transparent; color: var(--ivory); }
      .toast { position: fixed; left: 50%; bottom: calc(env(safe-area-inset-bottom, 0px) + 24px); transform: translateX(-50%); z-index: 30;
        max-width: 88vw; padding: 10px 14px; border-radius: 2px; background: var(--ink); color: var(--ivory); font-size: 13px; text-align: center; }
    `,
  ],
})
export class CameraComponent implements AfterViewInit, OnDestroy {
  private readonly api = inject(Api);
  /** Planting cell this phone watches (?cell=12 from the digital twin), sent with every photo. */
  readonly cell = signal<number | null>(((v) => (v != null && /^\d+$/.test(v) ? +v : null))(inject(ActivatedRoute).snapshot.queryParamMap.get('cell')));

  @ViewChild('video', { static: true }) private videoRef!: ElementRef<HTMLVideoElement>;
  @ViewChild('canvas', { static: true }) private canvasRef!: ElementRef<HTMLCanvasElement>;

  readonly shots = signal<Shot[]>([]);
  readonly roll = computed(() => [...this.shots()].reverse());
  readonly live = signal(false);
  readonly needsTap = signal(false);
  readonly error = signal('');
  readonly remaining = signal(INTERVAL_MS);
  readonly storageNote = signal('');
  readonly toast = signal('');
  readonly viewing = signal<{ shot: Shot; url: string; owned: boolean } | null>(null);

  readonly uploadTarget = signal<UploadTarget | null>(loadTarget(this.api.base));
  readonly setupError = signal('');
  readonly editing = signal(false);

  /** The failure reason of the newest unsent photo, shown under the sync line. */
  readonly lastError = computed(() => {
    const failed = this.shots().find((s) => s.upload === 'failed');
    if (!failed) return '';
    const why = failed.error ?? 'upload failed';
    if (why.includes('lost on the phone')) return `Not sent: ${why}.`;
    return `Not sent: ${why} — retrying automatically.`;
  });

  readonly countdown = computed(() => {
    const s = Math.max(0, Math.ceil(this.remaining() / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  });

  readonly statusLabel = computed(() => {
    if (this.live()) return 'Back camera live · auto';
    if (this.needsTap()) return 'Waiting for one tap';
    if (this.error()) return 'Camera off';
    return 'Starting camera…';
  });

  readonly syncState = computed(() => {
    const list = this.shots();
    if (list.some((s) => s.upload === 'failed')) return 'failed';
    if (list.length && list.every((s) => s.upload === 'sent')) return 'sent';
    return 'pending';
  });

  readonly uploadLine = computed(() => {
    const target = this.uploadTarget();
    if (!target) return '';
    let host = target.url;
    try {
      host = new URL(target.url).host;
    } catch {
      /* keep the raw value */
    }
    const list = this.shots();
    const sent = list.filter((s) => s.upload === 'sent').length;
    const busy = list.filter((s) => s.upload === 'pending' || s.upload === 'sending').length;
    const failed = list.filter((s) => s.upload === 'failed').length;
    if (!list.length) return `Ready · ${host}`;
    const parts = [`${sent} sent`];
    if (busy) parts.push(`${busy} sending`);
    if (failed) parts.push(`${failed} failed`);
    return `${parts.join(' · ')} · ${host}`;
  });

  private stream?: MediaStream;
  private clock?: number;
  private nextAt = 0;
  private wakeLock?: { release(): Promise<void> };
  private db?: IDBDatabase;
  private starting = false;
  private destroyed = false;
  private toastTimer?: number;

  private sending = false;
  private retryTimer?: number;
  private retryStep = 0;

  /** Full-size photos of this session, so a send never depends on a DB read back. */
  private readonly memory = new Map<number, Blob>();

  // ---------------------------------------------------------------- lifecycle

  async ngAfterViewInit() {
    document.addEventListener('visibilitychange', this.onVisibility);
    document.addEventListener('pointerdown', this.onAnyTap, true);
    window.addEventListener('online', this.onOnline);

    try {
      this.db = await this.openDb();
      await this.loadShots();
    } catch {
      this.storageNote.set('This phone blocks local storage: photos stay only until the page is closed.');
    }
    void this.requestPersistentStorage();
    // Anything still unsent from an earlier visit goes out now.
    this.pump();
    await this.start();
  }

  ngOnDestroy() {
    this.destroyed = true;
    this.stopCamera();
    document.removeEventListener('visibilitychange', this.onVisibility);
    document.removeEventListener('pointerdown', this.onAnyTap, true);
    window.removeEventListener('online', this.onOnline);
    if (this.toastTimer) clearTimeout(this.toastTimer);
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.shots().forEach((s) => URL.revokeObjectURL(s.thumbUrl));
    this.closeViewer();
  }

  // ------------------------------------------------------------------- camera

  retry() {
    this.needsTap.set(false);
    this.error.set('');
    void this.start();
  }

  private async start() {
    if (this.starting || this.live() || this.destroyed) return;
    this.starting = true;
    this.error.set('');

    const media = navigator.mediaDevices;
    if (!media?.getUserMedia) {
      this.error.set(
        location.protocol === 'https:'
          ? 'This browser cannot open the camera.'
          : 'The camera needs a secure (https) address. Open the site through its https link on the phone.'
      );
      this.starting = false;
      return;
    }

    try {
      const stream = await media.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' }, // back camera
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      });

      if (this.destroyed) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }

      this.stream = stream;
      this.attachTrack(stream);

      const video = this.videoRef.nativeElement;
      video.muted = true;
      video.srcObject = stream;
      try {
        await video.play();
      } catch {
        // iOS can refuse playback without a gesture even though the stream is open.
        // The frame is still captured from the canvas, and the next tap retries play().
      }

      this.live.set(true);
      this.needsTap.set(false);
      this.error.set('');
      void this.requestWakeLock();
      this.startClock();

      // First photo almost immediately so the roll is not empty, then every 2 min.
      this.nextAt = Date.now() + (this.shots().length ? INTERVAL_MS : 2500);
      this.remaining.set(Math.max(0, this.nextAt - Date.now()));
    } catch (e: any) {
      const name = e?.name ?? '';
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        this.needsTap.set(true);
      } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        this.error.set('No back camera was found on this device.');
      } else if (name === 'NotReadableError') {
        this.error.set('Another app is using the camera. Close it and tap Try again.');
        this.needsTap.set(true);
      } else {
        this.error.set(`Could not open the camera: ${e?.message ?? e}`);
      }
    } finally {
      this.starting = false;
    }
  }

  private delay(ms: number, fn: () => void) {
    setTimeout(() => {
      if (!this.destroyed) fn();
    }, ms);
  }

  private attachTrack(stream: MediaStream) {
    stream.getVideoTracks().forEach((track) => {
      track.addEventListener('ended', () => {
        if (this.destroyed) return;
        this.live.set(false);
        this.stopClock();
        this.delay(1200, () => void this.start());
      });
    });
  }

  private stopCamera() {
    this.stopClock();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = undefined;
    const v = this.videoRef?.nativeElement;
    if (v) v.srcObject = null;
    this.wakeLock?.release().catch(() => undefined);
    this.wakeLock = undefined;
    this.live.set(false);
  }

  private async requestWakeLock() {
    try {
      const wl = await (navigator as any).wakeLock?.request('screen');
      if (wl) this.wakeLock = wl;
    } catch {
      /* unsupported or denied — the phone may dim, nothing else to do */
    }
  }

  private onVisibility = () => {
    if (this.destroyed) return;
    if (document.visibilityState !== 'visible') return;

    this.pump();

    if (this.live()) {
      void this.requestWakeLock();
      void this.ensurePlaying();
      const track = this.stream?.getVideoTracks()[0];
      if (!track || track.readyState === 'ended') {
        this.live.set(false);
        this.stopClock();
        void this.start();
      }
      return;
    }
    if (!this.starting) void this.start();
  };

  private onOnline = () => {
    if (this.destroyed) return;
    this.resetFailed();
    this.pump();
  };

  /** Any tap anywhere retries a blocked camera or a paused video, without a visible button. */
  private onAnyTap = () => {
    if (this.destroyed) return;
    if (!this.live()) {
      if (!this.starting) void this.start();
      return;
    }
    void this.ensurePlaying();
  };

  private async ensurePlaying() {
    const v = this.videoRef?.nativeElement;
    if (!v || !this.stream) return;
    if (v.paused) {
      try {
        await v.play();
      } catch {
        /* still blocked; next tap or visibility change retries */
      }
    }
  }

  // -------------------------------------------------------------------- timer

  private startClock() {
    if (this.clock) return;
    this.clock = window.setInterval(() => this.tick(), 1000);
    this.tick();
  }

  private stopClock() {
    if (this.clock) clearInterval(this.clock);
    this.clock = undefined;
  }

  private tick() {
    const left = this.nextAt - Date.now();
    this.remaining.set(Math.max(0, left));
    if (left > 0) return;

    if (this.live()) {
      this.capture();
    } else {
      this.nextAt = Date.now() + 1000;
    }
  }

  // ------------------------------------------------------------------ capture

  private capture() {
    const video = this.videoRef.nativeElement;
    this.nextAt = Date.now() + INTERVAL_MS;
    this.remaining.set(INTERVAL_MS);

    if (!video.videoWidth || video.readyState < 2) {
      this.nextAt = Date.now() + 5000; // frames not ready yet, try shortly
      return;
    }

    const source = this.canvasRef.nativeElement;
    const scale = Math.min(1, 1600 / video.videoWidth);
    source.width = Math.round(video.videoWidth * scale);
    source.height = Math.round(video.videoHeight * scale);

    const ctx = source.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, source.width, source.height);

    source.toBlob(
      (blob) => {
        if (blob) void this.saveShot(blob);
      },
      'image/jpeg',
      0.86
    );
  }

  private async saveShot(full: Blob) {
    const ts = Date.now();
    const thumb = await this.makeThumb(full);
    this.memory.set(ts, full);

    const shot: Shot = {
      id: -ts,
      ts,
      thumbUrl: URL.createObjectURL(thumb),
      upload: 'pending',
    };

    try {
      const [fullBytes, thumbBytes] = await Promise.all([full.arrayBuffer(), thumb.arrayBuffer()]);
      const id = await this.put({
        ts,
        thumb: thumbBytes,
        full: fullBytes,
        upload: 'pending',
        attempts: 0,
      });

      // Read it back: a write iOS quietly drops must not look like a saved photo.
      const check = await this.get(id);
      if (!asBlob(check?.full)) throw new Error('write not confirmed');
      shot.id = id;
      this.storageNote.set('');
    } catch (e: any) {
      const why =
        e?.name === 'QuotaExceededError'
          ? 'the phone is out of space for this site'
          : e?.message || e?.name || 'storage error';
      this.storageNote.set(
        `This photo could not be saved on the phone (${why}). It is still sent to your backend now, but it disappears when this page closes.`
      );
    }

    this.shots.update((list) => [...list, shot]);

    // Real time: the photo starts uploading the instant it is taken.
    this.pump();
  }

  private makeThumb(full: Blob): Promise<Blob> {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(full);
      const img = new Image();
      img.onload = () => {
        const size = 420;
        const c = document.createElement('canvas');
        const ratio = Math.min(size / img.width, size / img.height, 1);
        c.width = Math.round(img.width * ratio);
        c.height = Math.round(img.height * ratio);
        c.getContext('2d')?.drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        c.toBlob((b) => resolve(b ?? full), 'image/jpeg', 0.72);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(full);
      };
      img.src = url;
    });
  }

  // ------------------------------------------------------------------ uploads

  readonly photoPath = () => PHOTO_PATH;

  connect(raw: string) {
    const value = (raw ?? '').trim();
    if (!value) {
      this.setupError.set('Paste an address first.');
      return;
    }

    const target = normalizeEndpoint(value);
    if (!target) {
      this.setupError.set('That is not a usable address, e.g. https://your-tunnel.trycloudflare.com');
      return;
    }

    this.uploadTarget.set(saveTarget(target));
    this.setupError.set('');
    this.editing.set(false);
    this.retryStep = 0;
    let host = target.url;
    try {
      host = new URL(target.url).host;
    } catch {
      /* keep raw */
    }
    this.showToast(`Sending photos to ${host}`);
    this.pump();
  }

  /** Manual capture, same pipeline as the automatic one. */
  snapNow() {
    if (this.live()) this.capture();
  }

  /** "Change" — reopen the endpoint field, prefilled with the current value. */
  forgetTarget() {
    this.setupError.set('');
    this.editing.set(true);
  }

  cancelEdit() {
    this.setupError.set('');
    this.editing.set(false);
  }

  /** Back to the INBETWEEN API this site uses. */
  useDefaultTarget() {
    clearTarget();
    this.uploadTarget.set(defaultTarget(this.api.base));
    this.editing.set(false);
    this.setupError.set('');
    this.retryStep = 0;
    this.showToast('Sending photos to the INBETWEEN engine');
    this.pump();
  }

  /** Manual "Send now" from the viewer. */
  resend() {
    const v = this.viewing();
    if (!v) return;
    if (!this.uploadTarget()) {
      this.showToast('Choose where to send the photos first.');
      return;
    }
    this.markShot(v.shot.ts, 'pending');
    this.retryStep = 0;
    this.pump();
    this.closeViewer();
  }

  /** One upload at a time, oldest first, so the phone's uplink is not saturated. */
  private pump() {
    if (this.sending || this.destroyed) return;
    if (!this.uploadTarget()) return;

    const next = this.shots().find((s) => s.upload === 'pending');
    if (!next) return;

    this.sending = true;
    void this.send(next).finally(() => {
      this.sending = false;
      if (!this.destroyed) this.pump();
    });
  }

  private async send(shot: Shot) {
    const target = this.uploadTarget();
    if (!target) return;

    this.markShot(shot.ts, 'sending');

    try {
      const rec = await this.get(shot.id);
      // Prefer this session's copy: it is the exact bytes just captured.
      const photo = this.memory.get(shot.ts) ?? asBlob(rec?.full);
      if (!photo) {
        // Nothing left to send — retrying can never succeed, so stop the loop.
        throw Object.assign(new Error('the photo was lost on the phone — delete it'), {
          fatal: true,
        });
      }

      const res = await sendPhoto(target, photo, {
        takenAt: shot.ts,
        fileName: this.fileName(shot.ts),
        cell: this.cell(),
      });

      if (!res.ok) throw new Error(res.error ?? `HTTP ${res.status}`);

      this.markShot(shot.ts, 'sent');
      await this.patch(shot, { upload: 'sent', attempts: 0, error: '' });
      this.retryStep = 0;
    } catch (e: any) {
      const message = e?.message ?? 'Upload failed';
      this.markShot(shot.ts, 'failed', message);
      const attempts = (await this.get(shot.id))?.attempts ?? 0;
      await this.patch(shot, { upload: 'failed', attempts: attempts + 1, error: message });
      if (!e?.fatal) this.scheduleRetry();
    }
  }

  private scheduleRetry() {
    if (this.retryTimer || this.destroyed) return;
    const wait = RETRY_STEPS[Math.min(this.retryStep, RETRY_STEPS.length - 1)];
    this.retryStep += 1;
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = undefined;
      this.resetFailed();
      this.pump();
    }, wait);
  }

  private resetFailed() {
    const failed = this.shots().filter((s) => s.upload === 'failed');
    if (!failed.length) return;
    this.shots.update((list) =>
      list.map((s) => (s.upload === 'failed' ? { ...s, upload: 'pending' as UploadState } : s))
    );
    failed.forEach((s) => void this.patch(s, { upload: 'pending' }));
  }

  private markShot(ts: number, upload: UploadState, error?: string) {
    this.shots.update((list) =>
      list.map((s) => (s.ts === ts ? { ...s, upload, error: error ?? s.error } : s))
    );
  }

  mark(s: Shot) {
    switch (s.upload) {
      case 'sent':
        return '✓';
      case 'sending':
        return '↑';
      case 'failed':
        return '!';
      default:
        return '·';
    }
  }

  markLabel(s: Shot) {
    switch (s.upload) {
      case 'sent':
        return 'Sent to the digital twin';
      case 'sending':
        return 'Sending';
      case 'failed':
        return `Not sent yet${s.error ? ` — ${s.error}` : ''}`;
      default:
        return 'Queued to send';
    }
  }

  // ------------------------------------------------------------------ roll UI

  async open(shot: Shot) {
    this.closeViewer();
    let url = shot.thumbUrl;
    let owned = false;
    try {
      const rec = await this.get(shot.id);
      const full = asBlob(rec?.full) ?? this.memory.get(shot.ts);
      if (full) {
        url = URL.createObjectURL(full);
        owned = true;
      }
    } catch {
      /* fall back to the thumbnail */
    }
    this.viewing.set({ shot, url, owned });
  }

  closeViewer() {
    const v = this.viewing();
    if (v?.owned) URL.revokeObjectURL(v.url);
    this.viewing.set(null);
  }

  async remove() {
    const v = this.viewing();
    if (!v) return;
    if (!confirm('Delete this photo?')) return;
    const id = v.shot.id;
    this.closeViewer();
    this.memory.delete(v.shot.ts);
    this.shots.update((list) => list.filter((s) => s.id !== id));
    URL.revokeObjectURL(v.shot.thumbUrl);
    try {
      await this.tx('readwrite', (store) => store.delete(id));
    } catch {
      /* already gone */
    }
  }

  async saveOne() {
    const v = this.viewing();
    if (!v) return;
    const nav = navigator as any;
    try {
      const rec = await this.get(v.shot.id);
      const blob =
        asBlob(rec?.full) ??
        this.memory.get(v.shot.ts) ??
        (await (await fetch(v.shot.thumbUrl)).blob());
      const file = new File([blob], this.fileName(v.shot.ts), { type: 'image/jpeg' });
      if (nav.canShare?.({ files: [file] })) {
        await nav.share({ files: [file] });
      } else {
        this.showToast('Saving to Photos is not available in this browser.');
      }
    } catch {
      /* share sheet cancelled */
    }
  }

  time(ts: number) {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  day(ts: number) {
    const d = new Date(ts);
    const today = new Date();
    const same = (a: Date, b: Date) =>
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate();
    if (same(d, today)) return 'Today';
    const yesterday = new Date(today.getTime() - 86_400_000);
    if (same(d, yesterday)) return 'Yesterday';
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  private fileName(ts: number) {
    const d = new Date(ts);
    const p = (n: number) => String(n).padStart(2, '0');
    return `photo-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(
      d.getMinutes()
    )}${p(d.getSeconds())}.jpg`;
  }

  private showToast(message: string) {
    this.toast.set(message);
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => this.toast.set(''), 3500);
  }

  // --------------------------------------------------------------- IndexedDB

  private openDb(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  private tx<T>(
    mode: IDBTransactionMode,
    run: (store: IDBObjectStore) => IDBRequest<T>
  ): Promise<T> {
    return new Promise((resolve, reject) => {
      if (!this.db) return reject(new Error('storage unavailable'));
      const req = run(this.db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  private put(rec: Omit<ShotRecord, 'id'>): Promise<number> {
    return this.tx<number>('readwrite', (store) => store.add(rec) as IDBRequest<number>);
  }

  private get(id: number): Promise<ShotRecord | undefined> {
    return this.tx<ShotRecord | undefined>('readonly', (store) => store.get(id));
  }

  /** Persist the upload state so a reload does not resend what already arrived. */
  private patch(shot: Shot, patch: Partial<ShotRecord>): Promise<void> {
    if (shot.id < 0 || !this.db) return Promise.resolve();
    return new Promise((resolve) => {
      const tx = this.db!.transaction(STORE, 'readwrite');
      const store = tx.objectStore(STORE);
      const req = store.get(shot.id);
      req.onsuccess = () => {
        const rec = req.result as ShotRecord | undefined;
        if (rec) store.put({ ...rec, ...patch });
      };
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    });
  }

  private async loadShots() {
    const rows = await this.tx<ShotRecord[]>('readonly', (store) => store.getAll());
    this.shots.set(
      rows.map((r) => ({
        id: r.id,
        ts: r.ts,
        thumbUrl: URL.createObjectURL(asBlob(r.thumb) ?? asBlob(r.full) ?? new Blob()),
        upload: r.upload ?? 'pending',
        error: r.error,
      }))
    );
  }

  private async requestPersistentStorage() {
    try {
      const storage = navigator.storage as any;
      if (storage?.persist && !(await storage.persisted())) await storage.persist();
    } catch {
      /* best effort */
    }
  }
}
