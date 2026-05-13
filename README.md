# Contortion Fighter

A retro SF2-style 2D fighting game where every fighter's moveset is built around extreme flexibility and contortion.

## How to Run

Open `index.html` in any modern browser. No build step, no server required.

> Tip: use a local file server (e.g. `python3 -m http.server`) if your browser blocks ES module imports from `file://`.

---

## Controls

| Action       | Player 1   | Player 2     |
|--------------|------------|--------------|
| Move Left    | A          | ←            |
| Move Right   | D          | →            |
| Jump         | W          | ↑            |
| Crouch       | S          | ↓            |
| Light Attack | F          | J            |
| Med Attack   | G          | K            |
| Heavy Attack | H (hold)   | L            |

> **Note:** H is also used as a debug toggle — tap it while not attacking to toggle hitbox/hurtbox overlays.

| Key | Function              |
|-----|-----------------------|
| H   | Toggle hitbox overlay |
| ESC | Pause                 |

---

## Architecture

```
src/
  main.js               Boot: canvas setup, module wiring, game start
  engine/
    loop.js             Fixed-timestep 60hz logic, interpolated render
    physics.js          Gravity, velocity integration, floor/wall collision
    collision.js        AABB hit/hurtbox detection and resolution
  input/
    keyboard.js         Raw key state + per-frame edge detection
                        getInputState(id) → { left, right, up, down, lp, mp, hp }
                        Same interface will be used by AI controller in Phase 5
  game/
    fighter.js          Fighter state machine (IDLE/WALK/JUMP/CROUCH/ATTACK/HITSTUN/KO)
    round.js            Round lifecycle: intro → fight → KO → result
    stage.js            Parallax background layers, floor constants
  render/
    renderer.js         Master render pass orchestrator
    fighterRenderer.js  Rectangle body + stick-figure limbs, state-aware poses
    ui.js               Health bars, round timer, announcements
    postfx.js           CRT scanlines + chromatic aberration
```

Internal resolution: **640×360** — scaled 2× to 1280×720 via CSS for chunky pixels.

---

## Phase Status

See [PHASES.md](PHASES.md) for detailed progress.
