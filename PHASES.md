# Contortion Fighter — Phase Tracker

---

## Phase 1 — Core Engine + Movement ✅ COMPLETE

Goal: Rock-solid foundation. No characters, no AI, no special moves.

### Sub-steps
- [x] Repo init, scaffolding, .gitignore, README, PHASES.md
- [x] Fixed-timestep game loop (loop.js)
- [x] Stage background + CRT post-FX (stage.js, renderer.js, postfx.js)
- [x] Input abstraction (keyboard.js)
- [x] Fighter state machine + physics (fighter.js, physics.js)
- [x] Stick-figure renderer with state-aware poses (fighterRenderer.js)
- [x] Hit detection, hitstun, knockback (collision.js + light punch)
- [x] Health bars + round timer (ui.js)
- [x] Round lifecycle intro/KO flow (round.js)

### Deliverables
- Two placeholder fighters (red vs blue rectangles + stick limbs)
- Walk, jump, crouch, one attack each
- Working hit detection with hitstun + knockback
- CRT scanline + chromatic aberration overlay
- Health bars + 99-second round timer
- Hitbox/hurtbox debug toggle (H key)

---

## Phase 2 — Character System + First Fighter (PLANNED)

"The Backbender" — full moveset of normals + 1–2 specials.
Character data architecture, animation frames, move properties.

---

## Phase 3 — Input Buffer + Special Moves (PLANNED)

Quarter-circle motions, charge moves, double-tap dashes.
16-frame input buffer, canonical motion detection.

---

## Phase 4 — Full Roster (PLANNED)

4–6 contortion-themed fighters: grappler, zoner, rushdown, etc.

---

## Phase 5 — CPU AI (PLANNED)

Reactive AI driven through the same input interface as human players.
Easy / Medium / Hard difficulty. Reads spacing, punishes mistakes.

---

## Phase 6 — Polish (PLANNED)

Title screen, character select, stage select, sound, music, visual polish.
