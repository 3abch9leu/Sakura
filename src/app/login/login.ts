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
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

@Component({
  selector: 'app-login',
  imports: [ReactiveFormsModule],
  templateUrl: './login.html',
  styleUrl: './login.css',
})
export class LoginComponent implements AfterViewInit, OnDestroy {
  private readonly zone = inject(NgZone);
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);

  @ViewChild('panel', { static: true }) private panelRef!: ElementRef<HTMLElement>;
  @ViewChild('arch', { static: true }) private archRef!: ElementRef<HTMLElement>;

  /* ---------- form ---------- */
  readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(6)]],
  });

  readonly showPassword = signal(false);
  readonly privacy = signal(false);
  readonly shake = signal(false);

  get email() {
    return this.form.controls.email;
  }

  get password() {
    return this.form.controls.password;
  }

  onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.shake.set(true);
      setTimeout(() => this.shake.set(false), 500);
      return;
    }
    // No auth backend yet: go straight to the designer.
    this.router.navigate(['/design']);
  }

  /* ---------- decorative geometry ---------- */
  readonly star8 = this.star(50, 50, 40, 22, 8, -Math.PI / 2);
  readonly star8Dots = [[0, 0], [100, 0], [0, 100], [100, 100]];
  readonly orbit8 = this.star(0, 0, 190, 118, 8, -Math.PI / 2);
  readonly orbit6 = this.star(0, 0, 170, 100, 6, 0);
  readonly plants = [
    { x: 92, d: '0s' },
    { x: 200, d: '-1.6s' },
    { x: 308, d: '-3.1s' },
  ];
  readonly leafAngles = [-54, -27, 0, 27, 54];
  readonly leafD = 'M0 0C11-16 11-38 0-54C-11-38-11-16 0 0Z';

  /* ---------- sun runtime ---------- */
  private raf = 0;
  private destroyed = false;
  private reduced = false;
  private ptr = { x: 0, y: 0 };
  private lastPtr = -1e9;
  private cur = { x: 0.5, y: 0.35 };

  private onPointer = (e: PointerEvent) => {
    this.ptr = { x: e.clientX, y: e.clientY };
    this.lastPtr = performance.now();
  };

  private tick = (t: number) => {
    if (this.destroyed) return;
    const panel = this.panelRef.nativeElement;
    const arch = this.archRef.nativeElement;
    const pr = panel.getBoundingClientRect();

    if (pr.width > 0) {
      const idle = t - this.lastPtr > 2600;
      let tx: number;
      let ty: number;
      if (idle) {
        const a = this.reduced ? 0.6 : t / 6500;
        tx = 0.5 + 0.42 * Math.cos(a);
        ty = 0.28 + 0.14 * Math.sin(a * 1.3);
      } else {
        tx = (this.ptr.x - pr.left) / pr.width;
        ty = (this.ptr.y - pr.top) / pr.height;
      }
      this.cur.x += (tx - this.cur.x) * 0.07;
      this.cur.y += (ty - this.cur.y) * 0.07;

      const sx = pr.width * this.cur.x;
      const sy = pr.height * this.cur.y;
      panel.style.setProperty('--sx', `${sx.toFixed(1)}px`);
      panel.style.setProperty('--sy', `${sy.toFixed(1)}px`);

      const ar = arch.getBoundingClientRect();
      const mx = (pr.left + sx - ar.left) / ar.width;
      const my = (pr.top + sy - ar.top) / ar.height;
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
      this.raf = requestAnimationFrame(this.tick);
    });
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    window.removeEventListener('pointermove', this.onPointer);
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