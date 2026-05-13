// Master render pass: stage → fighters → UI → post-FX
// Uses an offscreen canvas so post-FX can sample the full frame.
import { drawStage }    from '../game/stage.js';
import { drawFighter }  from './fighterRenderer.js';
import { drawUI }       from './ui.js';
import { applyCRT }     from './postfx.js';

const W = 640, H = 360;

export class Renderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');

    // Offscreen buffer — everything draws here, then CRT pass composites on top
    this.offscreen = new OffscreenCanvas(W, H);
    this.offCtx    = this.offscreen.getContext('2d');

    this.showBoxes = false; // toggled by H key
  }

  render(fighters, round, alpha) {
    const ctx = this.offCtx;

    // Clear
    ctx.clearRect(0, 0, W, H);

    // Stage
    drawStage(ctx);

    // Fighters
    for (const f of fighters) {
      drawFighter(ctx, f, alpha, this.showBoxes);
    }

    // HUD
    drawUI(ctx, fighters, round);

    // Blit offscreen → display canvas
    this.ctx.clearRect(0, 0, W, H);
    this.ctx.drawImage(this.offscreen, 0, 0);

    // CRT post-FX drawn on top of display canvas
    applyCRT(this.ctx, this.offscreen, 1);
  }
}
