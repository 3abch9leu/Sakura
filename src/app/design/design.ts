import { AfterViewInit, Component, ElementRef, NgZone, OnDestroy, OnInit, computed, effect, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  Api, ApiError, ChatMessage, DesignName, DesignResponse, FacadeResponse, Health, SiteContext, SunResponse,
  prepareImage, png,
} from '../api';

type LeafKind = 'std' | 'wide' | 'round' | 'needle';
type Pt = [number, number];

interface PlantLook {
  name: string;
  latin: string;
  color: string;
  leaf: LeafKind;
  angles: number[];
  scale: number;
  fruit?: string;
}

interface City { name: string; lat: number; lon: number }

const PLANT_LOOKS: Record<string, PlantLook> = {
  mint: { name: 'Mint', latin: 'Mentha', color: '#4f9a5a', leaf: 'wide', angles: [-42, -14, 14, 42], scale: 1 },
  basil: { name: 'Basil', latin: 'Ocimum basilicum', color: '#3f8a4a', leaf: 'round', angles: [-50, -25, 0, 25, 50], scale: 1 },
  parsley: { name: 'Parsley', latin: 'Petroselinum crispum', color: '#3d8a45', leaf: 'std', angles: [-46, -23, 0, 23, 46], scale: 1 },
  lettuce: { name: 'Lettuce', latin: 'Lactuca sativa', color: '#7fb85a', leaf: 'round', angles: [-60, -30, 0, 30, 60], scale: 1.15 },
  strawberry: { name: 'Strawberry', latin: 'Fragaria × ananassa', color: '#4a8f4f', leaf: 'wide', angles: [-48, -24, 0, 24, 48], scale: 0.9, fruit: '#d4492f' },
  chili: { name: 'Chili', latin: 'Capsicum annuum', color: '#4d8a50', leaf: 'std', angles: [-40, -14, 14, 40], scale: 0.9, fruit: '#c8321e' },
  cherry_tomato: { name: 'Cherry tomato', latin: 'Solanum lycopersicum', color: '#3f7f45', leaf: 'std', angles: [-56, -28, 0, 28, 56], scale: 1, fruit: '#e0452c' },
};

const DESIGN_INFO: Record<DesignName, { label: string; pitch: string }> = {
  balanced: { label: 'Balanced', pitch: 'The best all-rounder: a much cooler room and plants that get what they need.' },
  shade_maximizer: { label: 'Coolest room', pitch: 'Blocks the most heat. Uses a bit more water to do it.' },
  water_saver: { label: 'Water saver', pitch: 'Uses the least water. Plants may be slightly under-watered on the hottest days.' },
  baseline: { label: 'Standard screen', pitch: 'A conventional perforated screen, for comparison.' },
};

@Component({
  selector: 'app-design',
  imports: [ReactiveFormsModule, DecimalPipe, RouterLink],
  templateUrl: './design.html',
  styleUrls: ['./design.css', './design.engine.css'],
})
export class DesignComponent implements OnInit, AfterViewInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly zone = inject(NgZone);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly sanitizer = inject(DomSanitizer);
  readonly api = inject(Api);
  /** 'farm' when the user chose Farm on /space (Agro is an extension in development). */
  readonly setting = inject(ActivatedRoute).snapshot.queryParamMap.get('setting') ?? 'urban';

  /* ================================================================ engine status */
  readonly engine = signal<'checking' | 'online' | 'offline'>('checking');
  readonly health = signal<Health | null>(null);
  readonly aiReady = computed(() => !!this.health()?.diffusion?.weights_cached && !!this.health()?.gpu?.cuda_available);

  /* ================================================================ roadmap */
  readonly steps = [
    { t: 'Your window', s: 'Photo & size' },
    { t: 'Its place', s: 'Direction & sun' },
    { t: 'Plants & water', s: 'What you grow' },
    { t: 'Your design', s: 'Compare & see it' },
  ];
  readonly step = signal(0);
  readonly shake = signal(false);
  readonly stepError = signal('');

  /* ================================================================ step 1: window */
  readonly photo = signal<{ blob: Blob; url: string; w: number; h: number } | null>(null);
  readonly dragging = signal(false);
  readonly fileError = signal('');
  readonly taps = signal<Pt[]>([]);
  readonly corners = signal<Pt[] | null>(null);
  readonly detecting = signal(false);
  readonly detectError = signal('');
  readonly facadeRes = signal<FacadeResponse | null>(null);
  readonly cornersEdited = signal(false);
  private dragIdx = -1;

  readonly form = this.fb.group({
    width: this.fb.control<number | null>(null, [Validators.required, Validators.min(0.3), Validators.max(6)]),
    height: this.fb.control<number | null>(null, [Validators.min(0.3), Validators.max(6)]),
  });
  get width() { return this.form.controls.width; }
  get height() { return this.form.controls.height; }
  private readonly formVal = toSignal(this.form.valueChanges, { initialValue: this.form.value });

  /** Height/width ratio of the marked window (perspective-corrected by the API when detected). */
  readonly aspect = computed(() => {
    const f = this.facadeRes();
    if (f && !this.cornersEdited()) return f.window_h_m / f.window_w_m;
    const c = this.corners();
    if (!c) return null;
    const d = (a: Pt, b: Pt) => Math.hypot(a[0] - b[0], a[1] - b[1]);
    const w = (d(c[0], c[1]) + d(c[3], c[2])) / 2;
    const h = (d(c[0], c[3]) + d(c[1], c[2])) / 2;
    return w > 0 ? h / w : null;
  });

  readonly widthM = computed(() => {
    const w = Number(this.formVal().width);
    return w >= 0.3 && w <= 6 ? w : null;
  });
  readonly typedHeight = computed(() => {
    const h = Number(this.formVal().height);
    return h >= 0.3 && h <= 6 ? h : null;
  });
  readonly heightM = computed(() => {
    const w = this.widthM();
    const a = this.aspect();
    return this.typedHeight() ?? (w && a ? Math.round(w * a * 100) / 100 : null);
  });
  readonly heightEstimated = computed(() => !this.typedHeight() && this.heightM() !== null);
  readonly grid = computed(() => {
    const w = this.widthM(), h = this.heightM();
    if (!w || !h) return null;
    const cols = Math.max(1, Math.ceil(w / 0.3)), rows = Math.max(1, Math.ceil(h / 0.3));
    return { cols, rows, total: cols * rows };
  });

  /* ================================================================ step 2: place */
  readonly cities: City[] = [
    { name: 'Tunis', lat: 36.81, lon: 10.18 },
    { name: 'Sousse', lat: 35.83, lon: 10.64 },
    { name: 'Sfax', lat: 34.74, lon: 10.76 },
    { name: 'Bizerte', lat: 37.27, lon: 9.87 },
    { name: 'Djerba', lat: 33.81, lon: 10.86 },
    { name: 'Tokyo', lat: 35.68, lon: 139.69 },
    { name: 'Osaka', lat: 34.69, lon: 135.5 },
    { name: 'Kyoto', lat: 35.01, lon: 135.77 },
  ];
  readonly city = signal<City>(this.cities[0]);
  readonly locating = signal(false);
  readonly directions = [
    { id: 'N', label: 'North', deg: 0 }, { id: 'NE', label: 'North-east', deg: 45 },
    { id: 'E', label: 'East', deg: 90 }, { id: 'SE', label: 'South-east', deg: 135 },
    { id: 'S', label: 'South', deg: 180 }, { id: 'SW', label: 'South-west', deg: 225 },
    { id: 'W', label: 'West', deg: 270 }, { id: 'NW', label: 'North-west', deg: 315 },
  ];
  readonly facing = signal<string | null>(null);
  readonly climates = [
    { rh: 0.3, label: 'Dry', note: 'Inland, desert air' },
    { rh: 0.55, label: 'Mild', note: 'Typical summer' },
    { rh: 0.75, label: 'Humid', note: 'Seaside, muggy' },
  ];
  readonly rh = signal(0.55);
  readonly sun = signal<SunResponse | null>(null);
  readonly sunLoading = signal(false);
  readonly sunHover = signal<number | null>(null);

  /* ================================================================ step 3: plants & water */
  readonly plantDemand = signal<Record<string, number>>({
    mint: 0.25, basil: 0.2, parsley: 0.18, lettuce: 0.2, strawberry: 0.3, chili: 0.25, cherry_tomato: 0.45,
  });
  readonly plantIds = computed(() => Object.keys(this.plantDemand()).filter((p) => PLANT_LOOKS[p]));
  readonly selectedPlants = signal<string[]>([]);
  readonly waterBudget = signal(6);
  readonly rootTiles = signal(4);
  readonly maxRootTiles = computed(() => this.grid()?.cols ?? 8);
  readonly looks = PLANT_LOOKS;
  readonly leaves: Record<LeafKind, string> = {
    std: 'M0 0C11-16 11-38 0-54C-11-38-11-16 0 0Z',
    wide: 'M0 0C17-14 17-34 0-46C-17-34-17-14 0 0Z',
    round: 'M0 0C15-6 17-26 0-36C-17-26-15-6 0 0Z',
    needle: 'M0 0C3-18 3-40 0-58C-3-40-3-18 0 0Z',
  };

  /* ================================================================ step 4: results */
  readonly optimizing = signal(false);
  readonly optStage = signal(0);
  readonly optStages = ['Tracing the sun on your wall', 'Testing thousands of tile shapes', 'Balancing shade, water and plants'];
  readonly designs = signal<DesignResponse | null>(null);
  readonly chosen = signal<DesignName>('balanced');
  readonly order: DesignName[] = ['balanced', 'shade_maximizer', 'water_saver'];
  readonly info = DESIGN_INFO;
  private svgCache = new Map<string, SafeHtml>();

  readonly visual = signal<Record<string, { tryon?: string; render?: string; renderMsg?: string; renderSecs?: number }>>({});
  readonly tryonLoading = signal(false);
  readonly tryonError = signal('');
  readonly rendering = signal(false);
  readonly renderElapsed = signal(0);
  readonly renderError = signal('');
  readonly strength = signal(0.35);
  readonly seed = signal(42);
  readonly view = signal<'ai' | 'tiles'>('tiles');
  readonly split = signal(50);

  readonly current = computed(() => this.designs()?.designs[this.chosen()] ?? null);
  readonly baseline = computed(() => this.designs()?.designs.baseline ?? null);
  readonly currentVisual = computed(() => this.visual()[this.chosen()] ?? {});
  readonly shownImage = computed(() => {
    const v = this.currentVisual();
    return this.view() === 'ai' && v.render ? v.render : v.tryon ?? null;
  });

  /* ================================================================ assistant */
  readonly chatOpen = signal(false);
  readonly chatBusy = signal(false);
  readonly chatError = signal('');
  readonly chatLog = signal<{ role: 'user' | 'assistant'; text: string }[]>([]);
  private chatHistory: ChatMessage[] = [];
  readonly chatInput = signal('');
  readonly suggestions = [
    'Why is this design better than a normal screen?',
    'How often do I refill the water bottle?',
    'Which plants grow best on this window?',
  ];

  private timers: ReturnType<typeof setTimeout | typeof setInterval>[] = [];

  constructor() {
    // Live sun profile whenever direction or city changes.
    effect(() => {
      const f = this.facing();
      const c = this.city();
      if (f && this.engine() === 'online') this.loadSun(f, c);
    });
    // Keep root tiles within the window width.
    effect(() => {
      const max = this.maxRootTiles();
      if (this.rootTiles() > max) this.rootTiles.set(max);
    });
  }

  /* ---------------------------------------------------------------- lifecycle */
  private onPointer = (e: PointerEvent) => {
    const el = this.host.nativeElement;
    el.style.setProperty('--sx', `${e.clientX}px`);
    el.style.setProperty('--sy', `${e.clientY}px`);
  };

  ngOnInit(): void {
    this.checkEngine();
  }

  ngAfterViewInit(): void {
    this.zone.runOutsideAngular(() => window.addEventListener('pointermove', this.onPointer, { passive: true }));
  }

  ngOnDestroy(): void {
    this.clearTimers();
    window.removeEventListener('pointermove', this.onPointer);
    const p = this.photo();
    if (p) URL.revokeObjectURL(p.url);
  }

  async checkEngine(): Promise<void> {
    this.engine.set('checking');
    try {
      this.health.set(await this.api.health());
      this.engine.set('online');
      this.api.plants().then((p) => this.plantDemand.set(p)).catch(() => {});
    } catch {
      this.engine.set('offline');
    }
  }

  /* ---------------------------------------------------------------- navigation */
  next(): void {
    const s = this.step();
    const err = this.validate(s);
    if (err) {
      this.stepError.set(err);
      this.form.markAllAsTouched();
      this.bump();
      return;
    }
    this.stepError.set('');
    if (s === 2) {
      this.optimize();
      return;
    }
    this.step.set(s + 1);
    this.scrollTop();
  }

  back(): void {
    if (this.step() > 0) {
      this.stepError.set('');
      this.step.update((s) => s - 1);
      this.scrollTop();
    }
  }

  goTo(i: number): void {
    if (i < this.step()) {
      this.stepError.set('');
      this.step.set(i);
      this.scrollTop();
    }
  }

  private validate(s: number): string {
    if (s === 0) {
      if (!this.widthM()) return 'Enter the width of the window (0.3 – 6 m).';
      if (this.photo() && !this.corners()) return 'Tap the glass of your window so we can find it.';
      if (!this.photo() && !this.typedHeight()) return 'Without a photo, we also need the height.';
    }
    if (s === 1 && !this.facing()) return 'Choose which way the window faces.';
    if (s === 2) {
      const n = this.selectedPlants().length;
      if (n < 1) return 'Pick at least one plant.';
      if (n > 6) return 'Six plants at most per tile.';
    }
    return '';
  }

  /* ---------------------------------------------------------------- step 1: photo */
  onFile(e: Event): void {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    if (f) this.read(f);
    input.value = '';
  }

  onDragOver(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(true);
  }

  onDrop(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) this.read(f);
  }

  useSample(): void {
    fetch('images/sample-window.jpg')
      .then((r) => r.blob())
      .then((b) => this.read(new File([b], 'sample.jpg', { type: 'image/jpeg' })))
      .catch(() => this.fileError.set('Sample photo not found.'));
  }

  removePhoto(): void {
    const p = this.photo();
    if (p) URL.revokeObjectURL(p.url);
    this.photo.set(null);
    this.resetWindow();
  }

  private async read(f: File): Promise<void> {
    if (!f.type.startsWith('image/')) {
      this.fileError.set('Please choose an image (JPG or PNG). iPhone HEIC photos: export as JPG first.');
      return;
    }
    if (f.size > 20 * 1024 * 1024) {
      this.fileError.set('The image must be under 20 MB.');
      return;
    }
    this.fileError.set('');
    try {
      const img = await prepareImage(f);
      const old = this.photo();
      if (old) URL.revokeObjectURL(old.url);
      this.photo.set(img);
      this.resetWindow();
      this.visual.set({});
    } catch {
      this.fileError.set('This image could not be read. Try a JPG or PNG.');
    }
  }

  private resetWindow(): void {
    this.taps.set([]);
    this.corners.set(null);
    this.facadeRes.set(null);
    this.detectError.set('');
    this.cornersEdited.set(false);
  }

  /** Click on the photo: add a tap on the glass and detect the window. */
  onPhotoClick(e: MouseEvent, svg: Element): void {
    if (this.dragIdx >= 0 || this.detecting()) return;
    if (this.corners() && !this.facadeRes() && this.cornersEdited()) return; // manual mode: only drag
    const p = this.toImage(e, svg);
    const taps = this.corners() ? [p] : [...this.taps(), p].slice(-4);
    this.taps.set(taps);
    this.detect();
  }

  addPane(): void {
    // keep current taps; next click adds to them instead of replacing
    this.corners.set(null);
    this.facadeRes.set(null);
  }

  async detect(): Promise<void> {
    const p = this.photo();
    if (!p || !this.taps().length) return;
    this.detecting.set(true);
    this.detectError.set('');
    try {
      const r = await this.api.facade(p.blob, this.taps(), this.widthM() ?? 1, this.typedHeight(), this.rootTiles());
      this.facadeRes.set(r);
      this.corners.set(r.quad_px.map((q) => [q[0], q[1]] as Pt));
      this.cornersEdited.set(false);
    } catch (e) {
      this.detectError.set(
        e instanceof ApiError && e.status === 422
          ? "We couldn't outline the window from that tap. Tap the middle of the glass, or place the corners by hand."
          : (e as Error).message,
      );
    } finally {
      this.detecting.set(false);
    }
  }

  manualCorners(): void {
    const p = this.photo();
    if (!p) return;
    const { w, h } = p;
    this.facadeRes.set(null);
    this.taps.set([]);
    this.detectError.set('');
    this.corners.set([[w * 0.3, h * 0.25], [w * 0.7, h * 0.25], [w * 0.7, h * 0.75], [w * 0.3, h * 0.75]]);
    this.cornersEdited.set(true);
  }

  startDrag(i: number, e: PointerEvent, svg: Element): void {
    e.preventDefault();
    e.stopPropagation();
    this.dragIdx = i;
    svg.setPointerCapture(e.pointerId);
  }

  onDragMove(e: PointerEvent, svg: Element): void {
    if (this.dragIdx < 0) return;
    const p = this.toImage(e, svg);
    const c = [...(this.corners() ?? [])];
    c[this.dragIdx] = p;
    this.corners.set(c);
    this.cornersEdited.set(true);
  }

  endDrag(e: PointerEvent, svg: Element): void {
    if (this.dragIdx < 0) return;
    svg.releasePointerCapture(e.pointerId);
    // swallow the click that follows the drag
    setTimeout(() => (this.dragIdx = -1));
  }

  quadPoints(c: Pt[]): string {
    return c.map((p) => p.join(',')).join(' ');
  }

  /** Tile grid lines drawn inside the quad (bilinear), so users see the tiles while marking. */
  gridLines = computed(() => {
    const c = this.corners(), g = this.grid();
    if (!c || !g) return [];
    const lerp = (a: Pt, b: Pt, t: number): Pt => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    const [tl, tr, br, bl] = c;
    const lines: string[] = [];
    for (let i = 1; i < g.cols; i++) {
      const t = Math.min(1, (i * 0.3) / (this.widthM() ?? 1));
      const a = lerp(tl, tr, t), b = lerp(bl, br, t);
      lines.push(`M${a[0]} ${a[1]}L${b[0]} ${b[1]}`);
    }
    const h = this.heightM() ?? 1;
    for (let j = 1; j < g.rows; j++) {
      const t = 1 - Math.min(1, (j * 0.3) / h); // rows start at the sill
      const a = lerp(tl, bl, t), b = lerp(tr, br, t);
      lines.push(`M${a[0]} ${a[1]}L${b[0]} ${b[1]}`);
    }
    return lines;
  });

  private toImage(e: MouseEvent | PointerEvent, svg: Element): Pt {
    const p = this.photo()!;
    const r = svg.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * p.w;
    const y = ((e.clientY - r.top) / r.height) * p.h;
    return [Math.max(0, Math.min(p.w, x)), Math.max(0, Math.min(p.h, y))];
  }

  /* ---------------------------------------------------------------- step 2: place */
  pickCity(name: string): void {
    const c = this.cities.find((x) => x.name === name);
    if (c) this.city.set(c);
  }

  locate(): void {
    if (!navigator.geolocation) return;
    this.locating.set(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const c = { name: 'My location', lat: +pos.coords.latitude.toFixed(2), lon: +pos.coords.longitude.toFixed(2) };
        this.city.set(c);
        this.locating.set(false);
      },
      () => this.locating.set(false),
      { timeout: 8000 },
    );
  }

  private async loadSun(facade: string, c: City): Promise<void> {
    this.sunLoading.set(true);
    try {
      this.sun.set(await this.api.sun(facade, c.lat, c.lon));
    } catch {
      this.sun.set(null);
    } finally {
      this.sunLoading.set(false);
    }
  }

  /** Sun chart geometry: 5h-21h, W/m² on one axis. */
  readonly sunChart = computed(() => {
    const s = this.sun();
    if (!s) return null;
    const W = 560, H = 190, L = 44, R = 12, T = 14, B = 26;
    const hours = s.hourly.filter((h) => h.hour >= 5 && h.hour <= 21);
    const vals = hours.map((h) => h.beam_w_m2 + h.diffuse_w_m2);
    const max = Math.max(200, Math.ceil(Math.max(...vals) / 200) * 200);
    const x = (h: number) => L + ((h - 5) / 16) * (W - L - R);
    const y = (v: number) => T + (1 - v / max) * (H - T - B);
    const pts = hours.map((h, i) => [x(h.hour + 0.5), y(vals[i])]);
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join('');
    const area = `${line}L${pts[pts.length - 1][0].toFixed(1)} ${y(0)}L${pts[0][0].toFixed(1)} ${y(0)}Z`;
    const yTicks = [0, max / 2, max].map((v) => ({ v, y: y(v) }));
    const xTicks = [6, 9, 12, 15, 18, 21].map((h) => ({ h, x: x(h) }));
    return { W, H, L, R, T, B, line, area, yTicks, xTicks, pts, hours, vals, x, y, base: y(0) };
  });

  onSunMove(e: PointerEvent, svg: Element): void {
    const c = this.sunChart();
    if (!c) return;
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * c.W;
    let best = 0;
    c.pts.forEach((p, i) => { if (Math.abs(p[0] - px) < Math.abs(c.pts[best][0] - px)) best = i; });
    this.sunHover.set(best);
  }

  readonly sunInsight = computed(() => {
    const s = this.sun();
    if (!s) return '';
    const k = s.kwh_per_m2_day;
    const ph = parseFloat(String(s.peak_hour));
    const when = ph < 11 ? 'morning' : ph < 14 ? 'midday' : 'afternoon';
    if (k >= 3.5) return `Strong ${when} sun. Shading will make a big difference to how hot the room gets.`;
    if (k >= 2) return `Moderate ${when} sun. The screen can balance shade with daylight.`;
    return 'Little direct sun here. Plants will need less water, and shading matters less.';
  });

  /* ---------------------------------------------------------------- step 3: plants */
  togglePlant(id: string): void {
    this.selectedPlants.update((l) => (l.includes(id) ? l.filter((p) => p !== id) : l.length >= 6 ? l : [...l, id]));
    this.stepError.set('');
  }

  isSelected(id: string): boolean {
    return this.selectedPlants().includes(id);
  }

  readonly plantNeed = computed(() =>
    this.selectedPlants().reduce((s, p) => s + (this.plantDemand()[p] ?? 0), 0) * this.rootTiles(),
  );

  setRoot(d: number): void {
    this.rootTiles.update((v) => Math.max(1, Math.min(this.maxRootTiles(), v + d)));
  }

  /* ---------------------------------------------------------------- optimize */
  private ctx(): SiteContext {
    const g = this.grid();
    return {
      plants: this.selectedPlants(),
      facade: this.facing() ?? 'S',
      rh: this.rh(),
      window_w: this.widthM() ?? 1.2,
      window_h: this.heightM() ?? 1.4,
      root_tiles: Math.min(this.rootTiles(), g?.cols ?? this.rootTiles()),
      water_available_l_day: this.waterBudget(),
      lat: this.city().lat,
      lon: this.city().lon,
    };
  }

  async optimize(): Promise<void> {
    if (this.engine() !== 'online') {
      this.stepError.set('The design engine is offline. Start it, then press Retry at the top.');
      this.bump();
      return;
    }
    this.optimizing.set(true);
    this.optStage.set(0);
    this.timers.push(setTimeout(() => this.optStage.set(1), 700), setTimeout(() => this.optStage.set(2), 2200));
    try {
      const d = await this.api.design(this.ctx(), true);
      this.designs.set(d);
      this.svgCache.clear();
      this.visual.set({});
      this.chosen.set('balanced');
      this.view.set('tiles');
      this.chatLog.set([]);
      this.chatHistory = [];
      this.step.set(3);
      this.scrollTop();
      if (this.photo() && this.corners()) this.loadTryon('balanced');
    } catch (e) {
      const msg = (e as Error).message;
      this.stepError.set(
        e instanceof ApiError && e.status === 422 && /feasible/i.test(msg)
          ? 'No design fits these limits. Allow more water per day, or choose fewer plants.'
          : msg,
      );
      this.bump();
    } finally {
      this.clearTimers();
      this.optimizing.set(false);
    }
  }

  choose(n: DesignName): void {
    this.chosen.set(n);
    this.renderError.set('');
    this.tryonError.set('');
    if (this.photo() && this.corners() && !this.visual()[n]?.tryon) this.loadTryon(n);
    if (!this.visual()[n]?.render) this.view.set('tiles');
  }

  svgOf(n: DesignName): SafeHtml | null {
    const d = this.designs()?.designs[n];
    if (!d) return null;
    if (!this.svgCache.has(n)) this.svgCache.set(n, this.sanitizer.bypassSecurityTrustHtml(d.preview_svg));
    return this.svgCache.get(n)!;
  }

  private async loadTryon(n: DesignName): Promise<void> {
    const p = this.photo(), c = this.corners(), d = this.designs()?.designs[n];
    if (!p || !c || !d) return;
    this.tryonLoading.set(true);
    this.tryonError.set('');
    try {
      const r = await this.api.tryon(p.blob, c, this.ctx(), this.typedHeight(), d.design);
      this.visual.update((v) => ({ ...v, [n]: { ...v[n], tryon: png(r.tryon_png_base64) } }));
    } catch (e) {
      if (this.chosen() === n) this.tryonError.set((e as Error).message);
    } finally {
      this.tryonLoading.set(false);
    }
  }

  async renderAI(newSeed = false): Promise<void> {
    const n = this.chosen();
    const p = this.photo(), c = this.corners(), d = this.current();
    if (!p || !c || !d || this.rendering()) return;
    if (newSeed) this.seed.set(Math.floor(Math.random() * 100000));
    this.rendering.set(true);
    this.renderError.set('');
    this.renderElapsed.set(0);
    const t0 = Date.now();
    const tick = setInterval(() => this.renderElapsed.set(Math.round((Date.now() - t0) / 1000)), 500);
    try {
      const r = await this.api.render(p.blob, c, this.ctx(), this.typedHeight(), d.design, this.strength(), this.seed());
      if (!r.enhanced) {
        this.renderError.set(r.message.replace('enhancement unavailable: ', 'The AI render is unavailable: '));
      } else {
        this.visual.update((v) => ({ ...v, [n]: { ...v[n], render: png(r.render_png_base64), renderSecs: r.render_seconds } }));
        if (this.chosen() === n) this.view.set('ai');
        this.health.update((h) => (h ? { ...h, diffusion: { ...h.diffusion, pipeline_loaded: true } } : h));
      }
    } catch (e) {
      this.renderError.set((e as Error).message);
    } finally {
      clearInterval(tick);
      this.rendering.set(false);
    }
  }

  download(): void {
    const src = this.shownImage();
    if (!src) return;
    const a = document.createElement('a');
    a.href = src;
    a.download = `inbetween-${this.chosen()}-${this.view() === 'ai' ? 'ai-render' : 'tiles'}.png`;
    a.click();
  }

  downloadSpec(): void {
    const d = this.current();
    if (!d) return;
    const spec = {
      design: this.chosen(), site: this.ctx(), tile: d.design,
      results: { objectives: d.result.objectives, panel: d.result.panel, pockets: d.result.pockets, hydraulics: d.result.hydraulics },
    };
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(spec, null, 2)], { type: 'application/json' }));
    a.download = `inbetween-${this.chosen()}-spec.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /* ---------------------------------------------------------------- result helpers */
  fedPct(n: DesignName): number {
    const d = this.designs()?.designs[n];
    return d ? Math.round((1 - d.result.objectives.plant_deficit) * 100) : 0;
  }

  heatPct(n: DesignName): number {
    return Math.round(this.designs()?.designs[n]?.result.panel.heat_reduction_pct ?? 0);
  }

  water(n: DesignName): number {
    return this.designs()?.designs[n]?.result.objectives.water_l_day ?? 0;
  }

  /** Bars: water received vs needed per plant (per root tile). */
  readonly waterBars = computed(() => {
    const d = this.current();
    if (!d) return [];
    const max = Math.max(...d.result.pockets.flatMap((p) => [p.received_l, p.need_l])) * 1.1;
    return d.result.pockets.map((p) => ({
      ...p,
      name: PLANT_LOOKS[p.plant]?.name ?? p.plant,
      recW: (p.received_l / max) * 100,
      needX: (p.need_l / max) * 100,
      ok: p.ratio >= 0.95,
    }));
  });
  readonly barHover = signal<number | null>(null);

  readonly refillDays = computed(() => {
    const d = this.current();
    if (!d) return null;
    // one 10x10 cm tank per root tile; assume a 1.5 L bottle feeds one tile
    return d.design.water_l_day > 0 ? 1.5 / d.design.water_l_day : null;
  });

  /* ---------------------------------------------------------------- assistant */
  async ask(text?: string): Promise<void> {
    const q = (text ?? this.chatInput()).trim();
    if (!q || this.chatBusy()) return;
    this.chatInput.set('');
    this.chatError.set('');
    this.chatLog.update((l) => [...l, { role: 'user', text: q }]);
    let content = q;
    if (!this.chatHistory.length) {
      const c = this.ctx(), d = this.current();
      content =
        `Context: my window is ${c.window_w} x ${c.window_h} m, facing ${c.facade}, in ${this.city().name} ` +
        `(lat ${c.lat}, lon ${c.lon}), relative humidity ${c.rh}, plants ${c.plants.join(', ')}, ` +
        `${c.root_tiles} root tiles, water budget ${c.water_available_l_day} L/day.` +
        (d ? ` I am looking at the "${DESIGN_INFO[this.chosen()].label}" design: ${JSON.stringify(d.design)}.` : '') +
        `\n\nQuestion: ${q}`;
    }
    this.chatHistory = [...this.chatHistory, { role: 'user', content }];
    this.chatBusy.set(true);
    try {
      const r = await this.api.chat(this.chatHistory);
      this.chatHistory = r.messages;
      this.chatLog.update((l) => [...l, { role: 'assistant', text: r.reply }]);
    } catch (e) {
      this.chatHistory = this.chatHistory.slice(0, -1);
      this.chatError.set(
        e instanceof ApiError && e.status === 503
          ? 'The assistant has no language model available right now (set GROQ_API_KEY or start Ollama on the server).'
          : (e as Error).message,
      );
    } finally {
      this.chatBusy.set(false);
    }
  }

  /* ---------------------------------------------------------------- utils */
  private clearTimers(): void {
    this.timers.forEach((t) => clearTimeout(t as ReturnType<typeof setTimeout>));
    this.timers = [];
  }

  private bump(): void {
    this.shake.set(true);
    setTimeout(() => this.shake.set(false), 500);
  }

  private scrollTop(): void {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  plantName(id: string): string {
    return PLANT_LOOKS[id]?.name ?? id;
  }

  dirLabel(id: string | null): string {
    return this.directions.find((d) => d.id === id)?.label ?? '';
  }

  hourLabel(h: number | string): string {
    return typeof h === 'string' ? h : `${String(h).padStart(2, '0')}:00`;
  }
}
