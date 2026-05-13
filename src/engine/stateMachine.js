// State constants and helpers for the fighter state machine.
// Attack states are dynamically named 'ATK_<moveName>' — never hardcoded here.

export const STATE = {
  IDLE:       'IDLE',
  WALK_F:     'WALK_F',
  WALK_B:     'WALK_B',
  JUMP_N:     'JUMP_N',   // neutral jump
  JUMP_F:     'JUMP_F',   // forward jump
  JUMP_B:     'JUMP_B',   // back jump
  CROUCH:     'CROUCH',
  BLOCK_HIGH: 'BLOCK_HIGH',
  BLOCK_LOW:  'BLOCK_LOW',
  HITSTUN:    'HITSTUN',
  BLOCKSTUN:  'BLOCKSTUN',
  KNOCKDOWN:  'KNOCKDOWN',
  GETUP:      'GETUP',
  KO:         'KO',
};

export const attackState    = moveName => `ATK_${moveName}`;
export const isAttackState  = state   => typeof state === 'string' && state.startsWith('ATK_');
export const getMoveFromState = state => state.slice(4);  // strips 'ATK_'

export const isGroundState = s =>
  s === STATE.IDLE || s === STATE.WALK_F || s === STATE.WALK_B || s === STATE.CROUCH;

export const isAirState = s =>
  s === STATE.JUMP_N || s === STATE.JUMP_F || s === STATE.JUMP_B;

/** True if the fighter's current move has an invulnerability window covering the current frame. */
export function isInvulnerable(fighter) {
  if (!isAttackState(fighter.state)) return false;
  const move = fighter.characterDef.moves[getMoveFromState(fighter.state)];
  if (!move?.invulnFrames) return false;
  const [s, e] = move.invulnFrames;
  return fighter.stateFrame >= s && fighter.stateFrame <= e;
}

/** True if the fighter's facing direction should be locked (not auto-updated). */
export function isFacingLocked(state) {
  return state === STATE.KO || state === STATE.KNOCKDOWN || state === STATE.GETUP;
}
