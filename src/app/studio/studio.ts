import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Router, RouterLink } from '@angular/router';
import { Api, png } from '../api';
import { Twin3dComponent, TwinSun, TwinView } from '../twin/twin3d';
import {
  AreaResponse, GenDesign, Greenery, Obstacle, PLANT_LABEL, PreviewResponse, SegmentResponse, SolarDay, StylesResponse,
  UploadResponse, XY, saveInstallation,
} from '../twin/types';

type Tool = 'include' | 'exclude' | 'rect' | 'polygon' | 'reference';
type Layer = 'original' | 'segmented' | 'geometry' | 'realistic';

interface City { name: string; lat: number; lon: number }

const STYLE_INFO: { id: string; name: string; culture: string }[] = [
  { id: 'mashrabiya', name: 'Mashrabiya', culture: 'Tunisia' },
  { id: 'arabic_star', name: 'Arabic stars', culture: 'Tunisia / Arab world' },
  { id: 'asanoha', name: 'Asanoha', culture: 'Japan' },
  { id: 'sakura', name: 'Sakura', culture: 'Japan' },
  { id: 'seigaiha', name: 'Seigaiha waves', culture: 'Japan' },
  { id: 'tree', name: 'Organic branches', culture: 'Nature' },
  { id: 'honeycomb', name: 'Honeycomb', culture: 'Nature' },
  { id: 'hybrid', name: 'Tunisian × Japanese', culture: 'Hybrid' },
];

@Component({
  selector: 'app-studio',
  imports: [DecimalPipe, RouterLink, Twin3dComponent],
  templateUrl: './studio.html',
  styleUrl: './studio.css',
})
export class StudioComponent implements OnDestroy {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly san = inject(DomSanitizer);
  readonly plantLabel = PLANT_LABEL;
  readonly styleInfo = STYLE_INFO;
  readonly steps = ['Space', 'Sun', 'Plants & culture', 'Designs', 'Preview'];
  readonly step = signal(0);
  readonly error = signal('');

  /* ---------------- 1. space ---------------- */
  readonly photoUrl = signal<string | null>(null);
  readonly upload = signal<UploadResponse | null>(null);
  readonly uploading = signal(false);
  readonly tool = signal<Tool>('include');
  readonly clicks = signal<{ p: XY; l: 0 | 1 }[]>([]);
  readonly poly = signal<XY[]>([]);
  readonly rectStart = signal<XY | null>(null);
  readonly rectNow = signal<XY | null>(null);
  readonly seg = signal<SegmentResponse | null>(null);
  readonly segmenting = signal(false);
  readonly keepClear = signal<Record<number, boolean>>({});
  readonly refPts = signal<XY[]>([]);
  readonly refLen = signal<number | null>(null);
  readonly heightM = signal<number | null>(null);
  /** How the user gives the one real size: the selection's width, its height, or a line on something else. */
  readonly scaleMode = signal<'width' | 'height' | 'line'>('width');
  readonly area = signal<AreaResponse | null>(null);
  readonly measuring = signal(false);
  readonly showSuggestions = signal(true);

  /* ---------------- 2. sun ---------------- */
  readonly cities: City[] = [
    { name: 'Tunis', lat: 36.81, lon: 10.18 }, { name: 'Sfax', lat: 34.74, lon: 10.76 }, { name: 'Sousse', lat: 35.83, lon: 10.64 },
    { name: 'Bizerte', lat: 37.27, lon: 9.87 }, { name: 'Gabès', lat: 33.88, lon: 10.1 }, { name: 'Tozeur', lat: 33.92, lon: 8.13 },
    { name: 'Tokyo', lat: 35.68, lon: 139.69 }, { name: 'Osaka', lat: 34.69, lon: 135.5 },
  ];
  readonly city = signal<City>(this.cities[0]);
  readonly azimuth = signal<number | null>(null);
  readonly azConfirmed = signal(false);
  readonly season = signal<'summer' | 'winter'>('summer');
  readonly solar = signal<Record<string, SolarDay>>({});
  readonly tIndex = signal(0);
  readonly compass = [['N', 0], ['NE', 45], ['E', 90], ['SE', 135], ['S', 180], ['SW', 225], ['W', 270], ['NW', 315]] as const;

  /* ---------------- 3. plants & culture ---------------- */
  readonly allPlants = Object.keys(PLANT_LABEL);
  readonly plants = signal<string[]>(['mint', 'basil', 'cherry_tomato']);
  /** How many cells become planting pockets. "full" = every pocket planted (the frame carries the pattern). */
  readonly greenery = signal<Greenery>('full');
  readonly greeneryOptions: { id: Greenery; name: string; text: string; fill: number[] }[] = [
    { id: 'full', name: 'Every pocket planted', text: 'A full green wall; the cultural pattern stays in the wooden frame.', fill: [1, 1, 1, 1, 1, 1, 1, 1, 1] },
    { id: 'balanced', name: 'Half plants, half pattern', text: 'Plants alternate with open, patterned cells.', fill: [1, 0, 1, 0, 1, 0, 1, 0, 1] },
    { id: 'pattern', name: 'Pattern first', text: 'Mostly open screen with a few plants: more light and view.', fill: [0, 0, 1, 0, 0, 0, 1, 0, 0] },
  ];
  /** Optional: only if the owner cannot give more than a fixed amount of water per day. */
  readonly waterLimitOn = signal(false);
  readonly waterLimit = signal(6);
  /** Preview: zoom on the installation instead of showing the whole photo. */
  readonly zoom = signal(true);
  /** One pattern by default (fastest, clearest choice); "compare" mode allows several. */
  readonly styleSel = signal<string[]>(['hybrid']);
  readonly compare = signal(false);
  readonly patterns = signal<Record<string, { svg: SafeHtml | null; text: string }>>({});
  readonly prices = signal<{ frame: number | null; screen: number | null; pocket: number | null }>({ frame: null, screen: null, pocket: null });

  /* ---------------- 4. designs ---------------- */
  readonly result = signal<StylesResponse | null>(null);
  readonly generating = signal(false);
  readonly genElapsed = signal(0);
  readonly chosen = signal<GenDesign | null>(null);
  readonly twinView = signal<TwinView>('environment');
  readonly twinChannels = signal(false);

  /* ---------------- 5. preview ---------------- */
  readonly preview = signal<PreviewResponse | null>(null);
  readonly previewing = signal(false);
  readonly realisticBusy = signal(false);
  readonly layer = signal<Layer>('geometry');
  readonly split = signal(55);

  private timer: ReturnType<typeof setInterval> | null = null;

  /* ================================================================ derived */
  readonly vb = computed(() => {
    const u = this.upload();
    return u ? `0 0 ${u.width} ${u.height}` : '0 0 100 100';
  });

  readonly overlay = computed(() => (this.seg() ? png(this.seg()!.overlay_png_base64) : null));

  readonly obstaclesKept = computed(() => (this.seg()?.obstacles ?? []).filter((_, i) => this.keepClear()[i] !== false));

  readonly sunDay = computed(() => this.solar()[this.season()] ?? null);

  readonly twinSun = computed<TwinSun | null>(() => {
    const d = this.sunDay();
    if (!d) return null;
    const i = Math.min(this.tIndex(), d.times.length - 1);
    let rel = d.sun_azimuth[i] - d.azimuth_facade;
    rel = ((rel + 540) % 360) - 180;
    return { elevation: d.sun_elevation[i], relAzimuth: rel, beam: d.beam_w_m2[i], index: i, season: this.season() };
  });

  readonly sunNow = computed(() => {
    const d = this.sunDay();
    if (!d) return null;
    const i = Math.min(this.tIndex(), d.times.length - 1);
    return { time: d.times[i], el: d.sun_elevation[i], az: d.sun_azimuth[i], facing: d.facing[i], beam: d.beam_w_m2[i], diffuse: d.diffuse_w_m2[i] };
  });

  /** Elevation curve + irradiance bars for the sun panel (SVG 600 x 180). */
  readonly sunChart = computed(() => {
    const d = this.sunDay();
    if (!d) return null;
    const n = d.times.length, W = 600, H = 180;
    const x = (i: number) => 30 + (i / Math.max(1, n - 1)) * (W - 50);
    const el = d.sun_elevation.map((e, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${(H - 30 - Math.max(0, e) / 90 * (H - 50)).toFixed(1)}`).join(' ');
    const maxI = Math.max(800, ...d.beam_w_m2.map((b, i) => b + d.diffuse_w_m2[i]));
    const bars = d.times.map((t, i) => ({ x: x(i) - 3, h: ((d.beam_w_m2[i] + d.diffuse_w_m2[i]) / maxI) * (H - 50), beam: d.facing[i] }));
    const ticks = d.times.map((t, i) => ({ t, x: x(i) })).filter((_, i) => i % 4 === 0);
    return { el, bars, ticks, H, cursor: x(Math.min(this.tIndex(), n - 1)) };
  });

  readonly exifAz = computed(() => this.upload()?.exif?.facade_azimuth_deg ?? null);

  ngOnDestroy(): void {
    if (this.timer) clearInterval(this.timer);
  }

  svgOf(d: GenDesign): SafeHtml {
    return this.san.bypassSecurityTrustHtml(d.svg ?? '');
  }

  png(b: string | null | undefined): string | null {
    return b ? png(b) : null;
  }

  go(i: number): void {
    this.error.set('');
    if (i > 0 && !this.area()) return this.error.set('Select the space and measure it first.');
    if (i > 1 && !this.azConfirmed()) return this.error.set('Confirm the orientation of the wall first.');
    if (i > 3 && !this.chosen()) return this.error.set('Choose a design first.');
    this.step.set(i);
    if (i === 1) this.loadSun();
    if (i === 2) this.loadPatterns();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /* ================================================================ 1. space */
  async onFile(e: Event): Promise<void> {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) await this.start(f, f.name);
  }

  async onDrop(e: DragEvent): Promise<void> {
    e.preventDefault();
    const f = e.dataTransfer?.files?.[0];
    if (f) await this.start(f, f.name);
  }

  async useSample(): Promise<void> {
    const b = await (await fetch('images/sample-wall.jpg')).blob();
    await this.start(b, 'sample-wall.jpg');
  }

  private async start(file: Blob, name: string): Promise<void> {
    this.error.set('');
    this.reset();
    this.photoUrl.set(URL.createObjectURL(file));
    this.uploading.set(true);
    try {
      const u = await this.api.spaceUpload(file, name);    // original file: the server reads GPS / compass from EXIF
      this.upload.set(u);
      if (u.exif?.lat && u.exif.lon) this.city.set({ name: 'Photo location (EXIF)', lat: u.exif.lat, lon: u.exif.lon });
      if (u.exif?.facade_azimuth_deg != null) { this.azimuth.set(Math.round(u.exif.facade_azimuth_deg)); this.azConfirmed.set(false); }
    } catch (e) {
      this.error.set((e as Error).message);
      this.photoUrl.set(null);
    } finally {
      this.uploading.set(false);
    }
  }

  reset(): void {
    this.upload.set(null); this.seg.set(null); this.clicks.set([]); this.poly.set([]); this.area.set(null);
    this.refPts.set([]); this.refLen.set(null); this.heightM.set(null); this.scaleMode.set('width'); this.keepClear.set({}); this.result.set(null); this.chosen.set(null); this.preview.set(null);
  }

  private toImg(e: MouseEvent, svg: Element): XY {
    const r = svg.getBoundingClientRect();
    const u = this.upload()!;
    return [((e.clientX - r.left) / r.width) * u.width, ((e.clientY - r.top) / r.height) * u.height];
  }

  async onImageClick(e: MouseEvent, svg: Element): Promise<void> {
    if (!this.upload() || this.segmenting()) return;
    const p = this.toImg(e, svg);
    const t = this.tool();
    if (t === 'include' || t === 'exclude') {
      this.clicks.update((c) => [...c, { p, l: t === 'include' ? 1 : 0 }]);
      await this.runClicks();
    } else if (t === 'polygon') {
      this.poly.update((q) => [...q, p]);
    } else if (t === 'reference') {
      this.refPts.update((q) => (q.length >= 2 ? [p] : [...q, p]));
      this.area.set(null);
    }
  }

  onDown(e: PointerEvent, svg: Element): void {
    if (this.tool() !== 'rect' || !this.upload()) return;
    this.rectStart.set(this.toImg(e, svg));
    this.rectNow.set(this.rectStart());
    (e.target as Element).setPointerCapture?.(e.pointerId);
  }

  onMove(e: PointerEvent, svg: Element): void {
    if (this.tool() === 'rect' && this.rectStart()) this.rectNow.set(this.toImg(e, svg));
  }

  async onUp(): Promise<void> {
    const a = this.rectStart(), b = this.rectNow();
    this.rectStart.set(null);
    if (this.tool() !== 'rect' || !a || !b || Math.abs(a[0] - b[0]) < 8 || Math.abs(a[1] - b[1]) < 8) return;
    await this.segment({ mode: 'rect', rect: [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])] });
  }

  rectBox() {
    const a = this.rectStart(), b = this.rectNow();
    return a && b ? { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), w: Math.abs(a[0] - b[0]), h: Math.abs(a[1] - b[1]) } : null;
  }

  async closePolygon(): Promise<void> {
    if (this.poly().length < 3) return this.error.set('Place at least 3 corners.');
    await this.segment({ mode: 'polygon', polygon: this.poly() });
    this.poly.set([]);
  }

  async useSuggestion(i: number): Promise<void> {
    const s = this.upload()?.suggestions?.regions[i];
    if (!s) return;
    this.tool.set('include');
    this.clicks.set([{ p: s.seed, l: 1 }]);
    await this.runClicks();
  }

  undoClick(): void {
    this.clicks.update((c) => c.slice(0, -1));
    if (this.clicks().some((c) => c.l === 1)) this.runClicks();
    else this.seg.set(null);
  }

  clearSelection(): void {
    this.clicks.set([]); this.poly.set([]); this.seg.set(null); this.area.set(null);
  }

  private async runClicks(): Promise<void> {
    const c = this.clicks();
    if (!c.some((x) => x.l === 1)) {
      this.error.set('Start with a click on the surface you want (include).');
      this.clicks.set(c.filter((x) => x.l === 1));
      return;
    }
    await this.segment({ mode: 'click', points: c.map((x) => x.p), labels: c.map((x) => x.l) });
  }

  private async segment(body: { mode: 'click' | 'polygon' | 'rect'; points?: number[][]; labels?: number[]; polygon?: number[][]; rect?: number[] }): Promise<void> {
    this.segmenting.set(true);
    this.error.set('');
    this.area.set(null);
    try {
      const r = await this.api.spaceSegment({ image_id: this.upload()!.image_id, ...body });
      this.seg.set(r);
      this.keepClear.set(Object.fromEntries(r.obstacles.map((_, i) => [i, true])));
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.segmenting.set(false);
    }
  }

  toggleObstacle(i: number): void {
    this.keepClear.update((k) => ({ ...k, [i]: !(k[i] !== false) }));
    this.area.set(null);
  }

  pts(p: XY[]): string {
    return p.map((q) => q.join(',')).join(' ');
  }

  obstacleLabel(o: Obstacle): string {
    return o.label;
  }

  setScaleMode(m: 'width' | 'height' | 'line'): void {
    this.scaleMode.set(m);
    this.area.set(null);
    if (m === 'line') this.tool.set('reference');
    else if (this.tool() === 'reference') this.tool.set('include');
  }

  async measure(): Promise<void> {
    const s = this.seg(), r = this.refPts(), L = this.refLen(), mode = this.scaleMode();
    if (!s) return this.error.set('Select the surface first.');
    if (!L || L <= 0) return this.error.set(mode === 'line' ? 'Type the real length of the line you drew, in metres.'
      : `Type the real ${mode} of the selected area, in metres.`);
    if (mode === 'line' && r.length < 2) return this.error.set('Click both ends of the thing you measured on the photo.');
    if (L > 80) return this.error.set(`${L} m is very large: type the length in metres (for example 2.6, not 260).`);
    const reference = mode === 'line' ? { p1: r[0], p2: r[1], length_m: L } : { edge: mode, length_m: L };
    this.measuring.set(true);
    this.error.set('');
    try {
      this.area.set(await this.api.spaceArea({
        image_id: this.upload()!.image_id, selection: s.polygons, obstacles: this.obstaclesKept().map((o) => o.polygon),
        reference, height_m: mode === 'line' ? this.heightM() : null,
      }));
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.measuring.set(false);
    }
  }

  /* ================================================================ 2. sun */
  setAz(a: number): void {
    this.azimuth.set(((Math.round(a) % 360) + 360) % 360);
    this.azConfirmed.set(false);
    this.solar.set({});
  }

  confirmAz(): void {
    if (this.azimuth() == null) return this.error.set('Choose the direction the wall faces.');
    this.azConfirmed.set(true);
    this.error.set('');
    this.loadSun();
  }

  pickCity(name: string): void {
    const c = this.cities.find((x) => x.name === name);
    if (c) { this.city.set(c); this.solar.set({}); this.loadSun(); }
  }

  locate(): void {
    navigator.geolocation?.getCurrentPosition((p) => {
      this.city.set({ name: 'My location', lat: Math.round(p.coords.latitude * 100) / 100, lon: Math.round(p.coords.longitude * 100) / 100 });
      this.solar.set({});
      this.loadSun();
    }, () => this.error.set('Location unavailable: choose a city.'));
  }

  async loadSun(): Promise<void> {
    const az = this.azimuth();
    if (az == null || !this.azConfirmed()) return;
    const c = this.city();
    try {
      const [s, w] = await Promise.all([
        this.api.solarDay(az, c.lat, c.lon, '2026-06-21', 30), this.api.solarDay(az, c.lat, c.lon, '2026-12-21', 30),
      ]);
      this.solar.set({ summer: s, winter: w });
      const peak = s.beam_w_m2.indexOf(Math.max(...s.beam_w_m2));
      this.tIndex.set(peak > 0 ? peak : Math.floor(s.times.length / 2));
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  setSeason(s: 'summer' | 'winter'): void {
    const n = this.solar()[s]?.times.length ?? 1;
    this.season.set(s);
    this.tIndex.set(Math.min(this.tIndex(), n - 1));
  }

  /* ================================================================ 3. plants & culture */
  togglePlant(p: string): void {
    this.plants.update((l) => (l.includes(p) ? l.filter((x) => x !== p) : l.length >= 6 ? l : [...l, p]));
  }

  toggleStyle(s: string): void {
    if (!this.compare()) {
      this.styleSel.set([s]);
      return;
    }
    this.styleSel.update((l) => (l.includes(s) ? (l.length > 1 ? l.filter((x) => x !== s) : l) : [...l, s]));
  }

  setCompare(on: boolean): void {
    this.compare.set(on);
    if (!on) this.styleSel.set([this.styleSel()[0] ?? 'hybrid']);
  }

  async loadPatterns(): Promise<void> {
    if (Object.keys(this.patterns()).length) return;
    try {
      const list = await this.api.studioPatterns();
      this.patterns.set(Object.fromEntries(list.map((p) => [p.id, { svg: p.svg ? this.san.bypassSecurityTrustHtml(p.svg) : null, text: p.text }])));
    } catch { /* the names stay usable without drawings */ }
  }

  setPrice(k: 'frame' | 'screen' | 'pocket', v: string): void {
    const n = parseFloat(v);
    this.prices.update((p) => ({ ...p, [k]: isFinite(n) && n >= 0 ? n : null }));
  }

  /* ================================================================ 4. designs */
  async generate(): Promise<void> {
    if (!this.plants().length) return this.error.set('Choose at least one plant.');
    if (!this.styleSel().length) return this.error.set('Choose at least one cultural style.');
    const p = this.prices();
    const prices = p.frame != null && p.screen != null && p.pocket != null
      ? { frame_tnd_per_m: p.frame, screen_tnd_per_m2: p.screen, pocket_tnd: p.pocket } : null;
    this.generating.set(true);
    this.error.set('');
    this.genElapsed.set(0);
    this.timer = setInterval(() => this.genElapsed.update((s) => s + 1), 1000);
    this.step.set(3);
    try {
      const c = this.city();
      const r = await this.api.studioStyles({
        area: this.area(), plants: this.plants(), styles: this.styleSel(), facade_azimuth: this.azimuth()!,
        lat: c.lat, lon: c.lon, water_available_l_day: this.waterLimitOn() ? this.waterLimit() : null,
        greenery: this.greenery(), prices,
      });
      this.result.set(r);
      const ok = r.designs.filter((d) => !d.error);
      const best = ok.find((d) => d.fit === "suits this wall's sun" && d.optimisation?.feasible) ?? ok[0] ?? null;
      this.chosen.set(best);
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.generating.set(false);
      if (this.timer) clearInterval(this.timer);
    }
  }

  choose(d: GenDesign): void {
    if (d.error) return;
    this.chosen.set(d);
    this.preview.set(null);
  }

  /* ================================================================ 5. preview */
  /** One call: geometry layer + the photo-like render (CPU, ~2 s). `ai` adds the optional GPU pass. */
  async makePreview(ai = false): Promise<void> {
    const d = this.chosen();
    if (!d) return;
    if (!ai) this.step.set(4);
    (ai ? this.realisticBusy : this.previewing).set(true);
    this.error.set('');
    try {
      const r = await this.api.studioPreview({ image_id: this.upload()!.image_id, area: this.area(), design: d, realistic: true, ai });
      this.preview.set(r);
      this.layer.set(r.realistic_png_base64 ? 'realistic' : 'geometry');
      if (r.message) this.error.set(r.message);
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      (ai ? this.realisticBusy : this.previewing).set(false);
    }
  }

  layerSrc = computed(() => {
    const p = this.preview();
    switch (this.layer()) {
      case 'geometry': return this.png(p?.geometry_png_base64);
      case 'realistic': return this.png(p?.realistic_png_base64) ?? this.png(p?.geometry_png_base64);
      default: return this.photoUrl();
    }
  });

  openTwin(): void {
    const d = this.chosen();
    if (!d) return;
    const c = this.city();
    saveInstallation({
      design: d, context: { lat: c.lat, lon: c.lon, facade_azimuth: this.azimuth() ?? 270, city: c.name },
      plants: this.plants(), water_available_l_day: this.waterLimitOn() ? this.waterLimit() : (d.water?.summer_l_day ?? 6), saved_at: new Date().toISOString(),
    });
    this.router.navigate(['/dashboard']);
  }

  /** CSS transform that frames the installation (its quad on the photo) with a margin. */
  readonly zoomTf = computed(() => {
    const a = this.area(), u = this.upload();
    if (!this.zoom() || !a?.quad_px?.length || !u) return null;
    const xs = a.quad_px.map((p) => p[0] / u.width), ys = a.quad_px.map((p) => p[1] / u.height);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const z = Math.min(4, 0.86 / Math.max(x1 - x0, y1 - y0, 0.05));
    if (z < 1.15) return null;                                  // the area already fills the photo
    const clamp = (t: number) => Math.min(0, Math.max(1 / z - 1, t));
    const tx = clamp(0.5 / z - (x0 + x1) / 2), ty = clamp(0.5 / z - (y0 + y1) / 2);
    return { transform: `scale(${z.toFixed(3)}) translate(${(tx * 100).toFixed(2)}%, ${(ty * 100).toFixed(2)}%)`, z, tx };
  });

  /** The before/after split in photo coordinates: the slider works on the screen, the clip on the zoomed photo. */
  readonly stageSplit = computed(() => {
    const t = this.zoomTf(), f = this.split() / 100;
    return t ? Math.min(100, Math.max(0, (-t.tx + f / t.z) * 100)) : this.split();
  });

  perPlant(m: Record<string, number>): [string, number][] {
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }

  bottles(l: number): number {
    return Math.max(1, Math.round(l / 1.5));
  }

  isFit(d: GenDesign): boolean {
    return (d.fit ?? '').startsWith('suits');
  }

  pct(v: number | null | undefined, d = 0): string {
    return v == null ? '—' : `${(v * 100).toFixed(d)} %`;
  }
}
