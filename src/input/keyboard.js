// Raw keyboard state + per-frame edge detection.
// getInputState(playerId) returns a plain object that the fighter state machine
// consumes — the same shape the AI controller will produce in Phase 5.

const held = new Set();
const justPressed = new Set();
const justReleased = new Set();

// Key bindings per player id (1 or 2)
const BINDINGS = {
  1: { left: 'KeyA', right: 'KeyD', up: 'KeyW', down: 'KeyS',
       lp: 'KeyF', mp: 'KeyG', hp: 'KeyH' },
  2: { left: 'ArrowLeft', right: 'ArrowRight', up: 'ArrowUp', down: 'ArrowDown',
       lp: 'KeyJ', mp: 'KeyK', hp: 'KeyL' },
};

window.addEventListener('keydown', (e) => {
  if (!held.has(e.code)) justPressed.add(e.code);
  held.add(e.code);
});

window.addEventListener('keyup', (e) => {
  held.delete(e.code);
  justReleased.add(e.code);
});

/** Call once per logic frame to clear edge-detection sets. */
export function flushInput() {
  justPressed.clear();
  justReleased.clear();
}

/**
 * Returns current input state for a player.
 * { left, right, up, down, lp, mp, hp,
 *   lpPressed, mpPressed, hpPressed }  — *Pressed = true only on the frame the key went down
 */
export function getInputState(playerId) {
  const b = BINDINGS[playerId];
  return {
    left:      held.has(b.left),
    right:     held.has(b.right),
    up:        held.has(b.up),
    down:      held.has(b.down),
    lp:        held.has(b.lp),
    mp:        held.has(b.mp),
    hp:        held.has(b.hp),
    lpPressed: justPressed.has(b.lp),
    mpPressed: justPressed.has(b.mp),
    hpPressed: justPressed.has(b.hp),
    upPressed: justPressed.has(b.up),
  };
}

/** True if a raw key code was just pressed this frame (for system keys). */
export function wasPressed(code) {
  return justPressed.has(code);
}
