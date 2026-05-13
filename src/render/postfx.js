// CRT scanline overlay + chromatic aberration pass.
// Operates on the offscreen canvas by drawing on top of it.

const W = 640, H = 360;

// Pre-build scanline pattern into an OffscreenCanvas once
let _scanlinePattern = null;

function getScanlinePattern(ctx) {
  if (_scanlinePattern) return _scanlinePattern;

  const oc = new OffscreenCanvas(2, 4);
  const oc2 = oc.getContext('2d');
  // Transparent top half, dark bottom half — gives interlaced look
  oc2.fillStyle = 'rgba(0,0,0,0)';
  oc2.fillRect(0, 0, 2, 2);
  oc2.fillStyle = 'rgba(0,0,0,0.28)';
  oc2.fillRect(0, 2, 2, 2);

  _scanlinePattern = ctx.createPattern(oc, 'repeat');
  return _scanlinePattern;
}

/**
 * Apply CRT post-processing directly onto ctx.
 * Call LAST in the render pass.
 * aberrationOffset: how many pixels to shift R/B channels (default 1)
 */
export function applyCRT(ctx, offscreen, aberrationOffset = 1) {
  // ── Chromatic aberration ──────────────────────────────────────
  // Draw the whole frame twice with composite ops to shift red + blue channels
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.globalAlpha = 0.25;

  // Red channel shifted left
  ctx.filter = 'url(#red-channel)'; // fallback: just tint + offset
  ctx.drawImage(offscreen, -aberrationOffset, 0);

  // Blue channel shifted right — cheap approximation without filter API
  // We use a separate tinted draw with screen blend
  ctx.restore();

  // Real cheap aberration: draw the image twice at ±offset with colour tints
  applyAberration(ctx, offscreen, aberrationOffset);

  // ── Scanlines ────────────────────────────────────────────────
  const pattern = getScanlinePattern(ctx);
  ctx.fillStyle = pattern;
  ctx.fillRect(0, 0, W, H);

  // ── Vignette ─────────────────────────────────────────────────
  const vignette = ctx.createRadialGradient(W / 2, H / 2, H * 0.25, W / 2, H / 2, H * 0.75);
  vignette.addColorStop(0, 'rgba(0,0,0,0)');
  vignette.addColorStop(1, 'rgba(0,0,0,0.55)');
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, W, H);

  // ── Screen gloss (top highlight) ─────────────────────────────
  const gloss = ctx.createLinearGradient(0, 0, 0, H * 0.15);
  gloss.addColorStop(0, 'rgba(255,255,255,0.04)');
  gloss.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gloss;
  ctx.fillRect(0, 0, W, H);
}

function applyAberration(ctx, src, offset) {
  // Red: shift left, multiply red channel
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.globalAlpha = 0.07;
  // Tint canvas red by drawing with a red fill overlay + multiply
  // Simplest approach: draw image offset, then mask with colour
  ctx.drawImage(src, -offset, 0);
  ctx.fillStyle = '#ff0000';
  ctx.globalCompositeOperation = 'multiply';
  ctx.fillRect(0, 0, W, H);
  ctx.restore();

  // Blue: shift right
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.globalAlpha = 0.07;
  ctx.drawImage(src, offset, 0);
  ctx.fillStyle = '#0000ff';
  ctx.globalCompositeOperation = 'multiply';
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}
