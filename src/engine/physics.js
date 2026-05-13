// Physics constants and integration helpers.
// All values are in pixels at internal 640x360 resolution.

export const GRAVITY      = 0.65;   // px per frame² (applied each logic tick)
export const JUMP_FORCE   = -13.5;  // initial vy on jump
export const WALK_SPEED   = 3.2;    // px per frame horizontal walk
export const FLOOR_Y      = 300;    // y-coordinate of the ground surface
export const STAGE_LEFT   = 40;     // left wall
export const STAGE_RIGHT  = 600;    // right wall

/**
 * Integrate velocity and position for one logic tick.
 * Mutates fighter.x, fighter.y, fighter.vx, fighter.vy.
 */
export function integratePhysics(fighter) {
  // Gravity
  fighter.vy += GRAVITY;

  fighter.x += fighter.vx;
  fighter.y += fighter.vy;

  // Floor collision
  if (fighter.y >= FLOOR_Y) {
    fighter.y = FLOOR_Y;
    fighter.vy = 0;
    fighter.onGround = true;
  } else {
    fighter.onGround = false;
  }

  // Stage walls (using fighter half-width)
  const hw = fighter.w / 2;
  if (fighter.x - hw < STAGE_LEFT) {
    fighter.x = STAGE_LEFT + hw;
    fighter.vx = 0;
  }
  if (fighter.x + hw > STAGE_RIGHT) {
    fighter.x = STAGE_RIGHT - hw;
    fighter.vx = 0;
  }
}
