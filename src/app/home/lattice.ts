import { AfterViewInit, Component, ElementRef, NgZone, OnDestroy, ViewChild, ViewEncapsulation, inject, signal } from '@angular/core';
import type { LatticeHandle } from './lattice-scene';

/**
 * Landing-page prototype: the INBETWEEN living lattice (asanoha triangular lattice, planting cells with water
 * compartments in their floor beams, gravity-fed hidden channels, shading inserts).
 * The scene and its data are loaded only when the section approaches the viewport.
 */
@Component({
  selector: 'app-lattice',
  templateUrl: './lattice.html',
  styleUrl: './lattice.css',
  encapsulation: ViewEncapsulation.None,   // the side panel is rendered by the scene (innerHTML)
})
export class LatticeComponent implements AfterViewInit, OnDestroy {
  @ViewChild('root', { static: true }) private rootRef!: ElementRef<HTMLElement>;
  private readonly zone = inject(NgZone);
  readonly state = signal<'idle' | 'loading' | 'ready' | 'error'>('idle');
  private handle?: LatticeHandle;
  private io?: IntersectionObserver;
  private destroyed = false;

  ngAfterViewInit(): void {
    const root = this.rootRef.nativeElement;
    this.io = new IntersectionObserver((es) => {
      const on = es.some((e) => e.isIntersecting);
      if (on && this.state() === 'idle') this.start();
      this.handle?.setVisible(on);
    }, { rootMargin: '250px' });
    this.io.observe(root);
  }

  private async start(): Promise<void> {
    this.state.set('loading');
    try {
      const [data, mod] = await Promise.all([
        fetch('data/lattice-model.json').then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        }),
        import('./lattice-scene'),
      ]);
      if (this.destroyed) return;
      // the render loop runs outside Angular: no change detection on every frame
      this.handle = await this.zone.runOutsideAngular(() => mod.mountLattice(this.rootRef.nativeElement, data));
      if (this.destroyed) this.handle.dispose();
      else this.state.set('ready');
    } catch {
      this.state.set('error');
    }
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.io?.disconnect();
    this.handle?.dispose();
  }
}
