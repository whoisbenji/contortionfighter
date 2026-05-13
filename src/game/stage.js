// Procedural stage: gradient sky, silhouette horizon, parallax layers, floor.
import { FLOOR_Y, STAGE_LEFT, STAGE_RIGHT } from '../engine/physics.js';

// Silhouette buildings on the horizon — defined as rectangles
const BUILDINGS = [
  { x: 30,  w: 45, h: 70 },
  { x: 85,  w: 30, h: 50 },
  { x: 125, w: 60, h: 90 },
  { x: 195, w: 25, h: 45 },
  { x: 230, w: 50, h: 75 },
  { x: 290, w: 35, h: 60 },
  { x: 340, w: 70, h: 100 },
  { x: 420, w: 40, h: 65 },
  { x: 470, w: 55, h: 80 },
  { x: 535, w: 30, h: 50 },
  { x: 575, w: 45, h: 70 },
];

// Crowd silhouette row — simple bumps
function drawCrowd(ctx) {
  ctx.fillStyle = '#1a0a2e';
  const y = FLOOR_Y - 10;
  for (let x = STAGE_LEFT; x < STAGE_RIGHT; x += 12) {
    const offset = Math.sin(x * 0.3) * 3;
    ctx.beginPath();
    ctx.ellipse(x, y + offset, 6, 8, 0, Math.PI, 0);
    ctx.fill();
  }
}

export function drawStage(ctx) {
  const W = 640, H = 360;

  // ── Sky gradient ──────────────────────────────────────────────
  const sky = ctx.createLinearGradient(0, 0, 0, FLOOR_Y);
  sky.addColorStop(0,    '#0d0030');
  sky.addColorStop(0.4,  '#2b0060');
  sky.addColorStop(0.75, '#7a1a8a');
  sky.addColorStop(1,    '#d45a00');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, FLOOR_Y);

  // ── Distant glow / sun ────────────────────────────────────────
  const sunGrad = ctx.createRadialGradient(320, FLOOR_Y - 20, 0, 320, FLOOR_Y - 20, 80);
  sunGrad.addColorStop(0,   'rgba(255,200,50,0.6)');
  sunGrad.addColorStop(0.5, 'rgba(255,80,0,0.2)');
  sunGrad.addColorStop(1,   'rgba(255,80,0,0)');
  ctx.fillStyle = sunGrad;
  ctx.fillRect(0, 0, W, FLOOR_Y);

  // ── Horizon silhouette buildings ──────────────────────────────
  ctx.fillStyle = '#12003a';
  const horizonY = FLOOR_Y - 30;
  for (const b of BUILDINGS) {
    ctx.fillRect(b.x, horizonY - b.h, b.w, b.h);
  }

  // Window lights on buildings (tiny dots)
  ctx.fillStyle = 'rgba(255,240,100,0.7)';
  for (const b of BUILDINGS) {
    for (let wy = horizonY - b.h + 8; wy < horizonY - 6; wy += 10) {
      for (let wx = b.x + 5; wx < b.x + b.w - 4; wx += 8) {
        if (Math.sin(wx * 13 + wy * 7) > 0.2) {
          ctx.fillRect(wx, wy, 2, 2);
        }
      }
    }
  }

  // ── Crowd row ─────────────────────────────────────────────────
  drawCrowd(ctx);

  // ── Floor ─────────────────────────────────────────────────────
  // Main floor surface
  const floorGrad = ctx.createLinearGradient(0, FLOOR_Y, 0, H);
  floorGrad.addColorStop(0, '#3a1a00');
  floorGrad.addColorStop(1, '#1a0800');
  ctx.fillStyle = floorGrad;
  ctx.fillRect(0, FLOOR_Y, W, H - FLOOR_Y);

  // Floor highlight stripe
  ctx.fillStyle = 'rgba(255,140,0,0.3)';
  ctx.fillRect(0, FLOOR_Y, W, 3);

  // Floor tiles (subtle)
  ctx.strokeStyle = 'rgba(255,100,0,0.15)';
  ctx.lineWidth = 1;
  for (let x = STAGE_LEFT; x <= STAGE_RIGHT; x += 40) {
    ctx.beginPath();
    ctx.moveTo(x, FLOOR_Y);
    ctx.lineTo(x, H);
    ctx.stroke();
  }
}
