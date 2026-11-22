import { Component } from '@angular/core';

/**
 * Water quality screening (team branch water_monitoring): a self-contained analyzer (pH, turbidity, EC at 25 °C,
 * temperature, tank level) served as a static page and embedded here, so it adds nothing to the app bundle.
 */
@Component({
  selector: 'app-water-quality',
  template: `
    <header class="head">
      <div>
        <p class="eyebrow">Water quality</p>
        <h1>Is this water safe <em>for my plants?</em></h1>
        <p class="sub">Type or import readings (pH, turbidity, conductivity, temperature). The verdict follows FAO and WHO irrigation
          thresholds and the worst value decides. It is a screening for irrigation, not a drinking-water certificate.</p>
      </div>
      <a class="open" href="water-monitor/index.html" target="_blank" rel="noopener">Open full screen ↗</a>
    </header>
    <iframe src="water-monitor/index.html" title="Water quality analyzer" loading="lazy"></iframe>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; min-height: 100vh; background: #f5f1e8; font-family: 'Inter', system-ui, sans-serif; color: #292c25; }
    .head { display: flex; justify-content: space-between; align-items: end; gap: 20px; padding: 30px max(24px, 3vw) 16px; }
    .eyebrow { margin: 0 0 8px; font-size: .7rem; letter-spacing: .2em; text-transform: uppercase; color: #b77b59; }
    h1 { margin: 0 0 8px; font-family: 'Cormorant Garamond', Georgia, serif; font-size: clamp(2rem, 3.6vw, 2.9rem); font-weight: 500; line-height: 1.05; }
    h1 em { color: #414b30; }
    .sub { max-width: 46rem; margin: 0; color: #6a6d63; font-size: .92rem; line-height: 1.65; }
    .open { flex: none; font-size: .86rem; color: #414b30; text-decoration: underline; text-underline-offset: 3px; }
    iframe { flex: 1; width: 100%; min-height: 78vh; border: 0; border-top: 1px solid rgba(41, 44, 37, .13); background: #f6f1e8; }
    @media (max-width: 700px) { .head { flex-direction: column; align-items: start; } }
  `],
})
export class WaterQualityComponent {}
