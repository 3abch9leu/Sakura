import { AfterViewInit, Component, ElementRef, NgZone, OnDestroy, ViewChild, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LatticeComponent } from './lattice';

interface Feature {
  n: string;
  t: string;
  p: string;
  link?: string;
  query?: Record<string, string>;
  fragment?: string;
  cta?: string;
  status: 'live' | 'dev';
  icon: string;
  /** A real screenshot of the feature, and what it shows. */
  img: string;
  alt: string;
}

type App = 'urban' | 'agro';

@Component({
  selector: 'app-home',
  imports: [RouterLink, LatticeComponent],
  templateUrl: './home.html',
  styleUrl: './home.css',
})
export class HomeComponent implements AfterViewInit, OnDestroy {
  private readonly zone = inject(NgZone);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  @ViewChild('nav', { static: true }) private navRef!: ElementRef<HTMLElement>;
  @ViewChild('hero', { static: true }) private heroRef!: ElementRef<HTMLElement>;
  @ViewChild('film') private filmRef?: ElementRef<HTMLVideoElement>;

  readonly menuOpen = signal(false);
  readonly app = signal<App>('urban');
  readonly filmPlaying = signal(false);

  readonly headline = ['Making', 'room', 'for', 'life.'];

  /** The application's real services. "dev" ones are not built yet: no link, clearly tagged. */
  readonly features: Feature[] = [
    { n: '01', t: 'AI Design Studio', img: 'images/features/studio.jpg', alt: 'Before / after: a Tunisian × Japanese pattern previewed on a photo of a wall', status: 'live', link: '/studio', cta: 'Start a design',
      icon: 'M4 20l6-6m-2-6l8 8M14 4l6 6-8 8-6-6z',
      p: 'Upload a photo of any wall, balcony or façade, select the exact space, and compare cultural geometries fitted to it, with a before / after preview on your own photo.' },
    { n: '02', t: 'Solar Intelligence', img: 'images/features/solar.jpg', alt: 'Sun chart of a wall from sunrise to sunset, summer and winter', status: 'live', link: '/studio', cta: 'Analyse my wall',
      icon: 'M12 4v2m0 12v2m8-8h-2M6 12H4m13.7-5.7l-1.4 1.4M7.7 16.3l-1.4 1.4m0-11.4l1.4 1.4m8.6 8.6l1.4 1.4M12 8a4 4 0 100 8 4 4 0 000-8z',
      p: 'Sun from sunrise to sunset on your confirmed orientation, summer and winter, driving where plants go and how dense the geometry is.' },
    { n: '03', t: 'HydroEngine & HydroSafe', img: 'images/features/hydro.jpg', alt: '3D lattice prototype showing the water paths from the reservoir to each planting pocket', status: 'live', fragment: 'prototype', cta: 'See the water paths',
      icon: 'M12 3s6 7 6 11a6 6 0 01-12 0c0-4 6-11 6-11z',
      p: 'Gravity-fed irrigation sized channel by channel, with laminar-flow and drip-time checks.' },
    { n: '04', t: 'STEG Energy Companion', img: 'images/features/steg.jpg', alt: 'An STEG bill read line by line, each value explained and checked', status: 'live', link: '/energy', cta: 'Check my bill',
      icon: 'M13 3L5 14h6l-1 7 8-11h-6z',
      p: 'Your electricity bill read part by part and checked against the official STEG tariff.' },
    { n: '05', t: 'INBETWEEN Assistant', img: 'images/features/assistant.jpg', alt: 'The assistant answering a question about a bill in French', status: 'live', link: '/energy', cta: 'Ask a question',
      icon: 'M4 5h16v10H9l-5 4zM8 9h8M8 12h5',
      p: 'Answers in French, Arabic and Darija, using only checked numbers and official sources.' },
    { n: '06', t: 'Weather & Water Advisor', img: 'images/features/water.jpg', alt: 'Water level and dynamic refill threshold of each reservoir', status: 'live', link: '/dashboard', cta: 'Open the digital twin',
      icon: 'M7 17a4 4 0 010-8 5 5 0 019.6-1.5A3.5 3.5 0 1117 17zM9 20l-1 2m5-2l-1 2m5-2l-1 2',
      p: 'A transparent water budget per integrated reservoir: forecast heat, rain collection and your refill plan set a dynamic warning threshold.' },
    { n: '07', t: 'Arduino Smart Monitoring', img: 'images/features/arduino.jpg', alt: 'Arduino sensor readings with the LCD message and alert', status: 'live', link: '/dashboard', cta: 'See the sensors',
      icon: 'M4 5h16v11H4zM9 20h6M12 16v4M7 12l3-3 2 2 4-4',
      p: 'Level, temperature and humidity from the Arduino (or a clearly labelled simulation), with LCD and buzzer alerts.' },
    { n: '08', t: 'Plant Health Check', img: 'images/features/plants.jpg', alt: 'A diseased leaf photo with the damaged areas marked',
      status: 'live', link: '/plant-health', cta: 'Check a leaf',
      icon: 'M5 19c8 0 14-6 14-14C11 5 5 11 5 19zm0 0l7-7',
      p: 'Drop a leaf photo: the damaged areas are marked and you get a care plan for today and the week, adjusted to the weather forecast.' },
  ];

  /* ---------- generated geometry ---------- */
  readonly star8 = this.star(50, 50, 40, 22, 8, -Math.PI / 2);
  readonly star8Dots = [[0, 0], [100, 0], [0, 100], [100, 100]];
  /** Branching channels for the manifesto drawing: reservoir -> manifold -> pockets (all downhill). */
  readonly channels = this.channelPaths();

  private destroyed = false;
  private reduced = false;
  private observers: IntersectionObserver[] = [];
  private lightRaf = 0;
  private cur = { x: 0.18, y: 0.12 };
  private goal = { x: 0.18, y: 0.12 };
  private heroVisible = true;
  private ticking = false;

  private onScroll = () => {
    if (this.ticking) return;
    this.ticking = true;
    requestAnimationFrame(() => {
      this.ticking = false;
      const doc = document.documentElement;
      const max = doc.scrollHeight - window.innerHeight;
      const y = window.scrollY;
      const host = this.host.nativeElement;
      host.style.setProperty('--p', (max > 0 ? Math.min(1, y / max) : 0).toFixed(4));
      this.navRef.nativeElement.classList.toggle('scrolled', y > 40);
      if (this.heroVisible && !this.reduced) {
        this.heroRef.nativeElement.style.setProperty('--sy', Math.min(y, window.innerHeight).toFixed(1));
      }
    });
  };

  private onPointer = (e: PointerEvent) => {
    const r = this.heroRef.nativeElement.getBoundingClientRect();
    this.goal = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
    if (!this.lightRaf) this.lightRaf = requestAnimationFrame(this.light);
  };

  private onLeave = () => {
    this.goal = { x: 0.18, y: 0.12 };
    if (!this.lightRaf) this.lightRaf = requestAnimationFrame(this.light);
  };

  /** Slow interpolation toward the pointer: daylight drifts, it does not follow. Stops when settled. */
  private light = () => {
    this.lightRaf = 0;
    if (this.destroyed) return;
    const k = 0.045;
    this.cur.x += (this.goal.x - this.cur.x) * k;
    this.cur.y += (this.goal.y - this.cur.y) * k;
    const el = this.heroRef.nativeElement;
    el.style.setProperty('--lx', this.cur.x.toFixed(4));
    el.style.setProperty('--ly', this.cur.y.toFixed(4));
    if (Math.abs(this.goal.x - this.cur.x) + Math.abs(this.goal.y - this.cur.y) > 0.0008) {
      this.lightRaf = requestAnimationFrame(this.light);
    }
  };

  ngAfterViewInit(): void {
    this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const hero = this.heroRef.nativeElement;
    this.zone.runOutsideAngular(() => {
      window.addEventListener('scroll', this.onScroll, { passive: true });
      this.onScroll();
      if (finePointer && !this.reduced) {
        hero.classList.add('hero--live');
        hero.addEventListener('pointermove', this.onPointer, { passive: true });
        hero.addEventListener('pointerleave', this.onLeave, { passive: true });
      }
      const heroIo = new IntersectionObserver((es) => (this.heroVisible = es.some((e) => e.isIntersecting)));
      heroIo.observe(hero);

      const reveal = new IntersectionObserver((entries) => {
        for (const en of entries) {
          if (en.isIntersecting) {
            en.target.classList.add('in');
            reveal.unobserve(en.target);
          }
        }
      }, { threshold: 0.14, rootMargin: '0px 0px -6% 0px' });
      this.host.nativeElement.querySelectorAll('[data-reveal]').forEach((el) => reveal.observe(el));

      // looping decorations (droplets) only run while on screen
      const live = new IntersectionObserver((entries) => {
        for (const en of entries) {
          const on = en.isIntersecting && !this.reduced;
          en.target.classList.toggle('playing', on);
          const svg = en.target as SVGSVGElement;
          if (typeof svg.pauseAnimations === 'function') {
            if (on) svg.unpauseAnimations(); else svg.pauseAnimations();
          }
        }
      });
      this.host.nativeElement.querySelectorAll('[data-live]').forEach((el) => live.observe(el));
      // the film (24 MB) is only fetched and played while it is on screen; paused when scrolled away
      const film = this.filmRef?.nativeElement;
      if (film) {
        const filmIo = new IntersectionObserver((es) => {
          const on = es.some((e) => e.isIntersecting);
          if (on && !this.reduced && film.paused) void film.play().catch(() => this.filmPlaying.set(false));
          else if (!on && !film.paused) film.pause();
        }, { threshold: 0.35 });
        filmIo.observe(film);
        this.observers.push(filmIo);
      }
      this.observers.push(heroIo, reveal, live);
    });
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    cancelAnimationFrame(this.lightRaf);
    window.removeEventListener('scroll', this.onScroll);
    const hero = this.heroRef.nativeElement;
    hero.removeEventListener('pointermove', this.onPointer);
    hero.removeEventListener('pointerleave', this.onLeave);
    this.observers.forEach((o) => o.disconnect());
  }

  scrollTo(id: string): void {
    this.menuOpen.set(false);
    document.getElementById(id)?.scrollIntoView({ behavior: this.reduced ? 'auto' : 'smooth', block: 'start' });
  }

  setApp(a: App): void {
    this.app.set(a);
  }

  onAppKey(e: KeyboardEvent): void {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const next: App = this.app() === 'urban' ? 'agro' : 'urban';
      this.app.set(next);
      (this.host.nativeElement.querySelector(`#tab-${next}`) as HTMLElement | null)?.focus();
    }
  }

  playFilm(): void {
    const v = this.filmRef?.nativeElement;
    if (!v) return;
    if (v.paused) {
      void v.play().catch(() => this.filmPlaying.set(false));
    } else {
      v.pause();
    }
  }

  /* ---------- geometry helpers ---------- */
  private star(cx: number, cy: number, outer: number, inner: number, tips: number, start: number): string {
    const pts: string[] = [];
    for (let i = 0; i < tips * 2; i++) {
      const r = i % 2 === 0 ? outer : inner;
      const a = start + (i * Math.PI) / tips;
      pts.push(`${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`);
    }
    return pts.join(' ');
  }

  private channelPaths(): { main: string; branches: string[]; drops: string[]; pockets: number[][] } {
    // drawing space 420 x 520: reservoir at the top, a manifold, then branches falling to 5 pockets
    const xs = [70, 150, 230, 310, 390];
    const manY = 250;
    const tail = (x: number, i: number) => {
      const bend = manY + 40 + (i % 2) * 26;
      return `V${bend} C ${x} ${bend + 30}, ${x + (i % 2 ? -14 : 14)} ${bend + 50}, ${x} ${bend + 80} V 452`;
    };
    const branches = xs.map((x, i) => `M${x} ${manY} ${tail(x, i)}`);
    // a droplet's whole journey: down from the reservoir, along the manifold, down its branch
    const drops = xs.map((x, i) => `M230 6 V ${manY} H ${x} ${tail(x, i)}`);
    return {
      main: `M230 118 V 190 C 230 220, 230 236, 230 ${manY} M70 ${manY} H 390`,
      branches,
      drops,
      pockets: xs.map((x) => [x, 470]),
    };
  }
}
