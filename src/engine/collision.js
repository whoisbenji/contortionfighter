// AABB hit detection between hitboxes and hurtboxes.
// Boxes are defined relative to the fighter's bottom-centre origin.
// knockback is now a vector { x, y } — x is "away from attacker", y<0 = up (launcher).

/**
 * Returns true if two axis-aligned rects overlap.
 * Each rect: { x, y, w, h } in world space (top-left origin).
 */
export function rectsOverlap(a, b) {
  return (
    a.x < b.x + b.w &&
    a.x + a.w > b.x &&
    a.y < b.y + b.h &&
    a.y + a.h > b.y
  );
}

/**
 * Convert a fighter's local box definition to a world-space rect.
 * localBox: { ox, oy, w, h }  (ox/oy = offset from bottom-centre; ox flipped by facing)
 * fighter:  { x, y, facing, h }
 */
export function toWorldBox(localBox, fighter) {
  const worldOx = localBox.ox * fighter.facing;
  return {
    x: fighter.x + worldOx - localBox.w / 2,
    y: fighter.y - fighter.h + localBox.oy,
    w: localBox.w,
    h: localBox.h,
  };
}

/**
 * Check all active hitboxes from attacker against all hurtboxes of defender.
 * Returns the first overlapping pair as { hitbox, hurtbox, data }, or null.
 * data = the hitbox definition from the move (contains damage, hitstun, knockback, etc.)
 */
export function checkHit(attacker, defender) {
  for (const hb of attacker.hitboxes) {
    const worldHb = toWorldBox(hb, attacker);
    for (const hurt of defender.hurtboxes) {
      const worldHurt = toWorldBox(hurt, defender);
      if (rectsOverlap(worldHb, worldHurt)) {
        return { hitbox: worldHb, hurtbox: worldHurt, data: hb };
      }
    }
  }
  return null;
}
