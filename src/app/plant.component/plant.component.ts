import {
  AfterViewInit,
  Component,
  ElementRef,
  NgZone,
  OnDestroy,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { Api } from '../api';

interface RelayPhoto {
  id: string;
  url: string;
  takenAtMs: number;
  takenAt: string;
  fileName: string;
}

interface Photo extends RelayPhoto {
  /** Absolute image URL on the relay. */
  src: string;
}

type Status = 'connecting' | 'live' | 'offline';

/** The camera app takes one photo every 2 minutes. */
const INTERVAL_MS = 120_000;
const RING = 2 * Math.PI * 46;

@Component({
  selector: 'app-plant',
  imports: [DatePipe],
  templateUrl: './plant.component.html',
  styleUrl: './plant.component.css',
})
export class PlantComponent implements OnInit, AfterViewInit, OnDestroy {
  private readonly zone = inject(NgZone);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /**
   * Base URL of the photo relay (server.js). The camera app must POST to
   * `<relayUrl>/api/camera/photos`. Use the public https URL when the phone
   * is not on the same network as the relay.
   */
  readonly relayUrl = input(inject(Api).base);   // the INBETWEEN API stores the phone's photos (/api/camera/...)

  /* ---------- state ---------- */
  readonly photos = signal<Photo[]>([]);
  readonly status = signal<Status>('connecting');
  readonly freshId = signal<string | null>(null);
  readonly pinned = signal<string | null>(null);
  readonly now = signal(Date.now());

  readonly current = computed<Photo | null>(() => {
    const list = this.photos();
    const pin = this.pinned();
    return (pin ? list.find((p) => p.id === pin) : null) ?? list[0] ?? null;
  });

  /** ms until the next photo is expected, based on the latest capture time. */
  readonly nextIn = computed<number | null>(() => {
    const latest = this.photos()[0];
    if (!latest) return null;
    return Math.max(0, latest.takenAtMs + INTERVAL_MS - this.now());
  });

  readonly ringOffset = computed(() => {
    const n = this.nextIn();
    const progress = n === null ? 0 : 1 - Math.min(1, n / INTERVAL_MS);
    return RING * (1 - progress);
  });

  readonly ring = RING;

  /* ---------- decorative ---------- */
  readonly orbit8 = this.star(0, 0, 190, 118, 8, -Math.PI / 2);
  readonly orbit6 = this.star(0, 0, 170, 100, 6, 0);
  readonly leafD = 'M0 0C11-16 11-38 0-54C-11-38-11-16 0 0Z';
  readonly leaves = Array.from({ length: 6 }, (_, i) => ({
    left: (i * 17 + 9) % 100,
    delay: -(i * 3.1),
    dur: 16 + (i % 3) * 4,
    size: 16 + (i % 3) * 7,
    color: ['#4f8a55', '#6aa564', '#c4693f', '#3c7347'][i % 4],
  }));

  /* ---------- runtime ---------- */
  private es: EventSource | null = null;
  private tickTimer: ReturnType<typeof setInterval> | null = null;
  private freshTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;

  private onPointer = (e: PointerEvent) => {
    const el = this.host.nativeElement;
    el.style.setProperty('--gx', `${e.clientX}px`);
    el.style.setProperty('--gy', `${e.clientY}px`);
  };

  private get base(): string {
    return this.relayUrl().replace(/\/+$/, '');
  }

  ngOnInit(): void {
    this.tickTimer = setInterval(() => this.now.set(Date.now()), 1000);
    this.connect();
  }

  ngAfterViewInit(): void {
    this.zone.runOutsideAngular(() =>
      window.addEventListener('pointermove', this.onPointer, { passive: true }),
    );
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.es?.close();
    if (this.tickTimer) clearInterval(this.tickTimer);
    if (this.freshTimer) clearTimeout(this.freshTimer);
    window.removeEventListener('pointermove', this.onPointer);
  }

  /* ---------- live connection ---------- */
  private connect(): void {
    this.status.set('connecting');
    const es = new EventSource(`${this.base}/api/camera/stream`);
    this.es = es;

    es.onopen = () => {
      this.status.set('live');
      // Catch up on anything sent while we were disconnected.
      void this.sync();
    };

    // EventSource reconnects by itself; we only reflect the state.
    es.onerror = () => this.status.set('offline');

    es.addEventListener('photo', (e) => {
      const photo = JSON.parse((e as MessageEvent<string>).data) as RelayPhoto;
      this.merge([photo], true);
    });
  }

  private async sync(): Promise<void> {
    try {
      const res = await fetch(`${this.base}/api/camera/photos`);
      if (!res.ok) throw new Error(String(res.status));
      this.merge((await res.json()) as RelayPhoto[], false);
    } catch {
      if (!this.destroyed) this.status.set('offline');
    }
  }

  private merge(incoming: RelayPhoto[], announce: boolean): void {
    const byId = new Map(this.photos().map((p) => [p.id, p]));
    let newest: Photo | null = null;

    for (const raw of incoming) {
      if (byId.has(raw.id)) continue;
      const photo: Photo = { ...raw, src: this.base + raw.url };
      byId.set(photo.id, photo);
      if (!newest || photo.takenAtMs > newest.takenAtMs) newest = photo;
    }
    if (!newest) return;

    this.photos.set([...byId.values()].sort((a, b) => b.takenAtMs - a.takenAtMs));

    if (announce) {
      this.freshId.set(newest.id);
      if (this.freshTimer) clearTimeout(this.freshTimer);
      this.freshTimer = setTimeout(() => this.freshId.set(null), 12_000);
    }
  }

  /* ---------- interactions ---------- */
  pick(id: string): void {
    const latest = this.photos()[0];
    this.pinned.set(latest && latest.id === id ? null : id);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  backToLive(): void {
    this.pinned.set(null);
  }

  /* ---------- display helpers ---------- */
  ago(ms: number): string {
    const s = Math.max(0, Math.round((this.now() - ms) / 1000));
    if (s < 5) return 'just now';
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }

  countdown(ms: number | null): string {
    if (ms === null) return '--:--';
    if (ms === 0) return 'Any moment';
    const total = Math.ceil(ms / 1000);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  get statusLabel(): string {
    switch (this.status()) {
      case 'live':
        return 'Live';
      case 'connecting':
        return 'Connecting';
      default:
        return 'Reconnecting';
    }
  }

  private star(cx: number, cy: number, outer: number, inner: number, tips: number, start: number): string {
    const pts: string[] = [];
    for (let i = 0; i < tips * 2; i++) {
      const r = i % 2 === 0 ? outer : inner;
      const a = start + (i * Math.PI) / tips;
      pts.push(`${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`);
    }
    return pts.join(' ');
  }
}