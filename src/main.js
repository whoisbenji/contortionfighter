import { GameLoop }        from './engine/loop.js';
import { checkHit }        from './engine/collision.js';
import { getInputState, flushInput, wasPressed } from './input/keyboard.js';
import { createMotionBuffer }  from './input/motionBuffer.js';
import { createFighterInstance, updateFighter, applyHit }
  from './characters/characterBase.js';
import { Backbender }      from './characters/backbender.js';
import { createRound, updateRound, isFightActive, PHASE } from './game/round.js';
import { Renderer }        from './render/renderer.js';

const W = 640, H = 360;

// ─── Canvas ───────────────────────────────────────────────────────────────────
const canvas = document.getElementById('game');
canvas.width  = W;
canvas.height = H;

const renderer = new Renderer(canvas);

// ─── Game state ───────────────────────────────────────────────────────────────
let fighters, motionBufs, round, paused;

function initGame() {
  fighters = [
    createFighterInstance(Backbender, { id: 1, name: 'RED',  color: '#cc2020', x: 160, facing:  1 }),
    createFighterInstance(Backbender, { id: 2, name: 'BLUE', color: '#2050cc', x: 480, facing: -1 }),
  ];
  motionBufs = [createMotionBuffer(), createMotionBuffer()];
  round  = createRound();
  paused = false;
}

initGame();

// Prevent re-hitting on the same attack swing
const hitThisAttack = new Set();
let lastState = [null, null];

// ─── Update ───────────────────────────────────────────────────────────────────
function update() {
  const [f1, f2] = fighters;

  // System keys
  if (wasPressed('Escape'))   paused = !paused;
  if (wasPressed('Backquote')) renderer.showBoxes = !renderer.showBoxes;

  if (paused) { flushInput(); return; }

  // Auto-restart after result screen
  if (round.phase === PHASE.RESULT && round.phaseTimer <= 0) {
    initGame();
    flushInput();
    return;
  }

  const active = isFightActive(round);

  const in1 = active ? getInputState(1) : nullInput();
  const in2 = active ? getInputState(2) : nullInput();

  // Reset per-swing hit guard whenever a fighter changes state
  // (covers attack→idle, attack→cancel, attack→hitstun, etc.)
  for (let i = 0; i < 2; i++) {
    const f = fighters[i];
    if (f.state !== lastState[i]) {
      hitThisAttack.delete(f.id);
      lastState[i] = f.state;
    }
  }

  // Update fighters
  updateFighter(f1, in1, f2, motionBufs[0]);
  updateFighter(f2, in2, f1, motionBufs[1]);

  // Hit detection (only during FIGHT phase)
  if (active) {
    for (const [atk, def] of [[f1, f2], [f2, f1]]) {
      if (hitThisAttack.has(atk.id)) continue;
      const hit = checkHit(atk, def);
      if (hit) {
        applyHit(def, hit, atk);
        hitThisAttack.add(atk.id);
      }
    }
  }

  updateRound(round, fighters);
  flushInput();
}

// ─── Render ───────────────────────────────────────────────────────────────────
function render(alpha) {
  renderer.render(fighters, round, alpha);

  if (paused) {
    const ctx = renderer.ctx;
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    ctx.fillRect(0, 0, W, H);
    ctx.textAlign = 'center';
    ctx.font = 'bold 28px monospace';
    ctx.fillStyle = '#ffdd00';
    ctx.fillText('PAUSED', W / 2, H / 2);
    ctx.font = '12px monospace';
    ctx.fillStyle = '#aaa';
    ctx.fillText('ESC to resume', W / 2, H / 2 + 22);
  }
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
const loop = new GameLoop({ update, render });
loop.start();

function nullInput() {
  return {
    left:false, right:false, up:false, down:false,
    lp:false, mp:false, hp:false, lk:false, mk:false, hk:false,
    lpPressed:false, mpPressed:false, hpPressed:false,
    lkPressed:false, mkPressed:false, hkPressed:false,
    upPressed:false,
  };
}
