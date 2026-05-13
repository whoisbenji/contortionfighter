// Directional input buffer for special move detection.
// Stores per-frame directional inputs in numpad notation (relative to facing):
//   5=neutral, 2=down, 8=up, 4=back, 6=fwd, 1=down-back, 3=down-fwd, 7=up-back, 9=up-fwd

const BUFFER_FRAMES = 60; // how many frames of history to keep

export function createMotionBuffer() {
  return {
    dirs: [],        // string[], one entry per logic frame
    currentFrame: 0,
  };
}

/** Call once per logic frame before state machine runs. */
export function recordInput(buf, input, facing) {
  buf.dirs.push(getNumpad(input, facing));
  if (buf.dirs.length > BUFFER_FRAMES) buf.dirs.shift();
  buf.currentFrame++;
}

/**
 * Check if a numpad motion sequence appears in the last maxAge frames.
 * sequence: string like '236', '623', '214'
 * Returns true if the sequence is found (sub-sequence match, skipping irrelevant frames).
 */
export function checkMotion(buf, sequence, maxAge = 16) {
  const recent = buf.dirs.slice(-maxAge);
  let si = 0;
  for (const d of recent) {
    if (d === sequence[si]) {
      si++;
      if (si >= sequence.length) return true;
    }
  }
  return false;
}

/** Convert raw input to numpad direction, relative to facing direction. */
function getNumpad(input, facing) {
  const fwd  = facing === 1 ? input.right : input.left;
  const back = facing === 1 ? input.left  : input.right;
  const down = input.down;
  const up   = input.up;

  if (down && fwd)  return '3';
  if (down && back) return '1';
  if (up   && fwd)  return '9';
  if (up   && back) return '7';
  if (down)         return '2';
  if (up)           return '8';
  if (fwd)          return '6';
  if (back)         return '4';
  return '5';
}
