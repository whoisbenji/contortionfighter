// Fixed-timestep game loop.
// Logic runs at exactly 60hz regardless of display refresh rate.
// Render receives an interpolation factor (0..1) for smooth visuals.

const STEP_MS = 1000 / 60; // 16.667ms per logic tick

export class GameLoop {
  constructor({ update, render }) {
    this.update = update;   // (dt: number) => void  — dt always === STEP_MS
    this.render = render;   // (alpha: number) => void — alpha in [0,1]
    this._running = false;
    this._rafId = null;
    this._lastTime = null;
    this._accumulated = 0;
  }

  start() {
    this._running = true;
    this._lastTime = performance.now();
    this._rafId = requestAnimationFrame(this._tick.bind(this));
  }

  stop() {
    this._running = false;
    if (this._rafId) cancelAnimationFrame(this._rafId);
  }

  _tick(now) {
    if (!this._running) return;

    let elapsed = now - this._lastTime;
    this._lastTime = now;

    // Cap to avoid spiral-of-death on tab focus-restore
    if (elapsed > 200) elapsed = 200;

    this._accumulated += elapsed;

    while (this._accumulated >= STEP_MS) {
      this.update(STEP_MS);
      this._accumulated -= STEP_MS;
    }

    // alpha tells renderer how far we are between the last two logic frames
    const alpha = this._accumulated / STEP_MS;
    this.render(alpha);

    this._rafId = requestAnimationFrame(this._tick.bind(this));
  }
}
