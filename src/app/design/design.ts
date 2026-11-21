import { AfterViewInit, Component, ElementRef, NgZone, OnDestroy, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

type PatternId = 'tunisian' | 'japanese';
type LeafKind = 'std' | 'wide' | 'round' | 'needle';

interface Plant {
  id: string;
  name: string;
  latin: string;
  color: string;
  leaf: LeafKind;
  angles: number[];
  scale: number;
  berry?: boolean;
}

@Component({
  selector: 'app-design',
  imports: [ReactiveFormsModule],
  templateUrl: './design.html',
  styleUrl: './design.css',
})
export class DesignComponent implements AfterViewInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly zone = inject(NgZone);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /* ---------- roadmap ---------- */
  readonly steps = [
    { t: 'Your space', s: 'Photo & size' },
    { t: 'Design', s: 'Pattern & plants' },
    { t: 'Preview', s: 'AI-generated' },
  ];
  readonly step = signal(0);
  readonly shake = signal(false);

  /* ---------- step 1: space ---------- */
  readonly photo = signal<string | null>(null);
  readonly dragging = signal(false);
  readonly fileError = signal('');

  readonly form = this.fb.group({
    width: this.fb.control<number | null>(null, [Validators.required, Validators.min(0.3), Validators.max(20)]),
    height: this.fb.control<number | null>(null, [Validators.required, Validators.min(0.3), Validators.max(20)]),
    location: this.fb.nonNullable.control('', [Validators.required, Validators.minLength(2)]),
  });

  get width() { return this.form.controls.width; }
  get height() { return this.form.controls.height; }
  get location() { return this.form.controls.location; }

  /* ---------- step 2: design ---------- */
  readonly pattern = signal<PatternId | null>(null);
  readonly patternError = signal(false);
  readonly selectedPlants = signal<string[]>([]);

  readonly patterns = [
    { id: 'tunisian' as PatternId, name: 'Tunisian', note: 'Qallaline & zellige star' },
    { id: 'japanese' as PatternId, name: 'Japanese', note: 'Asanoha-inspired lattice' },
  ];

  readonly leaves: Record<LeafKind, string> = {
    std: 'M0 0C11-16 11-38 0-54C-11-38-11-16 0 0Z',
    wide: 'M0 0C17-14 17-34 0-46C-17-34-17-14 0 0Z',
    round: 'M0 0C15-6 17-26 0-36C-17-26-15-6 0 0Z',
    needle: 'M0 0C3-18 3-40 0-58C-3-40-3-18 0 0Z',
  };

  readonly plants: Plant[] = [
    { id: 'mint', name: 'Mint', latin: 'Mentha × piperita', color: '#4f9a5a', leaf: 'wide', angles: [-42, -14, 14, 42], scale: 1 },
    { id: 'basil', name: 'Basil', latin: 'Ocimum basilicum', color: '#3f8a4a', leaf: 'round', angles: [-50, -25, 0, 25, 50], scale: 1 },
    { id: 'rosemary', name: 'Rosemary', latin: 'Salvia rosmarinus', color: '#5a7f52', leaf: 'needle', angles: [-48, -32, -16, 0, 16, 32, 48], scale: 1 },
    { id: 'thyme', name: 'Thyme', latin: 'Thymus vulgaris', color: '#6b9a5c', leaf: 'round', angles: [-62, -40, -18, 4, 26, 48, 68], scale: 0.7 },
    { id: 'parsley', name: 'Parsley', latin: 'Petroselinum crispum', color: '#3d8a45', leaf: 'std', angles: [-46, -23, 0, 23, 46], scale: 1 },
    { id: 'strawberry', name: 'Strawberry', latin: 'Fragaria × ananassa', color: '#4a8f4f', leaf: 'wide', angles: [-48, -24, 0, 24, 48], scale: 0.9, berry: true },
  ];

  /* ---------- step 3: preview ---------- */
  readonly done = signal(false);
  readonly genStage = signal(0);
  readonly stages = ['Reading your space', 'Fitting the lattice', 'Placing your plants'];

  private timers: ReturnType<typeof setTimeout>[] = [];
  private destroyed = false;

  /* ---------- decorative geometry ---------- */
  readonly star8 = this.star(50, 50, 40, 22, 8, -Math.PI / 2);
  readonly star8Dots = [[0, 0], [100, 0], [0, 100], [100, 100]];
  readonly hexStars = [[0, 0], [100, 0], [50, 86.6], [0, 173.2], [100, 173.2]].map(([x, y]) =>
    this.star(x, y, 40, 21, 6, 0),
  );
  readonly hexDots = [[50, 28.87], [0, 57.74], [100, 57.74], [0, 115.47], [100, 115.47], [50, 144.33]];

  /* ---------- background sun ---------- */
  private onPointer = (e: PointerEvent) => {
    const el = this.host.nativeElement;
    el.style.setProperty('--sx', `${e.clientX}px`);
    el.style.setProperty('--sy', `${e.clientY}px`);
  };

  ngAfterViewInit(): void {
    this.zone.runOutsideAngular(() =>
      window.addEventListener('pointermove', this.onPointer, { passive: true }),
    );
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.clearTimers();
    window.removeEventListener('pointermove', this.onPointer);
  }

  /* ---------- navigation ---------- */
  next(): void {
    if (this.step() === 0) {
      if (this.form.invalid) {
        this.form.markAllAsTouched();
        this.bump();
        return;
      }
      this.step.set(1);
    } else if (this.step() === 1) {
      if (!this.pattern()) {
        this.patternError.set(true);
        this.bump();
        return;
      }
      this.step.set(2);
      this.generate();
    }
    this.scrollTop();
  }

  back(): void {
    if (this.step() > 0) {
      this.clearTimers();
      this.step.update((s) => s - 1);
      this.scrollTop();
    }
  }

  goTo(i: number): void {
    if (i < this.step()) {
      this.clearTimers();
      this.step.set(i);
      this.scrollTop();
    }
  }

  /* ---------- step 1 handlers ---------- */
  onFile(e: Event): void {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) this.read(f);
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

  removePhoto(input: HTMLInputElement): void {
    input.value = '';
    this.photo.set(null);
  }

  private read(f: File): void {
    if (!f.type.startsWith('image/')) {
      this.fileError.set('Please choose an image file.');
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      this.fileError.set('The image must be under 10 MB.');
      return;
    }
    this.fileError.set('');
    const r = new FileReader();
    r.onload = () => this.photo.set(r.result as string);
    r.readAsDataURL(f);
  }

  /* ---------- step 2 handlers ---------- */
  pickPattern(id: PatternId): void {
    this.pattern.set(id);
    this.patternError.set(false);
  }

  togglePlant(id: string): void {
    this.selectedPlants.update((list) => (list.includes(id) ? list.filter((p) => p !== id) : [...list, id]));
  }

  isSelected(id: string): boolean {
    return this.selectedPlants().includes(id);
  }

  /* ---------- step 3 helpers ---------- */
  get chosenPlants(): Plant[] {
    return this.plants.filter((p) => this.selectedPlants().includes(p.id));
  }

  get patternName(): string {
    return this.patterns.find((p) => p.id === this.pattern())?.name ?? '';
  }

  get ratio(): number {
    const w = this.width.value ?? 1;
    const h = this.height.value ?? 1;
    return Math.max(0.55, Math.min(1.9, w / h));
  }

  private generate(): void {
    this.clearTimers();
    this.done.set(false);
    this.genStage.set(0);
    this.timers.push(
      setTimeout(() => this.genStage.set(1), 1200),
      setTimeout(() => this.genStage.set(2), 2400),
      setTimeout(() => this.done.set(true), 3600),
    );
  }

  private clearTimers(): void {
    this.timers.forEach(clearTimeout);
    this.timers = [];
  }

  private bump(): void {
    this.shake.set(true);
    setTimeout(() => !this.destroyed && this.shake.set(false), 500);
  }

  private scrollTop(): void {
    window.scrollTo({ top: 0, behavior: 'smooth' });
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