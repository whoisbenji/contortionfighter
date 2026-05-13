import { GameLoop }        from './engine/loop.js';
import { checkHit, }       from './engine/collision.js';
import { getInputState, flushInput, wasPressed } from './input/keyboard.js';
import { createFighter, updateFighter, applyHit, STATE } from './game/fighter.js';
import { createRound, updateRound, isFightActive, PHASE } from './game/round.js';
import { Renderer }        from './render/renderer.js';

const W = 640, H = 360;

// ─── Canvas setup ─────────────────────────────────────────────────────────────
const canvas = document.getElementById('game');
canvas.width  = W;
canvas.height = H;

// ─── Game state ───────────────────────────────────────────────────────────────
const renderer = new Renderer(canvas);

let fighters, round, paused;

function initGame() {
  fighters = [
    createFighter({ id: 1, x: 160, facing: 1,  color: '#cc2020', name: 'RED' }),
    createFighter({ id: 2, x: 480, facing: -1, color: '#2050cc', name: 'BLUE' }),
  ];
  round   = createRound();
  paused  = false;
}

initGame();

// Track who was already hit this attack to prevent multi-hit on one swing
const hitThisAttack = new Set();
let lastAttackState = [null, null];

// ─── Update (fixed 60hz) ──────────────────────────────────────────────────────
function update() {
  const [f1, f2] = fighters;

  // System keys
  if (wasPressed('Escape')) paused = !paused;
  if (wasPressed('KeyH'))   renderer.showBoxes = !renderer.showBoxes;

  if (paused) { flushInput(); return; }

  // Auto-restart when result screen expires
  if (round.phase === PHASE.RESULT && round.phaseTimer <= 0) {
    initGame();
    flushInput();
    return;
  }

  const active = isFightActive(round);

  // Read inputs
  const in1 = active ? getInputState(1) : nullInput();
  const in2 = active ? getInputState(2) : nullInput();

  // Track attack-state changes to reset hit-set
  for (let i = 0; i < 2; i++) {
    const f = fighters[i];
    if (f.state !== lastAttackState[i]) {
      if (f.state !== STATE.ATTACK_LP) hitThisAttack.delete(f.id);
      lastAttackState[i] = f.state;
    }
  }

  // Update fighters
  updateFighter(f1, in1, f2);
  updateFighter(f2, in2, f1);

  // Hit detection — only during FIGHT phase
  if (active) {
    for (const [attacker, defender] of [[f1, f2], [f2, f1]]) {
      if (hitThisAttack.has(attacker.id)) continue;
      const hit = checkHit(attacker, defender);
      if (hit) {
        applyHit(defender, hit, attacker);
        hitThisAttack.add(attacker.id);
      }
    }
  }

  // Round update
  updateRound(round, fighters);

  flushInput();
}

// ─── Render (runs every animation frame) ─────────────────────────────────────
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

// ─── Start ────────────────────────────────────────────────────────────────────
const loop = new GameLoop({ update, render });
loop.start();

// ─── Helpers ──────────────────────────────────────────────────────────────────
function nullInput() {
  return { left:false, right:false, up:false, down:false,
           lp:false, mp:false, hp:false,
           lpPressed:false, mpPressed:false, hpPressed:false, upPressed:false };
}
