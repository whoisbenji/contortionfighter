import { integratePhysics, JUMP_FORCE, WALK_SPEED, FLOOR_Y } from '../engine/physics.js';

export const STATE = {
  IDLE:      'IDLE',
  WALK_F:    'WALK_F',
  WALK_B:    'WALK_B',
  JUMP:      'JUMP',
  CROUCH:    'CROUCH',
  ATTACK_LP: 'ATTACK_LP',
  HITSTUN:   'HITSTUN',
  KO:        'KO',
};

// Duration in frames for timed states
const DURATION = {
  ATTACK_LP: 22,   // total active frames for light punch
  HITSTUN:   18,
};

// Attack active frames (frame window within the state where hitbox is live)
const LP_ACTIVE_START = 5;
const LP_ACTIVE_END   = 10;

// Default hurtbox covering standing body (local coords, bottom-centre origin)
const HURTBOX_STAND = { ox: 0, oy: 0, w: 28, h: 72 };
const HURTBOX_CROUCH = { ox: 0, oy: 30, w: 32, h: 42 };

/**
 * Create a new fighter instance.
 * config: { id, x, facing, color, name }
 */
export function createFighter(config) {
  return {
    id:      config.id,
    name:    config.name,
    color:   config.color,   // main body color string
    x:       config.x,
    y:       FLOOR_Y,
    prevX:   config.x,       // for interpolation
    prevY:   FLOOR_Y,
    vx:      0,
    vy:      0,
    w:       30,
    h:       72,
    facing:  config.facing,  // 1 = right, -1 = left
    state:   STATE.IDLE,
    stateTimer: 0,           // counts down from state duration
    hp:      1000,
    maxHp:   1000,
    onGround: true,
    hitboxes: [],            // active hitboxes this frame
    hurtboxes: [{ ...HURTBOX_STAND }],
    hitConfirmed: false,     // set true on frame a hit lands (cleared next tick)
    hitstunVx:  0,
    knockbackVx: 0,
  };
}

/**
 * Update one fighter for one logic tick.
 * input: result of getInputState(id)
 * opponent: the other fighter (used for facing update)
 */
export function updateFighter(fighter, input, opponent) {
  fighter.prevX = fighter.x;
  fighter.prevY = fighter.y;
  fighter.hitboxes = [];
  fighter.hitConfirmed = false;

  // Always face opponent (except during KO)
  if (fighter.state !== STATE.KO) {
    fighter.facing = opponent.x > fighter.x ? 1 : -1;
  }

  switch (fighter.state) {
    case STATE.IDLE:
    case STATE.WALK_F:
    case STATE.WALK_B:
      handleGroundMovement(fighter, input);
      break;

    case STATE.JUMP:
      handleAirMovement(fighter, input);
      // Land check
      if (fighter.onGround) {
        fighter.state = STATE.IDLE;
        fighter.vx = 0;
      }
      break;

    case STATE.CROUCH:
      handleCrouch(fighter, input);
      break;

    case STATE.ATTACK_LP:
      fighter.stateTimer--;
      activateLpHitbox(fighter);
      if (fighter.stateTimer <= 0) {
        fighter.state = STATE.IDLE;
      }
      break;

    case STATE.HITSTUN:
      fighter.stateTimer--;
      fighter.vx = fighter.hitstunVx;
      if (fighter.stateTimer <= 0) {
        fighter.state = STATE.IDLE;
        fighter.vx = 0;
      }
      break;

    case STATE.KO:
      // Slide to a stop
      fighter.vx *= 0.85;
      break;
  }

  // Update hurtboxes based on state
  if (fighter.state === STATE.CROUCH) {
    fighter.hurtboxes = [{ ...HURTBOX_CROUCH }];
  } else {
    fighter.hurtboxes = [{ ...HURTBOX_STAND }];
  }

  integratePhysics(fighter);
}

// ─── Private helpers ─────────────────────────────────────────────────────────

function handleGroundMovement(fighter, input) {
  if (!fighter.onGround) {
    fighter.state = STATE.JUMP;
    return;
  }

  // Attack takes priority
  if (input.lpPressed) {
    fighter.state = STATE.ATTACK_LP;
    fighter.stateTimer = DURATION.ATTACK_LP;
    fighter.vx = 0;
    return;
  }

  // Jump
  if (input.upPressed) {
    fighter.vy = JUMP_FORCE;
    fighter.onGround = false;
    fighter.state = STATE.JUMP;
    fighter.vx = (input.right ? 1 : input.left ? -1 : 0) * WALK_SPEED;
    return;
  }

  // Crouch
  if (input.down) {
    fighter.state = STATE.CROUCH;
    fighter.vx = 0;
    return;
  }

  // Walk — forward/back relative to facing direction
  if (input.right) {
    fighter.vx = WALK_SPEED;
    fighter.state = fighter.facing === 1 ? STATE.WALK_F : STATE.WALK_B;
  } else if (input.left) {
    fighter.vx = -WALK_SPEED;
    fighter.state = fighter.facing === -1 ? STATE.WALK_F : STATE.WALK_B;
  } else {
    fighter.vx = 0;
    fighter.state = STATE.IDLE;
  }
}

function handleAirMovement(fighter, input) {
  // Allow slight air drift, no state change mid-air
  if (input.right) fighter.vx = WALK_SPEED;
  else if (input.left) fighter.vx = -WALK_SPEED;
  else fighter.vx *= 0.85; // air friction
}

function handleCrouch(fighter, input) {
  if (!input.down) {
    fighter.state = STATE.IDLE;
  }
  fighter.vx = 0;
}

function activateLpHitbox(fighter) {
  const frame = DURATION.ATTACK_LP - fighter.stateTimer;
  if (frame >= LP_ACTIVE_START && frame <= LP_ACTIVE_END) {
    // Hitbox extends forward from the body centre
    fighter.hitboxes = [{
      ox: 22,   // forward offset from centre
      oy: 10,   // down from top of fighter
      w:  28,
      h:  24,
      damage:   80,
      hitstun:  DURATION.HITSTUN,
      knockback: 4.5,
    }];
  }
}

/**
 * Apply a hit to the defender.
 * hit: { data: { damage, hitstun, knockback } }
 * attacker: used for knockback direction
 */
export function applyHit(defender, hit, attacker) {
  if (defender.state === STATE.KO) return;

  defender.hp = Math.max(0, defender.hp - hit.data.damage);
  defender.state = STATE.HITSTUN;
  defender.stateTimer = hit.data.hitstun;
  // Knock away from attacker
  defender.hitstunVx = hit.data.knockback * attacker.facing;

  if (defender.hp <= 0) {
    defender.state = STATE.KO;
    defender.vx = hit.data.knockback * attacker.facing * 1.5;
    defender.vy = -5;
  }
}
