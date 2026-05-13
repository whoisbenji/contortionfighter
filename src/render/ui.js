// HUD: health bars, round timer, announcements
import { PHASE, getTimeSeconds } from '../game/round.js';

const W = 640, H = 360;
const BAR_Y = 14;
const BAR_H = 18;
const BAR_W = 230;
const BAR_X1 = 20;          // P1 bar left edge
const BAR_X2 = W - BAR_X1 - BAR_W; // P2 bar left edge

export function drawUI(ctx, fighters, round) {
  drawHealthBars(ctx, fighters);
  drawTimer(ctx, round);
  drawAnnouncement(ctx, round);
}

function drawHealthBars(ctx, [f1, f2]) {
  // P1 bar (fills right from left)
  drawBar(ctx, BAR_X1, BAR_Y, BAR_W, BAR_H, f1.hp / f1.maxHp, '#e82020', '#ff6040', true);
  // P2 bar (fills left from right — mirrored)
  drawBar(ctx, BAR_X2, BAR_Y, BAR_W, BAR_H, f2.hp / f2.maxHp, '#2060e8', '#40a0ff', false);

  // Player labels
  ctx.font = 'bold 9px monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#fff';
  ctx.fillText('P1', BAR_X1, BAR_Y - 3);
  ctx.textAlign = 'right';
  ctx.fillText('P2', BAR_X2 + BAR_W, BAR_Y - 3);

  // Fighter names
  ctx.font = '7px monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = 'rgba(255,255,255,0.7)';
  ctx.fillText(f1.name.toUpperCase(), BAR_X1, BAR_Y + BAR_H + 8);
  ctx.textAlign = 'right';
  ctx.fillText(f2.name.toUpperCase(), BAR_X2 + BAR_W, BAR_Y + BAR_H + 8);
}

function drawBar(ctx, x, y, w, h, pct, darkColor, lightColor, leftAlign) {
  // Background
  ctx.fillStyle = '#111';
  ctx.fillRect(x, y, w, h);

  const fillW = Math.round(w * Math.max(0, pct));
  const fillX = leftAlign ? x : x + w - fillW;

  // Low-health warning flash
  const flash = pct < 0.25 && Math.floor(Date.now() / 200) % 2 === 0;
  ctx.fillStyle = flash ? '#ffcc00' : darkColor;
  ctx.fillRect(fillX, y, fillW, h);

  // Highlight stripe
  ctx.fillStyle = flash ? 'rgba(255,255,200,0.4)' : lightColor;
  ctx.fillRect(fillX, y + 2, fillW, 5);

  // Border
  ctx.strokeStyle = 'rgba(255,255,255,0.4)';
  ctx.lineWidth = 1;
  ctx.strokeRect(x, y, w, h);
}

function drawTimer(ctx, round) {
  const secs = getTimeSeconds(round);
  const urgent = secs <= 10;

  // Timer background box
  const bx = W / 2 - 20, by = 8, bw = 40, bh = 26;
  ctx.fillStyle = '#000';
  ctx.fillRect(bx, by, bw, bh);
  ctx.strokeStyle = urgent
    ? (Math.floor(Date.now() / 150) % 2 === 0 ? '#ff4040' : '#ff9900')
    : 'rgba(255,255,255,0.4)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(bx, by, bw, bh);

  ctx.textAlign = 'center';
  ctx.font = `bold ${urgent ? '20' : '18'}px monospace`;
  ctx.fillStyle = urgent ? '#ff4040' : '#ffffff';
  ctx.fillText(round.phase === PHASE.FIGHT ? String(secs).padStart(2, '0') : '--', W / 2, by + 20);
}

function drawAnnouncement(ctx, round) {
  ctx.textAlign = 'center';

  switch (round.phase) {
    case PHASE.INTRO: {
      // "ROUND X"
      const fade = Math.min(1, (180 - round.phaseTimer) / 20);
      const alpha = round.phaseTimer < 30 ? round.phaseTimer / 30 : fade;
      ctx.globalAlpha = alpha;
      drawBigText(ctx, `ROUND ${round.roundNumber}`, W / 2, H / 2 - 20, 32, '#ffdd00');
      if (round.phaseTimer < 120) {
        drawBigText(ctx, 'FIGHT!', W / 2, H / 2 + 20, 28, '#ff4040');
      }
      ctx.globalAlpha = 1;
      break;
    }
    case PHASE.KO:
    case PHASE.RESULT: {
      drawBigText(ctx, 'K.O.', W / 2, H / 2 - 10, 48, '#ffdd00');
      if (round.phase === PHASE.RESULT) {
        const msg = round.winner === 'draw' ? 'DRAW!' : `PLAYER ${round.winner} WINS!`;
        drawBigText(ctx, msg, W / 2, H / 2 + 38, 16, '#ffffff');
      }
      break;
    }
  }
}

function drawBigText(ctx, text, x, y, size, color) {
  ctx.font = `bold ${size}px monospace`;
  // Shadow / outline
  ctx.fillStyle = '#000';
  for (const [ox, oy] of [[-2,2],[2,2],[-2,-2],[2,-2]]) {
    ctx.fillText(text, x + ox, y + oy);
  }
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}
