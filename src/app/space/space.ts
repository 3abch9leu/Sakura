import { Router, RouterLink } from '@angular/router';
import {
  AfterViewInit,
  Component,
  ElementRef,
  NgZone,
  OnDestroy,
  inject,
  output,
  signal,
} from '@angular/core';

type Setting = 'urban' | 'farm';

interface Win {
  x: number;
  y: number;
  lit: boolean;
  d: number;
}

interface Building {
  x: number;
  y: number;
  w: number;
  h: number;
  c: string;
  wins: Win[];
}

@Component({
  selector: 'app-space',
  imports: [RouterLink],
  templateUrl: './space.html',
  styleUrl: './space.css',
})
export class SpaceComponent implements AfterViewInit, OnDestroy {
  private readonly zone = inject(NgZone);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly router = inject(Router);

  /** Emits the chosen setting when the user continues (wire to the design page later). */
  readonly continued = output<Setting>();

  readonly selected = signal<Setting | null>(null);
  readonly shake = signal(false);
  readonly hint = signal(false);

  readonly options = [
    {
      id: 'urban' as Setting,
      num: '01',
      name: 'Urban resident',
      desc: 'An apartment, balcony or rooftop in the city. A screen that shades your window and grows herbs where space is tight.',
      tags: ['Balcony', 'Window', 'Rooftop'],
    },
    {
      id: 'farm' as Setting,
      num: '02',
      name: 'Farm resident',
      desc: 'A farmhouse, barn or garden plot on open land. Shade and gravity-fed water, tuned to the way you work the land.',
      tags: ['Farmhouse', 'Barn', 'Garden plot'],
    },
  ];

  /* ---------- decorative geometry ---------- */
  readonly star8 = this.star(50, 50, 40, 22, 8, -Math.PI / 2);
  readonly star8Dots = [[0, 0], [100, 0], [0, 100], [100, 100]];
  readonly hexStars = [[0, 0], [100, 0], [50, 86.6], [0, 173.2], [100, 173.2]].map(([x, y]) =>
    this.star(x, y, 40, 21, 6, 0),
  );
  readonly hexDots = [[50, 28.87], [0, 57.74], [100, 57.74], [0, 115.47], [100, 115.47], [50, 144.33]];
  readonly orbit8 = this.star(0, 0, 190, 118, 8, -Math.PI / 2);
  readonly orbit6 = this.star(0, 0, 170, 100, 6, 0);

  readonly leafD = 'M0 0C11-16 11-38 0-54C-11-38-11-16 0 0Z';

  /* ---------- urban scene data ---------- */
  readonly farCity = Array.from({ length: 12 }, (_, i) => ({
    x: i * 52 - 10,
    w: 44,
    h: 110 + ((i * 53) % 90),
  }));
  readonly buildings: Building[] = this.makeBuildings();

  /* ---------- farm scene data ---------- */
  readonly fieldPlants = this.makeField();

  /* ---------- falling leaves ---------- */
  readonly leaves = Array.from({ length: 9 }, (_, i) => ({
    left: (i * 11 + 7) % 100,
    delay: -(i * 2.7),
    dur: 15 + (i % 4) * 3,
    size: 16 + (i % 3) * 8,
    color: ['#4f8a55', '#6aa564', '#c4693f', '#3c7347'][i % 4],
  }));

  /* ---------- runtime ---------- */
  private cleanups: Array<() => void> = [];

  ngAfterViewInit(): void {
    this.zone.runOutsideAngular(() => {
      const hostEl = this.host.nativeElement;

      const onWindow = (e: PointerEvent) => {
        hostEl.style.setProperty('--gx', `${e.clientX}px`);
        hostEl.style.setProperty('--gy', `${e.clientY}px`);
      };
      window.addEventListener('pointermove', onWindow, { passive: true });
      this.cleanups.push(() => window.removeEventListener('pointermove', onWindow));

      hostEl.querySelectorAll<HTMLElement>('.card').forEach((card) => {
        const scene = card.querySelector<HTMLElement>('.scene');
        if (!scene) return;

        const move = (e: PointerEvent) => {
          const cr = card.getBoundingClientRect();
          const sr = scene.getBoundingClientRect();
          const sx = Math.max(0, Math.min(100, ((e.clientX - sr.left) / sr.width) * 100));
          const sy = Math.max(0, Math.min(70, ((e.clientY - sr.top) / sr.height) * 100));
          card.style.setProperty('--sx', `${sx.toFixed(1)}%`);
          card.style.setProperty('--sy', `${sy.toFixed(1)}%`);
          card.style.setProperty('--px', (((e.clientX - cr.left) / cr.width - 0.5) * 2).toFixed(3));
          card.style.setProperty('--py', (((e.clientY - cr.top) / cr.height - 0.5) * 2).toFixed(3));
        };
        const leave = () => {
          card.style.removeProperty('--sx');
          card.style.removeProperty('--sy');
          card.style.setProperty('--px', '0');
          card.style.setProperty('--py', '0');
        };

        card.addEventListener('pointermove', move, { passive: true });
        card.addEventListener('pointerleave', leave);
        this.cleanups.push(() => {
          card.removeEventListener('pointermove', move);
          card.removeEventListener('pointerleave', leave);
        });
      });
    });
  }

  ngOnDestroy(): void {
    this.cleanups.forEach((fn) => fn());
    this.cleanups = [];
  }

  /* ---------- actions ---------- */
  pick(id: Setting): void {
    this.selected.set(id);
    this.hint.set(false);
  }

  get selectedName(): string {
    return this.options.find((o) => o.id === this.selected())?.name ?? '';
  }

  next(): void {
    const s = this.selected();
    if (!s) {
      this.hint.set(true);
      this.shake.set(true);
      setTimeout(() => this.shake.set(false), 500);
      return;
    }
    this.continued.emit(s);
    // Urban -> design studio. Agro is an extension in development: same studio, with a note.
    this.router.navigate(s === 'farm' ? ['/design'] : ['/studio'], s === 'farm' ? { queryParams: { setting: 'farm' } } : {});
  }

  /* ---------- generators ---------- */
  private makeBuildings(): Building[] {
    const spec = [
      { x: 0, w: 78, h: 210, c: '#c98a62' },
      { x: 84, w: 64, h: 160, c: '#d9a37d' },
      { x: 154, w: 86, h: 250, c: '#b9714a' },
      { x: 246, w: 72, h: 190, c: '#d39a72' },
    ];
    return spec.map((b, bi) => {
      const cols = Math.floor((b.w - 14) / 16);
      const rows = Math.floor((b.h - 26) / 24);
      const offset = (b.w - cols * 16) / 2 + 3;
      const wins: Win[] = [];
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const k = bi * 31 + r * 7 + c * 13;
          wins.push({
            x: b.x + offset + c * 16,
            y: 380 - b.h + 16 + r * 24,
            lit: k % 5 < 2,
            d: ((k * 37) % 60) / 10,
          });
        }
      }
      return { ...b, y: 380 - b.h, wins };
    });
  }

  private makeField() {
    const out: { x: number; y: number; s: number; d: number }[] = [];
    for (let r = 0; r < 5; r++) {
      for (let i = 0; i < 12; i++) {
        out.push({
          x: ((i * 56 + r * 28) % 650) - 20,
          y: 322 + r * 13,
          s: 0.5 + r * 0.13,
          d: (i * 0.23 + r * 0.31) % 3,
        });
      }
    }
    return out;
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