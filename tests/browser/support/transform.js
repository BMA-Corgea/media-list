/**
 * Parse a CSS `transform` COMPUTED style value into numbers — never trust the stylesheet
 * text, per kb/notes/handoff.md §3: an undefined custom property fails silently there and
 * looks deliberate. The carousel's centre card composes translateX/translateZ/rotateY/scale
 * into one 3D matrix, so a browser that gets any term wrong shows up here as a translateX or
 * translateZ that is not ~0 at the centre, even though every individual CSS declaration
 * still "looks" correct in the source.
 */
export function parseMatrix(value) {
  const match = /matrix(3d)?\(([^)]+)\)/.exec(value || '');
  if (!match) return null;
  const n = match[2].split(',').map(Number);
  if (match[1]) {
    // matrix3d(...): 16 values, column-major. Translation lives at indices 12-14.
    return { is3d: true, translateX: n[12], translateY: n[13], translateZ: n[14] };
  }
  // matrix(a, b, c, d, e, f): translation is (e, f); rotation is atan2(b, a).
  const [a, b, , , e, f] = n;
  return { is3d: false, translateX: e, translateY: f, rotationDeg: (Math.atan2(b, a) * 180) / Math.PI };
}
