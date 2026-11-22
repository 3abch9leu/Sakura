import {
  AfterViewInit,
  Component,
  ElementRef,
  NgZone,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';

export type SiteKind = 'urban' | 'farm';

export interface Site {
  id: string;
  /** Project name shown on the card. */
  name: string;
  city: string;
  /** Urban sites are apartments and companies; farms are the green ones. */
  kind: SiteKind;
  category: string;
  /** Position on the stylised map (viewBox 0 0 600 760). */
  x: number;
  y: number;
  /** Apartment / building / farm footprint in m². */
  area: number;
  plants: number;
  /** Monthly electricity before and after the InBetween screen. */
  kwhBefore: number;
  kwhAfter: number;
  since: number;
  note: string;
}

/** Monthly energy use per square metre = monthly kWh ÷ size in m². */
const UNIT = 'kWh/m²·mo';

@Component({
  selector: 'app-tunisia-map',
  templateUrl: './tunisia-map.html',
  styleUrl: './tunisia-map.css',
})
export class TunisiaMapComponent implements AfterViewInit, OnDestroy {
  private readonly zone = inject(NgZone);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly unit = UNIT;

  /** Static, illustrative locations. Nothing here is fetched. */
  readonly sites: Site[] = [
    {
      id: 'tunis',
      name: 'Résidence Les Jasmins',
      city: 'Tunis',
      kind: 'urban',
      category: 'Apartment',
      x: 322,
      y: 150,
      area: 84,
      plants: 96,
      kwhBefore: 1520,
      kwhAfter: 940,
      since: 2024,
      note: 'West-facing block. A zellige-star screen took the afternoon sun off the façade.',
    },
    {
      id: 'bizerte',
      name: 'Ferme El Haouaria',
      city: 'Bizerte',
      kind: 'farm',
      category: 'Market farm',
      x: 272,
      y: 104,
      area: 3600,
      plants: 640,
      kwhBefore: 5400,
      kwhAfter: 3200,
      since: 2025,
      note: 'Cold-room pumps and irrigation ran on peaks. Shade cut the chiller load.',
    },
    {
      id: 'nabeul',
      name: 'Serre Cap Bon',
      city: 'Nabeul',
      kind: 'farm',
      category: 'Greenhouse',
      x: 368,
      y: 180,
      area: 2100,
      plants: 520,
      kwhBefore: 4200,
      kwhAfter: 2450,
      since: 2025,
      note: 'Lattice screens over the glass roof dropped fan and evaporative-cooling hours.',
    },
    {
      id: 'sousse',
      name: 'Immeuble Sidi Bou Ali',
      city: 'Sousse',
      kind: 'urban',
      category: 'Company offices',
      x: 388,
      y: 268,
      area: 420,
      plants: 310,
      kwhBefore: 7800,
      kwhAfter: 4600,
      since: 2025,
      note: 'Three floors of glass. The screen shades the glazing without losing daylight.',
    },
    {
      id: 'kairouan',
      name: 'Atelier Kairouan Textile',
      city: 'Kairouan',
      kind: 'urban',
      category: 'Company workshop',
      x: 300,
      y: 302,
      area: 260,
      plants: 190,
      kwhBefore: 4900,
      kwhAfter: 3000,
      since: 2024,
      note: 'A south-facing workshop roof. Passive shade replaced two split units.',
    },
    {
      id: 'sfax',
      name: 'Résidence Sfax Nord',
      city: 'Sfax',
      kind: 'urban',
      category: 'Apartment',
      x: 370,
      y: 394,
      area: 76,
      plants: 88,
      kwhBefore: 1390,
      kwhAfter: 870,
      since: 2025,
      note: 'Sea-facing balcony screen, with mint and basil fed by gravity.',
    },
    {
      id: 'sidi-bouzid',
      name: 'Ferme Sidi Bouzid',
      city: 'Sidi Bouzid',
      kind: 'farm',
      category: 'Olive & vegetable farm',
      x: 252,
      y: 384,
      area: 5200,
      plants: 880,
      kwhBefore: 6100,
      kwhAfter: 3600,
      since: 2024,
      note: 'Pumping and packing were the load. Screened stores held a steadier temperature.',
    },
    {
      id: 'djerba',
      name: 'Maison Houmt Souk',
      city: 'Djerba',
      kind: 'urban',
      category: 'Small hotel',
      x: 432,
      y: 508,
      area: 620,
      plants: 420,
      kwhBefore: 11200,
      kwhAfter: 7200,
      since: 2025,
      note: 'Whitewashed courtyard rooms. Screens cut cooling demand through the summer.',
    },
    {
      id: 'tozeur',
      name: 'Oasis Tozeur',
      city: 'Tozeur',
      kind: 'farm',
      category: 'Date palm oasis',
      x: 182,
      y: 566,
      area: 7400,
      plants: 960,
      kwhBefore: 7300,
      kwhAfter: 4300,
      since: 2024,
      note: 'Date storage and irrigation. The screen shades pumps and reduces run time.',
    },
    {
      id: 'medenine',
      name: 'Ferme Medenine Sud',
      city: 'Medenine',
      kind: 'farm',
      category: 'Livestock & fodder',
      x: 330,
      y: 556,
      area: 3000,
      plants: 700,
      kwhBefore: 4800,
      kwhAfter: 2900,
      since: 2025,
      note: 'Arid-site trial. Shaded pens and water towers brought fans down to a fraction.',
    },
  ];

  readonly active = signal<string | null>(null);
  readonly selected = computed(() => this.sites.find((s) => s.id === this.active()) ?? null);

  readonly totals = computed(() => {
    const n = this.sites.length;
    const plants = this.sites.reduce((sum, s) => sum + s.plants, 0);
    const saved = this.sites.reduce((sum, s) => sum + (s.kwhBefore - s.kwhAfter), 0);
    const drop = this.sites.reduce((sum, s) => sum + this.drop(s), 0) / n;
    return { n, plants, saved, drop: Math.round(drop) };
  });

  /* ---------- map shape ---------- */
  readonly coast =
    'M120 122C150 96 200 78 246 74L296 62C316 72 330 92 348 104L392 96L420 128C428 140 424 148 414 152' +
    'L384 162C368 166 362 176 368 190L392 214L404 262C410 300 414 336 410 372L404 412' +
    'C400 436 392 452 380 466L362 486L378 512L404 540L396 566L348 584' +
    'C310 600 280 618 258 642L232 686L196 706L150 704L120 688C104 668 96 640 98 612' +
    'L112 566L96 512L110 462L96 412L118 360L104 306L120 254L104 204L112 162Z';

  readonly graticule = [180, 260, 340, 420, 500, 580];

  /* ---------- decode ring ---------- */
  private readonly ringR = 26;
  readonly ring = 2 * Math.PI * this.ringR;
  readonly ringR_ = this.ringR;

  /* ---------- formatting ---------- */
  before(s: Site): number {
    return this.ratio(s.kwhBefore, s.area);
  }

  after(s: Site): number {
    return this.ratio(s.kwhAfter, s.area);
  }

  /** Percentage reduction, rounded. */
  drop(s: Site): number {
    return Math.round((1 - s.kwhAfter / s.kwhBefore) * 100);
  }

  /** Share of the "before" bar still left after the screen. */
  keep(s: Site): number {
    return Math.round((s.kwhAfter / s.kwhBefore) * 100);
  }

  ringOffset(s: Site): number {
    return this.ring * (1 - this.drop(s) / 100);
  }

  num(n: number): string {
    return n.toLocaleString('en-US');
  }

  /* ---------- interaction ---------- */
  pick(id: string): void {
    this.active.set(this.active() === id ? null : id);
  }

  close(): void {
    this.active.set(null);
  }

  onBackdrop(e: MouseEvent): void {
    if (e.target === e.currentTarget) this.close();
  }

  onKey(e: KeyboardEvent, s: Site): void {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      this.pick(s.id);
    }
  }

  /* ---------- ambient ---------- */
  private readonly onPointer = (e: PointerEvent) => {
    const el = this.host.nativeElement;
    el.style.setProperty('--sx', `${e.clientX}px`);
    el.style.setProperty('--sy', `${e.clientY}px`);
  };

  private observer: IntersectionObserver | null = null;

  ngAfterViewInit(): void {
    this.zone.runOutsideAngular(() => {
      window.addEventListener('pointermove', this.onPointer, { passive: true });
      this.observer = new IntersectionObserver(
        (entries) => {
          for (const en of entries) {
            if (en.isIntersecting) {
              en.target.classList.add('in');
              this.observer?.unobserve(en.target);
            }
          }
        },
        { threshold: 0.15, rootMargin: '0px 0px -6% 0px' },
      );
      this.host.nativeElement
        .querySelectorAll('[data-reveal]')
        .forEach((el) => this.observer?.observe(el));
    });
  }

  ngOnDestroy(): void {
    window.removeEventListener('pointermove', this.onPointer);
    this.observer?.disconnect();
  }

  private ratio(kwh: number, area: number): number {
    return Math.round((kwh / area) * 10) / 10;
  }
}
