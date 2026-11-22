import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Api, CameraPhoto, LeafResult } from '../api';
import { Twin3dComponent, TwinSun, TwinView } from '../twin/twin3d';
import {
  BranchStatus, Cell, GenDesign, PLANT_LABEL, SavedInstallation, SensorReading, SolarDay, WaterResponse, loadInstallation,
} from '../twin/types';

const LEVEL_KEY = 'inbetween.levels.v1';           // per-branch "last refill" for estimated levels
const SETTINGS_KEY = 'inbetween.water-settings.v1';

interface Refill { level: number; at: number }

@Component({
  selector: 'app-dashboard',
  imports: [DecimalPipe, RouterLink, Twin3dComponent],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.css',
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly api = inject(Api);
  readonly plantLabel = PLANT_LABEL;

  readonly install = signal<SavedInstallation | null>(null);
  readonly design = signal<GenDesign | null>(null);
  readonly isDemo = signal(false);
  readonly loadError = signal('');

  readonly view = signal<TwinView>('hydraulic');
  readonly channels = signal(true);
  readonly selectedCell = signal<number | null>(null);

  // sun
  readonly season = signal<'summer' | 'winter'>('summer');
  readonly solar = signal<Record<string, SolarDay>>({});
  readonly tIndex = signal(0);

  // water
  readonly water = signal<WaterResponse | null>(null);
  readonly waterError = signal('');
  readonly refills = signal<Record<number, Refill>>({});
  readonly settings = signal({ hours_to_refill: 48, safety_margin: 0.2, losses: 0.15, collector_m2: 0 });
  readonly sensorBranch = signal<number | null>(null);

  // sensors
  readonly simOn = signal(false);
  readonly simRaw = signal(620);
  readonly simTemp = signal(31);
  readonly reading = signal<SensorReading | null>(null);
  readonly history = signal<SensorReading[]>([]);

  // leaf health (team DeepLabV3 model, on demand)
  readonly leafBusy = signal(false);
  readonly leafError = signal('');
  readonly leafResults = signal<Record<number, LeafResult>>({});
  readonly leafView = signal<'overlay' | 'original'>('overlay');
  readonly camPhotos = signal<CameraPhoto[]>([]);
  readonly leafDrag = signal(false);
  readonly leaf = computed(() => {
    const id = this.selectedCell();
    return id != null ? this.leafResults()[id] ?? null : null;
  });

  private poll: ReturnType<typeof setInterval> | null = null;
  private simTimer: ReturnType<typeof setTimeout> | null = null;

  /* ---------------- derived ---------------- */
  readonly cell = computed<Cell | null>(() => {
    const id = this.selectedCell(), d = this.design();
    return id != null && d ? d.cells.find((c) => c.id === id) ?? null : null;
  });

  readonly statusById = computed(() => new Map((this.water()?.branches ?? []).map((b) => [b.id, b])));

  readonly selBranch = computed<BranchStatus | null>(() => {
    const c = this.cell();
    return c && c.branch != null ? this.statusById().get(c.branch) ?? null : null;
  });

  readonly levels = computed<Record<number, number>>(() =>
    Object.fromEntries((this.water()?.branches ?? []).map((b) => [b.id, b.level_frac])));

  readonly thresholds = computed<Record<number, number>>(() =>
    Object.fromEntries((this.water()?.branches ?? []).map((b) => [b.id, b.dynamic_threshold_frac])));

  readonly alerts = computed(() => {
    const out: { branch: number; level: string; title: string; text: string }[] = [];
    for (const b of this.water()?.branches ?? []) for (const a of b.alerts) out.push({ branch: b.id, ...a });
    const order: Record<string, number> = { critical: 0, warning: 1, info: 2 };
    return out.sort((a, b) => order[a.level] - order[b.level]);
  });

  readonly totals = computed(() => {
    const bs = this.water()?.branches ?? [];
    const cap = bs.reduce((s, b) => s + b.capacity_l, 0), rem = bs.reduce((s, b) => s + b.remaining_l, 0);
    const need = bs.reduce((s, b) => s + b.need_today_l, 0);
    const aut = bs.length ? Math.min(...bs.map((b) => b.autonomy_hours)) : 0;
    return { cap, rem, need, aut, n: bs.length };
  });

  readonly sunDay = computed(() => this.solar()[this.season()] ?? null);

  readonly twinSun = computed<TwinSun | null>(() => {
    const d = this.sunDay();
    if (!d || this.view() !== 'environment') return null;
    const i = Math.min(this.tIndex(), d.times.length - 1);
    const rel = ((d.sun_azimuth[i] - d.azimuth_facade + 540) % 360) - 180;
    return { elevation: d.sun_elevation[i], relAzimuth: rel, beam: d.beam_w_m2[i], index: i, season: this.season() };
  });

  /** Remaining litres of the focused branch over the next 72 h vs. its dynamic threshold (SVG 520 x 150). */
  readonly projection = computed(() => {
    const b = this.selBranch() ?? this.water()?.branches?.[0];
    if (!b) return null;
    const W = 520, H = 150, hours = 72;
    const x = (h: number) => 36 + (h / hours) * (W - 50);
    const y = (l: number) => H - 24 - (l / Math.max(b.capacity_l, 0.001)) * (H - 40);
    let left = b.remaining_l;
    const pts: string[] = [`M${x(0)} ${y(left)}`];
    for (let h = 1; h <= hours; h++) {
      const day = b.timeline[Math.min(b.timeline.length - 1, Math.floor((h - 1) / 24))];
      left = Math.max(0, left - (day?.net_l ?? 0) / 24);
      pts.push(`L${x(h).toFixed(1)} ${y(left).toFixed(1)}`);
    }
    const ty = y(b.dynamic_threshold_frac * b.capacity_l);
    return { d: pts.join(' '), ty, W, H, b, ticks: [0, 24, 48, 72].map((h) => ({ h, x: x(h) })),
             refill: x(Math.min(hours, this.settings().hours_to_refill)), cap: b.capacity_l, y0: y(0), y1: y(b.capacity_l) };
  });

  ngOnInit(): void {
    try {
      this.refills.set(JSON.parse(localStorage.getItem(LEVEL_KEY) ?? '{}'));
      this.settings.set({ ...this.settings(), ...JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? '{}') });
    } catch { /* ignore */ }
    this.load();
  }

  ngOnDestroy(): void {
    if (this.poll) clearInterval(this.poll);
    if (this.simTimer) clearTimeout(this.simTimer);
  }

  private async load(): Promise<void> {
    const saved = loadInstallation();
    try {
      if (saved) {
        this.install.set(saved);
        this.design.set(saved.design);
      } else {
        const d = await this.api.installationDemo();
        this.isDemo.set(true);
        this.design.set(d);
        this.install.set({ design: d, context: { lat: d.context!.lat, lon: d.context!.lon, facade_azimuth: d.context!.facade_azimuth, city: d.context!.city ?? 'Tunis' },
          plants: [...new Set(d.branches.flatMap((b) => b.plants))], water_available_l_day: 6, saved_at: '' });
      }
      this.sensorBranch.set(this.design()!.branches[0]?.id ?? null);
      await Promise.all([this.refresh(), this.loadSun()]);
      this.poll = setInterval(() => this.refresh(), 5000);
    } catch (e) {
      this.loadError.set((e as Error).message);
    }
  }

  private async loadSun(): Promise<void> {
    const c = this.install()!.context;
    try {
      const [s, w] = await Promise.all([
        this.api.solarDay(c.facade_azimuth, c.lat, c.lon, '2026-06-21', 30), this.api.solarDay(c.facade_azimuth, c.lat, c.lon, '2026-12-21', 30)]);
      this.solar.set({ summer: s, winter: w });
      const now = new Date();
      const hhmm = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
      const i = s.times.findIndex((t) => t >= hhmm);
      this.tIndex.set(i > 0 ? i : Math.floor(s.times.length / 2));
    } catch { /* sun view simply stays unavailable */ }
  }

  /** Estimated level of a branch without sensor: last refill minus the modelled consumption since. */
  private estimated(bid: number, needDay: number, cap: number): number {
    const r = this.refills()[bid];
    if (!r) return 0.7;
    const days = (Date.now() - r.at) / 86400000;
    return Math.max(0, Math.min(1, r.level - (needDay * days) / Math.max(cap, 1e-6)));
  }

  async refresh(): Promise<void> {
    const d = this.design(), inst = this.install();
    if (!d || !inst) return;
    const levels: Record<string, number> = {};
    for (const b of d.branches) levels[String(b.id)] = this.estimated(b.id, b.need_l_day, b.capacity_l);
    try {
      const s = await this.api.sensorsGet();
      this.reading.set(s.reading);
      this.history.set(s.history);
      const w = await this.api.waterStatus({ branches: d.branches, levels, sensor_branch: this.sensorBranch(),
        lat: inst.context.lat, lon: inst.context.lon, ...this.settings() });
      this.water.set(w);
      this.waterError.set('');
    } catch (e) {
      this.waterError.set((e as Error).message);
    }
  }

  /* ---------------- interactions ---------------- */
  onPick(id: number | null): void {
    this.selectedCell.set(id);
    this.leafError.set('');
    if (id != null && this.cell()?.role === 'plant') this.loadCamPhotos();
  }

  /* ---------------- leaf health ---------------- */
  async loadCamPhotos(): Promise<void> {
    try {
      this.camPhotos.set(await this.api.cameraPhotos(this.selectedCell()));
    } catch {
      this.camPhotos.set([]);
    }
  }

  async onLeafFile(e: Event): Promise<void> {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (f) await this.runLeaf(() => this.api.leafAnalyze(f, this.cell()?.plant ?? null, this.selectedCell()));
  }

  async onLeafDrop(e: DragEvent): Promise<void> {
    e.preventDefault();
    this.leafDrag.set(false);
    const f = e.dataTransfer?.files?.[0];
    if (f && f.type.startsWith('image/')) await this.runLeaf(() => this.api.leafAnalyze(f, this.cell()?.plant ?? null, this.selectedCell(), this.install()?.context ?? null));
  }

  async analyzeCamPhoto(p: CameraPhoto): Promise<void> {
    await this.runLeaf(() => this.api.leafAnalyzePhoto(p.id, this.cell()?.plant ?? null));
  }

  private async runLeaf(call: () => Promise<LeafResult>): Promise<void> {
    const id = this.selectedCell();
    if (id == null) return;
    this.leafBusy.set(true);
    this.leafError.set('');
    try {
      const r = await call();
      this.leafResults.update((m) => ({ ...m, [id]: r }));
      this.leafView.set('overlay');
    } catch (e) {
      this.leafError.set((e as Error).message);
    } finally {
      this.leafBusy.set(false);
    }
  }

  jpg(b64: string): string {
    return `data:image/jpeg;base64,${b64}`;
  }

  selectBranch(bid: number): void {
    const c = this.design()?.cells.find((x) => x.branch === bid && x.role === 'plant');
    if (c) this.onPick(c.id);
  }

  refilled(bid: number): void {
    this.refills.update((r) => ({ ...r, [bid]: { level: 1, at: Date.now() } }));
    localStorage.setItem(LEVEL_KEY, JSON.stringify(this.refills()));
    this.refresh();
  }

  setSetting(k: 'hours_to_refill' | 'safety_margin' | 'losses' | 'collector_m2', v: number): void {
    if (!isFinite(v) || v < 0) return;
    this.settings.update((s) => ({ ...s, [k]: v }));
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings()));
    this.refresh();
  }

  setSensorBranch(v: string): void {
    this.sensorBranch.set(v === '' ? null : +v);
    this.refresh();
  }

  /** Simulation = a potentiometer you move on screen. Values are sent as "simulated" and labelled everywhere. */
  toggleSim(): void {
    this.simOn.set(!this.simOn());
    if (this.simOn()) this.sendSim();
  }

  simInput(raw: number, temp: number): void {
    this.simRaw.set(raw);
    this.simTemp.set(temp);
    if (!this.simOn()) return;
    if (this.simTimer) clearTimeout(this.simTimer);
    this.simTimer = setTimeout(() => this.sendSim(), 180);
  }

  private async sendSim(): Promise<void> {
    try {
      await this.api.sensorsPost({ source: 'simulated', branch: this.sensorBranch(), level_raw: this.simRaw(), temp_c: this.simTemp(), humidity: 0.45 });
      await this.refresh();
    } catch (e) {
      this.waterError.set((e as Error).message);
    }
  }

  sensorAge(r: SensorReading | null): string {
    if (!r) return '';
    const s = Math.round(Date.now() / 1000 - r.ts);
    return s < 60 ? `${s} s ago` : `${Math.round(s / 60)} min ago`;
  }

  isSimulated(r: SensorReading | null): boolean {
    return !!r && r.source.toLowerCase().includes('simulated');
  }

  hours(h: number): string {
    if (h >= 96) return '4+ days';
    if (h >= 48) return `${(h / 24).toFixed(1)} days`;
    return `${Math.round(h)} h`;
  }

  plantsOf(b: BranchStatus): string {
    const counts: Record<string, number> = {};
    for (const p of b.plants) counts[p] = (counts[p] ?? 0) + 1;
    return Object.entries(counts).map(([p, n]) => `${n} ${PLANT_LABEL[p] ?? p}`).join(', ');
  }
}
