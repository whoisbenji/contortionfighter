// Round lifecycle: INTRO → FIGHT → KO → RESULT → (restart)
import { STATE } from '../engine/stateMachine.js';

export const PHASE = {
  INTRO:   'INTRO',
  FIGHT:   'FIGHT',
  KO:      'KO',
  RESULT:  'RESULT',
};

const INTRO_DURATION  = 180; // 3 s at 60fps
const KO_FREEZE       = 60;  // 1 s freeze on KO
const RESULT_DURATION = 180; // 3 s result screen
const ROUND_TIME_SECS = 99;

export function createRound() {
  return {
    phase:       PHASE.INTRO,
    phaseTimer:  INTRO_DURATION,
    roundNumber: 1,
    timeLeft:    ROUND_TIME_SECS * 60, // in frames
    winner:      null, // 1, 2, or 'draw'
  };
}

/**
 * Advance round state each logic tick.
 * fighters: [f1, f2]
 * Returns updated round object (mutates in place for simplicity).
 */
export function updateRound(round, fighters) {
  switch (round.phase) {
    case PHASE.INTRO:
      round.phaseTimer--;
      if (round.phaseTimer <= 0) {
        round.phase = PHASE.FIGHT;
      }
      break;

    case PHASE.FIGHT:
      // Count down timer
      round.timeLeft--;

      // Check for KO
      for (const f of fighters) {
        if (f.state === STATE.KO) {
          round.phase = PHASE.KO;
          round.phaseTimer = KO_FREEZE;
          // Winner is the OTHER fighter
          round.winner = f.id === 1 ? 2 : 1;
          return;
        }
      }

      // Time-out
      if (round.timeLeft <= 0) {
        round.phase = PHASE.KO;
        round.phaseTimer = KO_FREEZE;
        const [f1, f2] = fighters;
        if (f1.hp > f2.hp) round.winner = 1;
        else if (f2.hp > f1.hp) round.winner = 2;
        else round.winner = 'draw';
      }
      break;

    case PHASE.KO:
      round.phaseTimer--;
      if (round.phaseTimer <= 0) {
        round.phase = PHASE.RESULT;
        round.phaseTimer = RESULT_DURATION;
      }
      break;

    case PHASE.RESULT:
      round.phaseTimer--;
      // main.js will detect phase === RESULT and phaseTimer <= 0 to restart
      break;
  }
}

/** True when fighters are allowed to move / attack */
export function isFightActive(round) {
  return round.phase === PHASE.FIGHT;
}

/** Seconds remaining (for UI display) */
export function getTimeSeconds(round) {
  return Math.ceil(round.timeLeft / 60);
}
