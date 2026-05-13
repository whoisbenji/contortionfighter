// Physics constants and integration helpers.
// All values are in pixels at internal 640x360 resolution.
// Per-character stats (walkSpeed, jumpHeight) come from characterDef.stats, not here.

export const GRAVITY     = 0.65;   // px per frame² applied to all fighters
export const FLOOR_Y     = 300;    // y-coordinate of the ground surface (bottom of fighters)
export const STAGE_LEFT  = 40;     // left wall (fighter centre x limit)
export const STAGE_RIGHT = 600;    // right wall

/**
 * Integrate velocity and position for one logic tick.
 * Mutates fighter.x, fighter.y, fighter.vx, fighter.vy, fighter.onGround.
 * stats: characterDef.stats (unused currently, reserved for per-char gravity modifiers)
 */
export function integratePhysics(fighter, stats) {  // eslint-disable-line no-unused-vars
  fighter.vy += GRAVITY;

  fighter.x += fighter.vx;
  fighter.y += fighter.vy;

  // Floor collision
  if (fighter.y >= FLOOR_Y) {
    fighter.y  = FLOOR_Y;
    fighter.vy = 0;
    fighter.onGround = true;
  } else {
    fighter.onGround = false;
  }

  // Stage walls (measured from fighter centre x)
  const hw = fighter.w / 2;
  if (fighter.x - hw < STAGE_LEFT) {
    fighter.x  = STAGE_LEFT + hw;
    fighter.vx = 0;
  }
  if (fighter.x + hw > STAGE_RIGHT) {
    fighter.x  = STAGE_RIGHT - hw;
    fighter.vx = 0;
  }
}
