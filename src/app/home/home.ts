import {
  AfterViewInit,
  Component,
  ElementRef,
  NgZone,
  OnDestroy,
  ViewChild,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-home',
  imports: [RouterLink],
  templateUrl: './home.html',
  styleUrl: './home.css',
})
export class HomeComponent implements AfterViewInit, OnDestroy {
  private readonly zone = inject(NgZone);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  @ViewChild('hero', { static: true }) private heroRef!: ElementRef<HTMLElement>;
  @ViewChild('arch', { static: true }) private archRef!: ElementRef<HTMLElement>;
  @ViewChild('nav', { static: true }) private navRef!: ElementRef<HTMLElement>;
  @ViewChild('cmp', { static: true }) private cmpRef!: ElementRef<HTMLElement>;

  /* ---------- content ---------- */
  readonly letters = [...'Between'];
  readonly words = ['shades', 'waters', 'feeds', 'remembers'];
  readonly ribbon = ['Shade', 'Water', 'Food', 'Heritage', 'Computation', 'Tunisia', 'Japan', 'Passive'];
  readonly steps = [
    { n: '01', t: 'Capture', p: 'Photograph your window or balcony, then confirm its size and orientation.' },
    { n: '02', t: 'Choose', p: 'Pick a Tunisian motif, a Japanese one, or a constrained blend of both.' },
    { n: '03', t: 'Optimize', p: 'A multi-objective optimizer balances shade, water and plant needs. Trivial answers are rejected.' },
    { n: '04', t: 'Build', p: 'Export the cutting geometry, fabricate the screen and let gravity do the rest.' },
  ];
  readonly plants = [
    { x: 92, d: '0s' },
    { x: 200, d: '-1.6s' },
    { x: 308, d: '-3.1s' },
  ];
  readonly leafAngles = [-54, -27, 0, 27, 54];
  readonly leafD = 'M0 0C11-16 11-38 0-54C-11-38-11-16 0 0Z';

  /* ---------- geometry (generated, not hand-typed) ---------- */
  readonly star8 = this.star(50, 50, 40, 22, 8, -Math.PI / 2);
  readonly star8Dots = [[0, 0], [100, 0], [0, 100], [100, 100]];
  readonly hexStars = [[0, 0], [100, 0], [50, 86.6], [0, 173.2], [100, 173.2]].map(([x, y]) =>
    this.star(x, y, 40, 21, 6, 0),
  );
  readonly hexDots = [[50, 28.87], [0, 57.74], [100, 57.74], [0, 115.47], [100, 115.47], [50, 144.33]];
  readonly orbit8 = this.star(0, 0, 190, 118, 8, -Math.PI / 2);
  readonly orbit6 = this.star(0, 0, 170, 100, 6, 0);
  readonly mini8 = this.star(0, 0, 66, 36, 8, -Math.PI / 2);
  readonly mini6 = this.star(0, 0, 66, 35, 6, 0);

  /* ---------- blend slider ---------- */
  readonly pos = signal(50);
  private dragging = false;
  private touched = false;
  private swept = false;

  /* ---------- runtime ---------- */
  private raf = 0;
  private sweepRaf = 0;
  private destroyed = false;
  private reduced = false;
  private ptr = { x: 0, y: 0 };
  private lastPtr = -1e9;
  private cur = { x: 0.5, y: 0.3 };
  private observers: IntersectionObserver[] = [];

  private onPointer = (e: PointerEvent) => {
    this.ptr = { x: e.clientX, y: e.clientY };
    this.lastPtr = performance.now();
  };

  private onScroll = () => {
    const doc = document.documentElement;
    const max = doc.scrollHeight - window.innerHeight;
    const p = max > 0 ? Math.min(1, window.scrollY / max) : 0;
    this.host.nativeElement.style.setProperty('--p', p.toFixed(4));
    this.navRef.nativeElement.classList.toggle('scrolled', window.scrollY > 24);
  };

  private tick = (t: number) => {
    if (this.destroyed) return;
    const hero = this.heroRef.nativeElement;
    const arch = this.archRef.nativeElement;
    const hr = hero.getBoundingClientRect();

    if (hr.bottom > 0 && hr.top < window.innerHeight) {
      const idle = t - this.lastPtr > 2600;
      let tx: number;
      let ty: number;
      if (idle) {
        const a = this.reduced ? 0.6 : t / 6500;
        tx = 0.5 + 0.42 * Math.cos(a);
        ty = 0.28 + 0.14 * Math.sin(a * 1.3);
      } else {
        tx = (this.ptr.x - hr.left) / hr.width;
        ty = (this.ptr.y - hr.top) / hr.height;
      }
      this.cur.x += (tx - this.cur.x) * 0.07;
      this.cur.y += (ty - this.cur.y) * 0.07;

      const sx = hr.width * this.cur.x;
      const sy = hr.height * this.cur.y;
      hero.style.setProperty('--sx', `${sx.toFixed(1)}px`);
      hero.style.setProperty('--sy', `${sy.toFixed(1)}px`);

      const ar = arch.getBoundingClientRect();
      const mx = (hr.left + sx - ar.left) / ar.width;
      const my = (hr.top + sy - ar.top) / ar.height;
      const clamp = (v: number, m: number) => Math.max(-m, Math.min(m, v));
      arch.style.setProperty('--mx', `${(mx * 100).toFixed(1)}%`);
      arch.style.setProperty('--my', `${(my * 100).toFixed(1)}%`);
      arch.style.setProperty('--dx', clamp((0.5 - mx) * 44, 24).toFixed(2));
      arch.style.setProperty('--dy', clamp((0.5 - my) * 44, 24).toFixed(2));
    }
    this.raf = requestAnimationFrame(this.tick);
  };

  ngAfterViewInit(): void {
    this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    this.zone.runOutsideAngular(() => {
      window.addEventListener('pointermove', this.onPointer, { passive: true });
      window.addEventListener('scroll', this.onScroll, { passive: true });
      this.onScroll();
      this.raf = requestAnimationFrame(this.tick);

      const reveal = new IntersectionObserver(
        (entries) => {
          for (const en of entries) {
            if (en.isIntersecting) {
              en.target.classList.add('in');
              reveal.unobserve(en.target);
            }
          }
        },
        { threshold: 0.15, rootMargin: '0px 0px -8% 0px' },
      );
      this.host.nativeElement
        .querySelectorAll('[data-reveal]')
        .forEach((el) => reveal.observe(el));

      const sweep = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting) && !this.swept) {
            this.swept = true;
            this.sweep();
            sweep.disconnect();
          }
        },
        { threshold: 0.45 },
      );
      sweep.observe(this.cmpRef.nativeElement);

      this.observers.push(reveal, sweep);
    });
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    cancelAnimationFrame(this.sweepRaf);
    window.removeEventListener('pointermove', this.onPointer);
    window.removeEventListener('scroll', this.onScroll);
    this.observers.forEach((o) => o.disconnect());
  }

  /* ---------- slider interactions ---------- */
  startDrag(e: PointerEvent, el: HTMLElement): void {
    this.dragging = true;
    this.touched = true;
    el.setPointerCapture(e.pointerId);
    this.setPos(e, el);
  }

  moveDrag(e: PointerEvent, el: HTMLElement): void {
    if (this.dragging) this.setPos(e, el);
  }

  endDrag(): void {
    this.dragging = false;
  }

  onKey(e: KeyboardEvent): void {
    const step = e.shiftKey ? 10 : 4;
    const map: Record<string, number> = {
      ArrowLeft: this.pos() - step,
      ArrowRight: this.pos() + step,
      Home: 0,
      End: 100,
    };
    if (e.key in map) {
      e.preventDefault();
      this.touched = true;
      this.pos.set(Math.max(0, Math.min(100, map[e.key])));
    }
  }

  private setPos(e: PointerEvent, el: HTMLElement): void {
    const r = el.getBoundingClientRect();
    this.pos.set(Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100)));
  }

  private sweep(): void {
    if (this.reduced) return;
    const start = performance.now();
    const dur = 2600;
    const step = (now: number) => {
      if (this.destroyed || this.touched) return;
      const k = Math.min(1, (now - start) / dur);
      const v = 50 + Math.sin(k * Math.PI * 2) * 30;
      this.zone.run(() => this.pos.set(v));
      if (k < 1) this.sweepRaf = requestAnimationFrame(step);
    };
    this.sweepRaf = requestAnimationFrame(step);
  }

  /* ---------- helpers ---------- */
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