// Draws placeholder fighters: coloured rectangle body + stick-figure limbs.
// Limb poses are keyed by state name; attack poses interpolate over startup→active→recovery.
// Debug overlay (H key in Phase 1, now ` key) shows hitboxes, hurtboxes, state, frame data.

import { STATE, isAttackState, getMoveFromState, isAirState } from '../engine/stateMachine.js';
import { toWorldBox } from '../engine/collision.js';

const HITBOX_FILL    = 'rgba(255,  40,  40, 0.55)';
const HURTBOX_FILL   = 'rgba( 40, 120, 255, 0.45)';
const HITBOX_STROKE  = 'rgba(255,  80,  80, 0.95)';
const HURTBOX_STROKE = 'rgba( 80, 160, 255, 0.95)';

export function drawFighter(ctx, fighter, alpha, showBoxes) {
  const x = lerp(fighter.prevX, fighter.x, alpha);
  const y = lerp(fighter.prevY, fighter.y, alpha);

  ctx.save();
  ctx.translate(x, y);
  if (fighter.facing === -1) ctx.scale(-1, 1);

  drawBody(ctx, fighter);
  drawLimbs(ctx, fighter);

  ctx.restore();

  if (showBoxes) {
    drawBoxes(ctx, fighter, alpha);
    drawDebugText(ctx, fighter, alpha);
  }
}

// ─── Body ─────────────────────────────────────────────────────────────────────

function drawBody(ctx, fighter) {
  const w = fighter.w;
  const isCrouch = fighter.state === STATE.CROUCH;
  const isHit    = fighter.state === STATE.HITSTUN;
  const isKO     = fighter.state === STATE.KO;

  const bodyH = isCrouch ? fighter.h * 0.55 : fighter.h;
  const bodyY = -bodyH;

  // Drop shadow
  ctx.fillStyle = 'rgba(0,0,0,0.3)';
  ctx.beginPath();
  ctx.ellipse(0, -1, w * 0.6, 5, 0, 0, Math.PI * 2);
  ctx.fill();

  // Flash white on hitstun
  let color = fighter.color;
  if (isHit && Math.floor(Date.now() / 60) % 2 === 0) color = '#ffffff';

  ctx.fillStyle = color;
  ctx.fillRect(-w / 2, bodyY, w, bodyH);

  ctx.strokeStyle = 'rgba(0,0,0,0.6)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(-w / 2, bodyY, w, bodyH);

  // Highlight stripe
  ctx.fillStyle = 'rgba(255,255,255,0.15)';
  ctx.fillRect(-w / 2 + 2, bodyY + 4, w * 0.4, bodyH * 0.35);
}

// ─── Limbs ────────────────────────────────────────────────────────────────────

function drawLimbs(ctx, fighter) {
  ctx.strokeStyle = darken(fighter.color, 0.55);
  ctx.lineCap = 'round';

  const s = fighter.state;

  if      (s === STATE.IDLE)                       poseIdle(ctx, fighter);
  else if (s === STATE.WALK_F || s === STATE.WALK_B) poseWalk(ctx, fighter);
  else if (isAirState(s))                           poseJump(ctx, fighter);
  else if (s === STATE.CROUCH)                      poseCrouch(ctx, fighter);
  else if (s === STATE.HITSTUN)                     poseHitstun(ctx, fighter);
  else if (s === STATE.KO)                          poseKO(ctx, fighter);
  else if (isAttackState(s))                        poseAttack(ctx, fighter);
  else                                              poseIdle(ctx, fighter);
}

function poseIdle(ctx, f) {
  drawHead(ctx, f, 0, -f.h + 10);
  line(ctx, 0, -f.h + 22, 0, -f.h * 0.42);
  line(ctx, 0, -f.h + 28, 14, -f.h + 44);
  line(ctx, 0, -f.h + 28, -10, -f.h + 46);
  line(ctx, 0, -f.h * 0.42, 10, -16);
  line(ctx, 10, -16, 12, 0);
  line(ctx, 0, -f.h * 0.42, -8, -16);
  line(ctx, -8, -16, -10, 0);
}

function poseWalk(ctx, f) {
  const t = Date.now() / 120;
  const swing = Math.sin(t) * 12;
  drawHead(ctx, f, Math.sin(t) * 1, -f.h + 10);
  line(ctx, 0, -f.h + 22, 0, -f.h * 0.42);
  line(ctx, 0, -f.h + 28, 14 + swing, -f.h + 44);
  line(ctx, 0, -f.h + 28, -10 - swing, -f.h + 46);
  line(ctx, 0, -f.h * 0.42, 10 + swing, -16);
  line(ctx, 10 + swing, -16, 12 + swing * 0.5, 0);
  line(ctx, 0, -f.h * 0.42, -8 - swing, -16);
  line(ctx, -8 - swing, -16, -10 - swing * 0.5, 0);
}

function poseJump(ctx, f) {
  drawHead(ctx, f, 0, -f.h + 10);
  line(ctx, 0, -f.h + 22, 0, -f.h * 0.42);
  line(ctx, 0, -f.h + 28, 18, -f.h + 14);
  line(ctx, 0, -f.h + 28, -14, -f.h + 14);
  line(ctx, 0, -f.h * 0.42, 16, -28);
  line(ctx, 16, -28, 18, -14);
  line(ctx, 0, -f.h * 0.42, -14, -28);
  line(ctx, -14, -28, -16, -14);
}

function poseCrouch(ctx, f) {
  const ch = f.h * 0.55;
  drawHead(ctx, f, 0, -ch + 10);
  line(ctx, 0, -ch + 22, 0, -ch * 0.5);
  line(ctx, 0, -ch + 26, 16, -ch + 38);
  line(ctx, 0, -ch + 26, -12, -ch + 38);
  line(ctx, 0, -ch * 0.5, 20, -12);
  line(ctx, 20, -12, 22, 0);
  line(ctx, 0, -ch * 0.5, -16, -12);
  line(ctx, -16, -12, -18, 0);
}

function poseHitstun(ctx, f) {
  drawHead(ctx, f, -6, -f.h + 12);
  line(ctx, -4, -f.h + 22, -4, -f.h * 0.42);
  line(ctx, -4, -f.h + 28, -16, -f.h + 20);
  line(ctx, -4, -f.h + 28, -18, -f.h + 42);
  line(ctx, -4, -f.h * 0.42, -8, -20);
  line(ctx, -8, -20, -6, 0);
  line(ctx, -4, -f.h * 0.42, -18, -14);
  line(ctx, -18, -14, -20, 0);
}

function poseKO(ctx, f) {
  line(ctx, -20, -8, 20, -4, 5);
  drawHead(ctx, f, 22, -10);
  line(ctx, -5, -6, -24, -12);
  line(ctx, -24, -12, -28, 0);
  line(ctx, 5, -4, 25, -8);
}

// Attack pose — dispatches to a per-move pose if available, else generic
function poseAttack(ctx, f) {
  const moveName = getMoveFromState(f.state);
  const sf = f.stateFrame;
  const move = f.characterDef.moves[moveName];

  if (!move) { poseIdle(ctx, f); return; }

  // Determine animation phase: 0=startup, 1=active, 2=recovery
  const inActive = sf >= move.startup && sf < move.startup + move.active;
  const ext = inActive ? 1 : Math.min(sf / Math.max(move.startup, 1), 1);

  // For now: distinguish punch vs kick vs anti-air vs special by moveName
  if (moveName.includes('kick') || moveName === 'j_hk') {
    poseKick(ctx, f, moveName, ext, inActive);
  } else if (moveName === '2hp' || moveName === 'spine_spike') {
    poseAntiAir(ctx, f, ext, inActive);
  } else if (moveName === 'backbend_shot') {
    poseBackbendShot(ctx, f, ext, inActive);
  } else {
    posePunch(ctx, f, ext, inActive);
  }
}

function posePunch(ctx, f, ext, inActive) {
  drawHead(ctx, f, ext * 2, -f.h + 10);
  line(ctx, 0, -f.h + 22, 0, -f.h * 0.42);
  const punchX = 14 + ext * 22;
  const punchY = -f.h + 28 + ext * 8;
  line(ctx, 0, -f.h + 28, punchX, punchY, 4);
  line(ctx, 0, -f.h + 28, -8, -f.h + 38);
  line(ctx, 0, -f.h * 0.42, 12, -16);
  line(ctx, 12, -16, 14, 0);
  line(ctx, 0, -f.h * 0.42, -10, -16);
  line(ctx, -10, -16, -12, 0);
}

function poseKick(ctx, f, moveName, ext, inActive) {
  drawHead(ctx, f, 0, -f.h + 10);
  line(ctx, 0, -f.h + 22, 0, -f.h * 0.42);
  line(ctx, 0, -f.h + 28, -10, -f.h + 38);   // guard arm
  line(ctx, 0, -f.h + 28, 8, -f.h + 40);
  // Kick leg
  const ky = moveName.includes('heavy') ? -f.h * 0.1 : -f.h * 0.35;
  const kx = 10 + ext * 28;
  line(ctx, 0, -f.h * 0.42, kx * 0.5, ky + 10);
  line(ctx, kx * 0.5, ky + 10, kx, ky, 4);
  // Standing leg
  line(ctx, 0, -f.h * 0.42, -8, -16);
  line(ctx, -8, -16, -10, 0);
}

function poseAntiAir(ctx, f, ext, inActive) {
  // Chest-stand / anti-air: body leans back, striking upward
  const lean = ext * 10;
  drawHead(ctx, f, -lean, -f.h + 8 + lean * 0.3);
  line(ctx, -lean * 0.5, -f.h + 22, -lean, -f.h * 0.45 + lean);
  line(ctx, -lean, -f.h * 0.45 + lean, 12, -f.h * 0.7 - ext * 12, 4);  // striking arm up
  line(ctx, -lean, -f.h * 0.45 + lean, -14, -f.h + 44);
  line(ctx, 0, -f.h * 0.42, 10, -16);
  line(ctx, 10, -16, 12, 0);
  line(ctx, 0, -f.h * 0.42, -8, -16);
  line(ctx, -8, -16, -10, 0);
}

function poseBackbendShot(ctx, f, ext, inActive) {
  // Backbend: torso arches backwards
  const bend = ext * 18;
  drawHead(ctx, f, -bend * 0.6, -f.h + 14 + bend * 0.4);
  line(ctx, 0, -f.h + 22, -bend * 0.3, -f.h * 0.42 + bend * 0.5);
  line(ctx, -bend * 0.3, -f.h * 0.42 + bend * 0.5, 20, -f.h + 30);  // arm fires fwd
  line(ctx, -bend * 0.3, -f.h * 0.42 + bend * 0.5, -16, -f.h + 50);
  line(ctx, 0, -f.h * 0.42, 10, -16);
  line(ctx, 10, -16, 12, 0);
  line(ctx, 0, -f.h * 0.42, -8, -16);
  line(ctx, -8, -16, -10, 0);
}

function drawHead(ctx, f, ox, oy) {
  ctx.fillStyle = lighten(f.color, 0.25);
  ctx.strokeStyle = 'rgba(0,0,0,0.5)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.ellipse(ox, oy, 9, 11, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = '#000';
  ctx.fillRect(ox + 2, oy - 3, 2, 3);
  ctx.fillRect(ox + 6, oy - 3, 2, 3);
}

function line(ctx, x1, y1, x2, y2, w = 3) {
  ctx.lineWidth = w;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

// ─── Debug overlay ────────────────────────────────────────────────────────────

function drawBoxes(ctx, fighter, alpha) {
  const ix = lerp(fighter.prevX, fighter.x, alpha);
  const iy = lerp(fighter.prevY, fighter.y, alpha);
  const snap = { ...fighter, x: ix, y: iy };

  for (const hurt of fighter.hurtboxes) {
    const r = toWorldBox(hurt, snap);
    ctx.fillStyle = HURTBOX_FILL;
    ctx.fillRect(r.x, r.y, r.w, r.h);
    ctx.strokeStyle = HURTBOX_STROKE;
    ctx.lineWidth = 1;
    ctx.strokeRect(r.x, r.y, r.w, r.h);
  }
  for (const hb of fighter.hitboxes) {
    const r = toWorldBox(hb, snap);
    ctx.fillStyle = HITBOX_FILL;
    ctx.fillRect(r.x, r.y, r.w, r.h);
    ctx.strokeStyle = HITBOX_STROKE;
    ctx.lineWidth = 1;
    ctx.strokeRect(r.x, r.y, r.w, r.h);
  }
}

function drawDebugText(ctx, fighter, alpha) {
  const ix = lerp(fighter.prevX, fighter.x, alpha);
  const iy = lerp(fighter.prevY, fighter.y, alpha);

  const s = fighter.state;
  const sf = fighter.stateFrame;

  ctx.save();
  ctx.font = '6px monospace';
  ctx.textAlign = 'center';

  // State name
  let label = s;
  if (isAttackState(s)) {
    const moveName = getMoveFromState(s);
    const move = fighter.characterDef.moves[moveName];
    if (move) {
      const total = move.startup + move.active + move.recovery;
      let phase = 'startup';
      if (sf >= move.startup && sf < move.startup + move.active)  phase = 'ACTIVE';
      else if (sf >= move.startup + move.active)                   phase = 'recovery';
      label = `${moveName} [${sf}/${total}] ${phase}`;
    }
  }

  ctx.fillStyle = 'rgba(0,0,0,0.7)';
  ctx.fillRect(ix - 60, iy - fighter.h - 16, 120, 10);
  ctx.fillStyle = '#fff';
  ctx.fillText(label, ix, iy - fighter.h - 8);

  // Cancel window indicator — green flash when cancel is available
  if (fighter.canChainCancel || fighter.canSpecialCancel) {
    const cx = fighter.canSpecialCancel ? '#00ff88' : '#88ff00';
    ctx.fillStyle = cx;
    ctx.fillRect(ix - 60, iy - fighter.h - 5, 120, 3);
  }

  // Frame advantage display (shown for 60 frames after a hit)
  if (fighter.lastHitAdvantage !== null) {
    const adv = fighter.lastHitAdvantage;
    ctx.font = '7px monospace';
    ctx.fillStyle = adv >= 0 ? '#00ff44' : '#ff4444';
    ctx.fillText((adv >= 0 ? '+' : '') + adv, ix, iy - fighter.h - 20);
  }

  ctx.restore();
}

// ─── Colour helpers ───────────────────────────────────────────────────────────

function lerp(a, b, t) { return a + (b - a) * t; }

function lighten(hex, amt) { return shiftColor(hex,  amt); }
function darken (hex, amt) { return shiftColor(hex, -amt); }

function shiftColor(hex, amt) {
  const n = parseInt(hex.replace('#', ''), 16);
  const clamp = v => Math.max(0, Math.min(255, v));
  const r = clamp(((n >> 16) & 0xff) + Math.round(amt * 255));
  const g = clamp(((n >>  8) & 0xff) + Math.round(amt * 255));
  const b = clamp(( n        & 0xff) + Math.round(amt * 255));
  return `rgb(${r},${g},${b})`;
}
