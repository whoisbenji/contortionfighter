// Raw keyboard state + per-frame edge detection.
// getInputState(playerId) returns a plain object that the fighter state machine
// consumes — the same shape the AI controller will produce in Phase 5.
//
// Control scheme (Phase 2+):
//   P1: WASD movement | F=LP  G=MP  H=HP  R=LK  T=MK  Y=HK
//   P2: Arrow movement | J=LP  K=MP  L=HP  U=LK  I=MK  O=HK
//   ` (backtick) = hitbox debug toggle
//   ESC = pause

const held        = new Set();
const justPressed  = new Set();
const justReleased = new Set();

const BINDINGS = {
  1: { left:'KeyA', right:'KeyD', up:'KeyW', down:'KeyS',
       lp:'KeyF', mp:'KeyG', hp:'KeyH', lk:'KeyR', mk:'KeyT', hk:'KeyY' },
  2: { left:'ArrowLeft', right:'ArrowRight', up:'ArrowUp', down:'ArrowDown',
       lp:'KeyJ', mp:'KeyK', hp:'KeyL', lk:'KeyU', mk:'KeyI', hk:'KeyO' },
};

window.addEventListener('keydown', e => {
  if (!held.has(e.code)) justPressed.add(e.code);
  held.add(e.code);
  // Prevent arrow keys from scrolling the page
  if (e.code.startsWith('Arrow')) e.preventDefault();
});

window.addEventListener('keyup', e => {
  held.delete(e.code);
  justReleased.add(e.code);
});

/** Call once per logic frame to clear edge-detection sets. */
export function flushInput() {
  justPressed.clear();
  justReleased.clear();
}

/**
 * Returns the current input state for a player.
 * Held fields (left/right/etc.) are true while key is down.
 * *Pressed fields are true ONLY on the frame the key went down.
 */
export function getInputState(playerId) {
  const b = BINDINGS[playerId];
  return {
    left:  held.has(b.left),
    right: held.has(b.right),
    up:    held.has(b.up),
    down:  held.has(b.down),
    lp:    held.has(b.lp),
    mp:    held.has(b.mp),
    hp:    held.has(b.hp),
    lk:    held.has(b.lk),
    mk:    held.has(b.mk),
    hk:    held.has(b.hk),

    lpPressed: justPressed.has(b.lp),
    mpPressed: justPressed.has(b.mp),
    hpPressed: justPressed.has(b.hp),
    lkPressed: justPressed.has(b.lk),
    mkPressed: justPressed.has(b.mk),
    hkPressed: justPressed.has(b.hk),
    upPressed: justPressed.has(b.up),
  };
}

/** True if a raw key code was just pressed this frame (for system keys). */
export function wasPressed(code) {
  return justPressed.has(code);
}
