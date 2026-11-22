import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Api, CameraPhoto, LeafResult } from '../api';
import { PLANT_LABEL, loadInstallation } from '../twin/types';

interface Check { at: number; plant: string | null; source: string; result: LeafResult }

/** Plant health: drop a leaf photo (or pick one from the plant camera) -> marked areas + a care plan. */
@Component({
  selector: 'app-plant-health',
  imports: [DecimalPipe, RouterLink],
  templateUrl: './plant-health.html',
  styleUrl: './plant-health.css',
})
export class PlantHealthComponent implements OnInit {
  private readonly api = inject(Api);
  readonly plantLabel = PLANT_LABEL;
  readonly plants = Object.keys(PLANT_LABEL);

  readonly plant = signal<string | null>(null);
  readonly useWeather = signal(true);
  readonly dragging = signal(false);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly view = signal<'marked' | 'photo'>('marked');
  readonly split = signal(50);
  readonly checks = signal<Check[]>([]);
  readonly current = computed(() => this.checks()[0] ?? null);
  readonly camPhotos = signal<CameraPhoto[]>([]);
  readonly camLoading = signal(false);

  /** Weather location: the saved installation, otherwise Tunis. Only rounded coordinates are sent. */
  private readonly loc = (() => {
    const i = loadInstallation();
    return i ? { lat: i.context.lat, lon: i.context.lon, name: i.context.city } : { lat: 36.81, lon: 10.18, name: 'Tunis' };
  })();
  readonly locName = this.loc.name;

  ngOnInit(): void {
    this.loadCamera();
  }

  async loadCamera(): Promise<void> {
    this.camLoading.set(true);
    try {
      this.camPhotos.set(await this.api.cameraPhotos(null));
    } catch {
      this.camPhotos.set([]);
    } finally {
      this.camLoading.set(false);
    }
  }

  onDragOver(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(true);
  }

  onDrop(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) this.analyzeFile(f);
  }

  onFile(e: Event): void {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (f) this.analyzeFile(f);
  }

  private async analyzeFile(f: File): Promise<void> {
    if (!f.type.startsWith('image/')) {
      this.error.set('Drop a photo (JPG or PNG) of one leaf.');
      return;
    }
    await this.run(() => this.api.leafAnalyze(f, this.plant(), null, this.useWeather() ? this.loc : null), f.name);
  }

  async analyzeCam(p: CameraPhoto): Promise<void> {
    await this.run(() => this.api.leafAnalyzePhoto(p.id, this.plant(), this.useWeather() ? this.loc : null), 'plant camera');
  }

  private async run(call: () => Promise<LeafResult>, source: string): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      const r = await call();
      this.checks.update((l) => [{ at: Date.now(), plant: this.plant(), source, result: r }, ...l].slice(0, 8));
      this.view.set('marked');
      this.split.set(50);
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  show(c: Check): void {
    this.checks.update((l) => [c, ...l.filter((x) => x !== c)]);
  }

  jpg(b64: string): string {
    return `data:image/jpeg;base64,${b64}`;
  }

  time(ts: number): string {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
}
