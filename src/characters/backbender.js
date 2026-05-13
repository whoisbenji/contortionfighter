// The Backbender — balanced all-rounder, the Ryu of the roster.
// Identity: backbend stances and chest-stand attacks.
// Pure data file — zero imports, zero logic.

export const Backbender = {

  // ── Stats ─────────────────────────────────────────────────────────────────
  stats: {
    health:       1000,
    walkSpeed:    2.8,
    jumpHeight:   13.5,   // initial vy magnitude (positive; applied as negative)
    weight:       1.0,    // knockback multiplier
    stunThreshold: 400,   // total hit-stun damage before dizzy (Phase 4+)
    width:        30,
    height:       72,
  },

  // ── Default hurtboxes ────────────────────────────────────────────────────
  // ox/oy: offset from fighter bottom-centre (ox flipped by facing)
  // oy=0 → top of box is at the top of the fighter
  defaultHurtboxes: {
    stand:  [{ ox: 0, oy:  0, w: 28, h: 72 }],
    crouch: [{ ox: 0, oy: 30, w: 32, h: 42 }],
    air:    [{ ox: 0, oy:  6, w: 26, h: 60 }],
  },

  // ── Move list ─────────────────────────────────────────────────────────────
  // All moves are defined here even if not yet wired in the state machine.
  // startup  = frames before first active frame (0-indexed from state entry)
  // active   = hitbox-live frames
  // recovery = frames after last active frame
  // total    = startup + active + recovery
  //
  // cancelWindow  = [firstFrame, lastFrame] within which cancel is possible
  // chainCancelInto  = moves you can normal-cancel into
  // specialCancelInto = moves you can special-cancel into
  //
  // hurtboxOverrides = { frameN: [...boxes] } sparse map for contortion shapes
  // invulnFrames = [start, end] frames where fighter is fully invincible
  //
  // onHit / onBlock = frame advantage (positive = attacker advantage)
  //
  // properties: array of flags — 'overhead','low','knockdown','launcher',
  //             'low_profile','anti_air'

  moves: {

    // ── Standing normals ──────────────────────────────────────────────────

    light_punch: {
      notation:  '5LP',
      startup:   3,
      active:    2,
      recovery:  7,     // total: 12
      hitboxes: [{
        ox: 22, oy: 10, w: 28, h: 24,
        damage:    80,
        hitstun:   14,
        blockstun: 10,
        knockback: { x: 3.0, y: 0 },
        blockType: 'mid',
      }],
      hurtboxOverrides: null,
      chainCancelInto:   ['light_kick', 'medium_punch'],
      specialCancelInto: ['backbend_shot', 'spine_spike'],
      cancelWindow: [3, 8],
      properties: [],
      onHit: 2, onBlock: -2,
    },

    medium_punch: {
      notation:  '5MP',
      startup:   6,
      active:    3,
      recovery:  12,    // total: 21
      hitboxes: [{
        ox: 28, oy: 6, w: 34, h: 26,
        damage:    130,
        hitstun:   18,
        blockstun: 14,
        knockback: { x: 4.0, y: 0 },
        blockType: 'mid',
      }],
      // Backbend pose: upper hurtbox retreats during this move (step 8)
      hurtboxOverrides: null,
      chainCancelInto:   ['heavy_punch'],
      specialCancelInto: ['backbend_shot', 'spine_spike'],
      cancelWindow: [6, 16],
      properties: [],
      onHit: 0, onBlock: -4,
    },

    heavy_punch: {
      notation:  '5HP',
      startup:   10,
      active:    4,
      recovery:  20,    // total: 34
      hitboxes: [{
        ox: 24, oy: 2, w: 38, h: 32,
        damage:    220,
        hitstun:   26,
        blockstun: 20,
        knockback: { x: 6.5, y: 0 },
        blockType: 'mid',
        // Chest-stand pose — big horizontal reach
      }],
      hurtboxOverrides: null,
      chainCancelInto:   [],
      specialCancelInto: ['spine_spike'],
      cancelWindow: [10, 18],
      properties: ['knockdown'],
      onHit: -4, onBlock: -12,
    },

    light_kick: {
      notation:  '5LK',
      startup:   4,
      active:    2,
      recovery:  8,     // total: 14
      hitboxes: [{
        ox: 20, oy: 32, w: 30, h: 20,
        damage:    70,
        hitstun:   12,
        blockstun:  8,
        knockback: { x: 2.5, y: 0 },
        blockType: 'mid',
      }],
      hurtboxOverrides: null,
      chainCancelInto:   ['medium_kick'],
      specialCancelInto: [],
      cancelWindow: [4, 10],
      properties: [],
      onHit: 0, onBlock: -3,
    },

    medium_kick: {
      notation:  '5MK',
      startup:   7,
      active:    4,
      recovery:  14,    // total: 25  — oversplit kick, long range
      hitboxes: [{
        ox: 36, oy: 26, w: 40, h: 24,
        damage:    150,
        hitstun:   20,
        blockstun: 16,
        knockback: { x: 5.0, y: 0 },
        blockType: 'mid',
      }],
      hurtboxOverrides: null,
      chainCancelInto:   ['heavy_kick'],
      specialCancelInto: ['backbend_shot', 'spine_spike'],
      cancelWindow: [7, 18],
      properties: [],
      onHit: 0, onBlock: -2,
    },

    heavy_kick: {
      notation:  '5HK',
      startup:   12,
      active:    4,
      recovery:  18,    // total: 34  — falling axe kick, overhead
      hitboxes: [{
        ox: 16, oy: 0, w: 28, h: 36,
        damage:    200,
        hitstun:   24,
        blockstun: 18,
        knockback: { x: 4.0, y: 0 },
        blockType: 'high',   // OVERHEAD — must be blocked standing
      }],
      // Inverted backbend hurtbox — retreats upper body (step 8)
      hurtboxOverrides: null,
      chainCancelInto:   [],
      specialCancelInto: [],
      cancelWindow: [12, 20],
      properties: ['overhead'],
      onHit: -2, onBlock: -10,
    },

    // ── Crouching normals ──────────────────────────────────────────────────

    '2lp': {
      notation:  '2LP',
      startup:   3,
      active:    2,
      recovery:  7,     // total: 12
      hitboxes: [{
        ox: 20, oy: 36, w: 26, h: 20,
        damage:    70,
        hitstun:   12,
        blockstun:  8,
        knockback: { x: 2.5, y: 0 },
        blockType: 'low',
      }],
      hurtboxOverrides: null,
      chainCancelInto:   ['2mk'],
      specialCancelInto: ['backbend_shot'],
      cancelWindow: [3, 8],
      properties: ['low'],
      onHit: 2, onBlock: -1,
    },

    '2mk': {
      notation:  '2MK',
      startup:   8,
      active:    3,
      recovery:  22,    // total: 33  — long recovery, punishable on whiff
      hitboxes: [{
        ox: 34, oy: 50, w: 44, h: 18,
        damage:    110,
        hitstun:   20,
        blockstun: 14,
        knockback: { x: 5.0, y: 0 },
        blockType: 'low',    // must be blocked low
      }],
      // Recovery pose: fold with stretched hurtbox (step 8)
      hurtboxOverrides: null,
      chainCancelInto:   [],
      specialCancelInto: [],
      cancelWindow: [],
      properties: ['low', 'knockdown'],
      onHit: -4, onBlock: -14,
    },

    '2hp': {
      notation:  '2HP',
      startup:   7,
      active:    4,
      recovery:  14,    // total: 25  — anti-air chest stand
      hitboxes: [{
        ox: 10, oy: -10, w: 32, h: 40,  // negative oy = above normal standing height
        damage:    180,
        hitstun:   22,
        blockstun: 16,
        knockback: { x: 2.0, y: -6 },   // launcher: sends opponent upward
        blockType: 'mid',
      }],
      // Chest-stand hurtbox: low and forward (step 8)
      hurtboxOverrides: null,
      chainCancelInto:   [],
      specialCancelInto: ['spine_spike'],
      cancelWindow: [7, 14],
      properties: ['anti_air', 'launcher'],
      onHit: -2, onBlock: -8,
    },

    // ── Air normals ────────────────────────────────────────────────────────

    j_mp: {
      notation:  'j.MP',
      startup:   5,
      active:    4,
      recovery:  8,     // total: 17
      hitboxes: [{
        ox: 20, oy: 18, w: 30, h: 26,
        damage:    110,
        hitstun:   16,
        blockstun: 12,
        knockback: { x: 3.0, y: 1.5 },
        blockType: 'mid',
      }],
      hurtboxOverrides: null,
      chainCancelInto:   [],
      specialCancelInto: [],
      cancelWindow: [],
      properties: [],
      onHit: 0, onBlock: -4,
    },

    j_hk: {
      notation:  'j.HK',
      startup:   8,
      active:    5,
      recovery:  10,    // total: 23  — diving kick from piked position, overhead
      hitboxes: [{
        ox: 14, oy: 28, w: 26, h: 34,
        damage:    160,
        hitstun:   20,
        blockstun: 14,
        knockback: { x: 4.0, y: 2.0 },
        blockType: 'high',   // overhead
      }],
      hurtboxOverrides: null,
      chainCancelInto:   [],
      specialCancelInto: [],
      cancelWindow: [],
      properties: ['overhead'],
      onHit: -2, onBlock: -8,
    },

    // ── Special moves ──────────────────────────────────────────────────────

    backbend_shot: {
      notation:    '236P',
      startup:     14,      // bends back, then fires
      active:      0,       // projectile handles its own active frames
      recovery:    20,      // total: 34  (projectile spawned on frame 14)
      spawnProjectileOnFrame: 14,
      hitboxes:    [],      // no direct hitbox — damage is on the projectile
      hurtboxOverrides: {
        // Frames 8-13: backbend pose — upper hurtbox retreats (step 8)
      },
      chainCancelInto:   [],
      specialCancelInto: [],
      cancelWindow: [],
      properties: [],
      onHit: -2, onBlock: -8,

      // Projectile definition — instantiated by the engine when this move fires
      projectile: {
        speed:    { lp: 5.0, mp: 6.5, hp: 8.0 },  // varies by button strength
        damage:   { lp: 80,  mp: 110, hp: 140 },
        hitstun:  18,
        blockstun: 12,
        knockback: { x: 3.0, y: 0 },
        size:      { w: 20, h: 20 },
        maxTravelX: 600,
      },
    },

    spine_spike: {
      notation:    '623P',
      startup:     5,
      active:      8,
      recovery:    24,    // total: 37  — rises in a chest-stand arc
      hitboxes: [
        // First active frames: upper body spike
        { ox: 10, oy: -8, w: 28, h: 36, damage: 90,  hitstun: 18, blockstun: 14,
          knockback: { x: 2.0, y: -5 }, blockType: 'mid' },
        // Later active frames: coming down
        { ox: 16, oy: 4, w: 24, h: 30, damage: 60, hitstun: 14, blockstun: 10,
          knockback: { x: 3.0, y: 0 }, blockType: 'mid' },
      ],
      // LP version: fully invincible frames 0-4 (startup), fast recovery
      // HP version: invincible frames 0-2, slow recovery
      invulnFrames: [0, 4],   // full invuln during startup (LP version)
      hurtboxOverrides: null, // step 8: chest-stand hurtbox while rising
      chainCancelInto:   [],
      specialCancelInto: [],
      cancelWindow: [],
      properties: ['anti_air'],
      onHit: -8, onBlock: -20,
    },
  },

  // ── State list ───────────────────────────────────────────────────────────
  // Non-attack states only — attack states are auto-generated from moves.
  // Transition priority is declared; the engine checks them in order.
  states: {
    IDLE:       { transitions: ['special', 'attack', 'jump', 'crouch', 'walk', 'block'] },
    WALK_F:     { transitions: ['special', 'attack', 'jump', 'crouch', 'idle', 'block'] },
    WALK_B:     { transitions: ['special', 'attack', 'jump', 'crouch', 'idle', 'block'] },
    JUMP_N:     { transitions: ['air_attack', 'land'] },
    JUMP_F:     { transitions: ['air_attack', 'land'] },
    JUMP_B:     { transitions: ['air_attack', 'land'] },
    CROUCH:     { transitions: ['special', 'attack', 'rise', 'block'] },
    BLOCK_HIGH: { transitions: ['unblock'] },
    BLOCK_LOW:  { transitions: ['unblock'] },
    HITSTUN:    { transitions: ['frame_end'] },
    BLOCKSTUN:  { transitions: ['frame_end'] },
    KNOCKDOWN:  { transitions: ['frame_end'] },
    GETUP:      { transitions: ['frame_end'] },
    KO:         { transitions: [] },
  },

  // ── Pose data ────────────────────────────────────────────────────────────
  // Stick-figure limb positions for the renderer.
  // Per state — attack poses are per-frame arrays (filled in step 4+).
  // Format: { head:{ox,oy}, joints: { armR:[...], armL:[...], legR:[...], legL:[...] } }
  // All coords relative to fighter bottom-centre, y-axis UP (y=-72 = top of standing figure).
  // null = fall back to fighterRenderer built-in poses.
  poses: {
    IDLE:    null,
    WALK_F:  null,
    WALK_B:  null,
    JUMP_N:  null,
    JUMP_F:  null,
    JUMP_B:  null,
    CROUCH:  null,
    HITSTUN: null,
    KO:      null,
  },
};
