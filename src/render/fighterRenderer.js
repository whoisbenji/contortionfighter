// Draws placeholder fighters: coloured rectangle body + stick-figure limbs.
// Limb poses change per state to give visual feedback during development.
import { STATE } from '../game/fighter.js';
import { toWorldBox } from '../engine/collision.js';

// Palette
const COLORS = {
  hitbox:  'rgba(255, 40,  40,  0.55)',
  hurtbox: 'rgba(40,  120, 255, 0.45)',
  hitboxBorder:  'rgba(255, 80,  80,  0.9)',
  hurtboxBorder: 'rgba(80,  160, 255, 0.9)',
};

/**
 * Draw a single fighter.
 * alpha: interpolation factor for smooth render
 * showBoxes: hitbox/hurtbox debug overlay
 */
export function drawFighter(ctx, fighter, alpha, showBoxes) {
  // Interpolated position
  const x = lerp(fighter.prevX, fighter.x, alpha);
  const y = lerp(fighter.prevY, fighter.y, alpha);

  ctx.save();
  ctx.translate(x, y);
  if (fighter.facing === -1) ctx.scale(-1, 1); // flip when facing left

  drawBody(ctx, fighter);
  drawLimbs(ctx, fighter);

  ctx.restore();

  if (showBoxes) drawBoxes(ctx, fighter, alpha);
}

// ─── Body ─────────────────────────────────────────────────────────────────────

function drawBody(ctx, fighter) {
  const w = fighter.w, h = fighter.h;
  const isCrouch = fighter.state === STATE.CROUCH;
  const isHit    = fighter.state === STATE.HITSTUN;
  const isKO     = fighter.state === STATE.KO;

  const bodyH = isCrouch ? h * 0.55 : h;
  const bodyY = -bodyH;

  // Shadow / drop indicator
  ctx.fillStyle = 'rgba(0,0,0,0.3)';
  ctx.beginPath();
  ctx.ellipse(0, -1, w * 0.6, 5, 0, 0, Math.PI * 2);
  ctx.fill();

  // Body flash on hitstun
  let color = fighter.color;
  if (isHit && Math.floor(Date.now() / 60) % 2 === 0) color = '#ffffff';

  // Main body rectangle with rounded corners feel (just rect for now)
  ctx.fillStyle = color;
  ctx.fillRect(-w / 2, bodyY, w, bodyH);

  // Darker outline
  ctx.strokeStyle = 'rgba(0,0,0,0.6)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(-w / 2, bodyY, w, bodyH);

  // Highlight stripe on torso
  ctx.fillStyle = 'rgba(255,255,255,0.15)';
  ctx.fillRect(-w / 2 + 2, bodyY + 4, w * 0.4, bodyH * 0.35);
}

// ─── Limbs ────────────────────────────────────────────────────────────────────
// Coordinates are relative to fighter bottom-centre, y-up is negative.
// facing is already handled by ctx.scale(-1,1) at call site.

function drawLimbs(ctx, fighter) {
  ctx.strokeStyle = darken(fighter.color, 0.55);
  ctx.lineCap = 'round';

  switch (fighter.state) {
    case STATE.IDLE:       poseIdle(ctx, fighter);      break;
    case STATE.WALK_F:
    case STATE.WALK_B:     poseWalk(ctx, fighter);      break;
    case STATE.JUMP:       poseJump(ctx, fighter);      break;
    case STATE.CROUCH:     poseCrouch(ctx, fighter);    break;
    case STATE.ATTACK_LP:  poseAttackLP(ctx, fighter);  break;
    case STATE.HITSTUN:    poseHitstun(ctx, fighter);   break;
    case STATE.KO:         poseKO(ctx, fighter);        break;
    default:               poseIdle(ctx, fighter);
  }
}

function line(ctx, x1, y1, x2, y2, w = 3) {
  ctx.lineWidth = w;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

function poseIdle(ctx, f) {
  // Head
  drawHead(ctx, f, 0, -f.h + 10);
  // Torso
  line(ctx, 0, -f.h + 22, 0, -f.h * 0.42);
  // Arms down with slight bend
  line(ctx, 0, -f.h + 28, 14, -f.h + 44);
  line(ctx, 0, -f.h + 28, -10, -f.h + 46);
  // Legs
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
  // Arms swing
  line(ctx, 0, -f.h + 28, 14 + swing, -f.h + 44);
  line(ctx, 0, -f.h + 28, -10 - swing, -f.h + 46);
  // Legs swing
  line(ctx, 0, -f.h * 0.42, 10 + swing, -16);
  line(ctx, 10 + swing, -16, 12 + swing * 0.5, 0);
  line(ctx, 0, -f.h * 0.42, -8 - swing, -16);
  line(ctx, -8 - swing, -16, -10 - swing * 0.5, 0);
}

function poseJump(ctx, f) {
  drawHead(ctx, f, 0, -f.h + 10);
  line(ctx, 0, -f.h + 22, 0, -f.h * 0.42);
  // Arms raised
  line(ctx, 0, -f.h + 28, 18, -f.h + 14);
  line(ctx, 0, -f.h + 28, -14, -f.h + 14);
  // Legs tucked
  line(ctx, 0, -f.h * 0.42, 16, -28);
  line(ctx, 16, -28, 18, -14);
  line(ctx, 0, -f.h * 0.42, -14, -28);
  line(ctx, -14, -28, -16, -14);
}

function poseCrouch(ctx, f) {
  const ch = f.h * 0.55;
  drawHead(ctx, f, 0, -ch + 10);
  line(ctx, 0, -ch + 22, 0, -ch * 0.5);
  // Arms on knees
  line(ctx, 0, -ch + 26, 16, -ch + 38);
  line(ctx, 0, -ch + 26, -12, -ch + 38);
  // Crouched legs spread wide — hint of contortion
  line(ctx, 0, -ch * 0.5, 20, -12);
  line(ctx, 20, -12, 22, 0);
  line(ctx, 0, -ch * 0.5, -16, -12);
  line(ctx, -16, -12, -18, 0);
}

function poseAttackLP(ctx, f) {
  const frame = (Date.now() / 16) % 22;
  const ext = Math.min(frame / 5, 1); // extend 0→1
  drawHead(ctx, f, ext * 2, -f.h + 10);
  line(ctx, 0, -f.h + 22, 0, -f.h * 0.42);
  // Punching arm extended forward
  const punchX = 14 + ext * 22;
  const punchY = -f.h + 28 + ext * 8;
  line(ctx, 0, -f.h + 28, punchX, punchY, 4);
  // Other arm guard
  line(ctx, 0, -f.h + 28, -8, -f.h + 38);
  // Legs planted
  line(ctx, 0, -f.h * 0.42, 12, -16);
  line(ctx, 12, -16, 14, 0);
  line(ctx, 0, -f.h * 0.42, -10, -16);
  line(ctx, -10, -16, -12, 0);
}

function poseHitstun(ctx, f) {
  drawHead(ctx, f, -6, -f.h + 12);
  line(ctx, -4, -f.h + 22, -4, -f.h * 0.42);
  // Arms flailing back
  line(ctx, -4, -f.h + 28, -16, -f.h + 20);
  line(ctx, -4, -f.h + 28, -18, -f.h + 42);
  line(ctx, -4, -f.h * 0.42, -8, -20);
  line(ctx, -8, -20, -6, 0);
  line(ctx, -4, -f.h * 0.42, -18, -14);
  line(ctx, -18, -14, -20, 0);
}

function poseKO(ctx, f) {
  // Slumped on ground — lying pose
  line(ctx, -20, -8, 20, -4, 5);
  drawHead(ctx, f, 22, -10);
  line(ctx, -5, -6, -24, -12);
  line(ctx, -24, -12, -28, 0);
  line(ctx, 5, -4, 25, -8);
}

function drawHead(ctx, f, ox, oy) {
  ctx.fillStyle = lighten(f.color, 0.25);
  ctx.strokeStyle = 'rgba(0,0,0,0.5)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.ellipse(ox, oy, 9, 11, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  // eyes
  ctx.fillStyle = '#000';
  ctx.fillRect(ox + 2, oy - 3, 2, 3);
  ctx.fillRect(ox + 6, oy - 3, 2, 3);
}

// ─── Debug boxes ─────────────────────────────────────────────────────────────

function drawBoxes(ctx, fighter, alpha) {
  const ix = lerp(fighter.prevX, fighter.x, alpha);
  const iy = lerp(fighter.prevY, fighter.y, alpha);
  const fSnap = { ...fighter, x: ix, y: iy };

  for (const hurt of fighter.hurtboxes) {
    const r = toWorldBox(hurt, fSnap);
    ctx.fillStyle = COLORS.hurtbox;
    ctx.fillRect(r.x, r.y, r.w, r.h);
    ctx.strokeStyle = COLORS.hurtboxBorder;
    ctx.lineWidth = 1;
    ctx.strokeRect(r.x, r.y, r.w, r.h);
  }
  for (const hb of fighter.hitboxes) {
    const r = toWorldBox(hb, fSnap);
    ctx.fillStyle = COLORS.hitbox;
    ctx.fillRect(r.x, r.y, r.w, r.h);
    ctx.strokeStyle = COLORS.hitboxBorder;
    ctx.lineWidth = 1;
    ctx.strokeRect(r.x, r.y, r.w, r.h);
  }
}

// ─── Colour helpers ───────────────────────────────────────────────────────────

function lerp(a, b, t) { return a + (b - a) * t; }

function lighten(hex, amt) {
  return shiftColor(hex, amt);
}
function darken(hex, amt) {
  return shiftColor(hex, -amt);
}
function shiftColor(hex, amt) {
  const n = parseInt(hex.replace('#', ''), 16);
  const clamp = v => Math.max(0, Math.min(255, v));
  const r = clamp(((n >> 16) & 0xff) + Math.round(amt * 255));
  const g = clamp(((n >> 8)  & 0xff) + Math.round(amt * 255));
  const b = clamp(( n        & 0xff) + Math.round(amt * 255));
  return `rgb(${r},${g},${b})`;
}
