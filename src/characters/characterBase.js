// Character runtime engine.
// createFighterInstance() builds the mutable runtime state from a pure-data character def.
// updateFighter() advances one logic frame.
// applyHit() applies hit or block outcome to a defender.
//
// Adding a new character: create one file in /characters/, call createFighterInstance() in main.js.
// No engine changes required.

import { integratePhysics, FLOOR_Y } from '../engine/physics.js';
import {
  STATE, attackState, isAttackState, getMoveFromState,
  isGroundState, isAirState, isFacingLocked,
} from '../engine/stateMachine.js';
import { recordInput } from '../input/motionBuffer.js';

export { STATE, attackState, isAttackState, getMoveFromState, isGroundState, isAirState };

// ─── Factory ──────────────────────────────────────────────────────────────────

/**
 * Create a mutable runtime fighter from a character definition.
 * config: { id, name, color, x, facing }
 */
export function createFighterInstance(characterDef, config) {
  const stats = characterDef.stats;
  return {
    // Identity
    characterDef,
    id:      config.id,
    name:    config.name,
    color:   config.color,

    // World position (bottom-centre origin)
    x:       config.x,
    y:       FLOOR_Y,
    prevX:   config.x,
    prevY:   FLOOR_Y,
    vx:      0,
    vy:      0,
    w:       stats.width,
    h:       stats.height,
    facing:  config.facing,
    onGround: true,

    // State machine
    state:       STATE.IDLE,
    stateFrame:  0,       // counts up from 0 on first frame of this state
    attackMove:  null,    // move name when in an ATK_ state

    // Combat
    hp:              stats.health,
    maxHp:           stats.health,
    hitstunDuration: 0,
    blockstunDuration: 0,

    // Per-frame computed (rebuilt every tick)
    hitboxes:  [],
    hurtboxes: [],

    // Cancel flags (set during active/recovery of an attack)
    canChainCancel:   false,
    canSpecialCancel: false,

    // For debug display
    lastHitAdvantage: null,   // frame advantage on last hit/block outcome
  };
}

// ─── Main update ──────────────────────────────────────────────────────────────

/**
 * Advance one fighter by one logic tick.
 * motionBuf: the fighter's own motion buffer (from motionBuffer.js)
 */
export function updateFighter(fighter, input, opponent, motionBuf) {
  fighter.prevX = fighter.x;
  fighter.prevY = fighter.y;
  fighter.hitboxes       = [];
  fighter.canChainCancel   = false;
  fighter.canSpecialCancel = false;

  // Auto-update facing toward opponent (locked during KO / knockdown)
  if (!isFacingLocked(fighter.state)) {
    fighter.facing = opponent.x > fighter.x ? 1 : -1;
  }

  // Record directional input for motion detection
  recordInput(motionBuf, input, fighter.facing);

  // Frame-count-based auto-transitions (runs at start of each frame)
  autoTransition(fighter);

  // State-specific logic
  const s = fighter.state;
  if (isGroundState(s)) {
    handleGround(fighter, input, motionBuf);
  } else if (isAirState(s)) {
    handleAir(fighter, input, motionBuf);
  } else if (s === STATE.HITSTUN) {
    fighter.vx *= 0.75;    // decay knockback velocity
  } else if (s === STATE.KO) {
    fighter.vx *= 0.85;
  } else if (isAttackState(s)) {
    handleAttack(fighter, input, motionBuf);
  }
  // BLOCK_HIGH, BLOCK_LOW, BLOCKSTUN, KNOCKDOWN, GETUP: passive (autoTransition handles end)

  // Compute this frame's hitboxes and hurtboxes
  fighter.hitboxes  = computeHitboxes(fighter);
  fighter.hurtboxes = computeHurtboxes(fighter);

  // Advance frame counter (after all logic — frame 0 is the first frame in this state)
  fighter.stateFrame++;

  // Physics integration
  integratePhysics(fighter, fighter.characterDef.stats);
}

// ─── Auto-transitions ─────────────────────────────────────────────────────────
// These fire at the START of each frame, before state logic, so the new state
// gets to run its handler in the same frame (e.g. you can act on landing frame).

function autoTransition(fighter) {
  const s = fighter.state;

  // Landing: air → ground
  if (isAirState(s) && fighter.onGround) {
    transitionTo(fighter, STATE.IDLE);
    fighter.vx = 0;
    return;
  }

  // Attack end
  if (isAttackState(s)) {
    const move = getMove(fighter);
    if (move) {
      const total = move.startup + move.active + move.recovery;
      if (fighter.stateFrame >= total) {
        transitionTo(fighter, STATE.IDLE);
        fighter.vx = 0;
      }
    }
    return;
  }

  // Hitstun end
  if (s === STATE.HITSTUN && fighter.stateFrame >= fighter.hitstunDuration) {
    transitionTo(fighter, fighter.onGround ? STATE.IDLE : STATE.JUMP_N);
    fighter.vx = 0;
    return;
  }

  // Blockstun end
  if (s === STATE.BLOCKSTUN && fighter.stateFrame >= fighter.blockstunDuration) {
    transitionTo(fighter, fighter.onGround ? STATE.IDLE : STATE.JUMP_N);
    fighter.vx = 0;
    return;
  }
}

// ─── State handlers ───────────────────────────────────────────────────────────

function handleGround(fighter, input, motionBuf) {
  if (fighter.state === STATE.CROUCH) {
    // Rise from crouch
    if (!input.down) {
      transitionTo(fighter, STATE.IDLE);
    } else {
      fighter.vx = 0;
      // Crouch attack checks (added step 4)
      if (input.lpPressed && tryStartAttack(fighter, '2lp'))  return;
      if (input.mkPressed && tryStartAttack(fighter, '2mk'))  return;
      if (input.hpPressed && tryStartAttack(fighter, '2hp'))  return;
      return;
    }
  }

  // --- Special moves (checked before normals) ---
  // (wired in step 6 — motion checks go here)

  // --- Normal attacks ---
  if (input.lpPressed && tryStartAttack(fighter, 'light_punch'))   return;
  if (input.mpPressed && tryStartAttack(fighter, 'medium_punch'))  return;
  if (input.hpPressed && tryStartAttack(fighter, 'heavy_punch'))   return;
  if (input.lkPressed && tryStartAttack(fighter, 'light_kick'))    return;
  if (input.mkPressed && tryStartAttack(fighter, 'medium_kick'))   return;
  if (input.hkPressed && tryStartAttack(fighter, 'heavy_kick'))    return;

  // --- Jump ---
  if (input.upPressed && fighter.onGround) {
    const dx = input.right ? 1 : input.left ? -1 : 0;
    fighter.vy = -fighter.characterDef.stats.jumpHeight;
    fighter.vx = dx * fighter.characterDef.stats.walkSpeed;
    if (dx === 0)                     transitionTo(fighter, STATE.JUMP_N);
    else if (dx === fighter.facing)   transitionTo(fighter, STATE.JUMP_F);
    else                              transitionTo(fighter, STATE.JUMP_B);
    return;
  }

  // --- Crouch ---
  if (input.down && !input.up) {
    if (fighter.state !== STATE.CROUCH) transitionTo(fighter, STATE.CROUCH);
    fighter.vx = 0;
    return;
  }

  // --- Walk ---
  const ws = fighter.characterDef.stats.walkSpeed;
  if (input.right && !input.left) {
    fighter.vx = ws;
    fighter.state = fighter.facing === 1 ? STATE.WALK_F : STATE.WALK_B;
  } else if (input.left && !input.right) {
    fighter.vx = -ws;
    fighter.state = fighter.facing === -1 ? STATE.WALK_F : STATE.WALK_B;
  } else {
    fighter.vx = 0;
    fighter.state = STATE.IDLE;
  }
}

function handleAir(fighter, input, motionBuf) {
  // Air drift
  const ws = fighter.characterDef.stats.walkSpeed;
  if (input.right)      fighter.vx = ws;
  else if (input.left)  fighter.vx = -ws;
  else                  fighter.vx *= 0.85;

  // Air attacks (wired in step 4)
  if (input.mpPressed && tryStartAttack(fighter, 'j_mp')) return;
  if (input.hkPressed && tryStartAttack(fighter, 'j_hk')) return;
}

function handleAttack(fighter, input, motionBuf) {
  const move = getMove(fighter);
  if (!move) return;

  const sf = fighter.stateFrame;

  // Update cancel flags
  if (move.cancelWindow) {
    const [cs, ce] = move.cancelWindow;
    const inWindow = sf >= cs && sf <= ce;
    fighter.canChainCancel   = inWindow && (move.chainCancelInto?.length   > 0);
    fighter.canSpecialCancel = inWindow && (move.specialCancelInto?.length > 0);
  }

  // Chain cancel into another normal (step 5)
  // Special cancel into special (step 6)

  // Ground attacks lock horizontal movement
  if (fighter.onGround) fighter.vx = 0;
}

// ─── Combat ───────────────────────────────────────────────────────────────────

/**
 * Apply a hit (or block) to a defender.
 * hit: result from collision.checkHit — contains hit.data (the hitbox definition)
 * attacker: used for knockback direction and advantage calculation
 */
export function applyHit(defender, hit, attacker) {
  if (defender.state === STATE.KO) return;

  const md = hit.data;  // move hitbox data: damage, hitstun, knockback, blockType, etc.

  // Blocking check — defender is blocking if in BLOCK_HIGH or BLOCK_LOW and the
  // block type matches (high=overhead must be blocked high, low must be blocked low, mid=either)
  const isBlocking = checkBlock(defender, md);

  if (isBlocking) {
    defender.blockstunDuration = md.blockstun ?? 12;
    transitionTo(defender, STATE.BLOCKSTUN);
    // Small push on block
    defender.vx = (md.knockback.x * 0.4) * attacker.facing;
    // Frame advantage = attacker recovery - defender blockstun (negative = defender's favour)
    const attackMove = getMove(attacker);
    if (attackMove) {
      const attackerRecovery = attackMove.recovery;
      const attackerFramesLeft = (attackMove.startup + attackMove.active + attackMove.recovery)
        - attacker.stateFrame;
      defender.lastHitAdvantage = -(attackerFramesLeft - defender.blockstunDuration);
    }
    return;
  }

  // Hit confirmed
  defender.hp = Math.max(0, defender.hp - md.damage);
  defender.hitstunDuration = md.hitstun ?? 18;
  transitionTo(defender, STATE.HITSTUN);

  // Knockback (x always pushes away from attacker, y for launchers)
  defender.vx = md.knockback.x * attacker.facing;
  defender.vy = md.knockback.y;

  if (defender.hp <= 0) {
    transitionTo(defender, STATE.KO);
    defender.vx = md.knockback.x * attacker.facing * 1.5;
    defender.vy = md.knockback.y - 4;
  }
}

// ─── Hitbox / hurtbox computation ────────────────────────────────────────────

export function computeHitboxes(fighter) {
  if (!isAttackState(fighter.state)) return [];

  const move = getMove(fighter);
  if (!move) return [];

  const { startup, active } = move;
  const sf = fighter.stateFrame;

  // Only live during active frames
  if (sf < startup || sf >= startup + active) return [];

  // Per-active-frame hitbox (if move defines multiple, index into them)
  const activeFrame = sf - startup;
  const hbDef = move.hitboxes[Math.min(activeFrame, move.hitboxes.length - 1)];
  return [{ ...hbDef }];
}

export function computeHurtboxes(fighter) {
  const def = fighter.characterDef;
  const s = fighter.state;

  // Choose base hurtbox set for current stance
  let boxes;
  if (s === STATE.CROUCH) {
    boxes = def.defaultHurtboxes.crouch;
  } else if (isAirState(s) || (isAttackState(s) && !fighter.onGround)) {
    boxes = def.defaultHurtboxes.air;
  } else {
    boxes = def.defaultHurtboxes.stand;
  }

  // Per-frame overrides from move data (contortion hurtbox changes — step 8)
  if (isAttackState(s)) {
    const move = getMove(fighter);
    if (move?.hurtboxOverrides) {
      const override = move.hurtboxOverrides[fighter.stateFrame];
      if (override) boxes = override;
    }
  }

  return boxes;
}

// ─── Private helpers ──────────────────────────────────────────────────────────

function transitionTo(fighter, newState) {
  fighter.state      = newState;
  fighter.stateFrame = 0;
  fighter.attackMove = isAttackState(newState) ? getMoveFromState(newState) : null;
}

function tryStartAttack(fighter, moveName) {
  const move = fighter.characterDef.moves[moveName];
  if (!move) return false;  // move not yet defined in character data

  // Air attacks only available in air; ground attacks only on ground
  const requiresAir = moveName.startsWith('j_');
  if (requiresAir && fighter.onGround)  return false;
  if (!requiresAir && !fighter.onGround) return false;

  transitionTo(fighter, attackState(moveName));
  if (fighter.onGround) fighter.vx = 0;
  return true;
}

function getMove(fighter) {
  const moveName = isAttackState(fighter.state) ? getMoveFromState(fighter.state) : fighter.attackMove;
  return moveName ? fighter.characterDef.moves[moveName] : null;
}

function checkBlock(defender, hitData) {
  if (defender.state !== STATE.BLOCK_HIGH && defender.state !== STATE.BLOCK_LOW) return false;
  const bt = hitData.blockType ?? 'mid';
  if (bt === 'mid') return true;
  if (bt === 'high' && defender.state === STATE.BLOCK_HIGH) return true;
  if (bt === 'low'  && defender.state === STATE.BLOCK_LOW)  return true;
  return false;
}
