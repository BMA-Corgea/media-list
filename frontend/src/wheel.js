/**
 * The wheel.
 *
 * The owner asked for this by name and asked for the animation to be good, so the motion is the
 * requirement here rather than decoration on a random number.
 *
 * The one rule that makes it honest: THE WINNER IS CHOSEN FIRST and the rotation is computed
 * to land on it. Reading a result off wherever a spin happens to stop makes fairness depend
 * on the animation, which is both harder to reason about and impossible to test. `pickIndex`
 * is deliberately DOM-free so its distribution can be checked ten thousand times without a
 * browser.
 */

/** Uniform over [0, count). The whole of the randomness, in one testable place. */
export function pickIndex(count) {
  if (count <= 0) return -1;
  return Math.floor(Math.random() * count);
}

/**
 * Where the wheel must stop for `winner` to sit under the pointer.
 *
 * Returns absolute degrees (always increasing, so the wheel never appears to rewind between
 * spins). The landing is jittered WITHIN the winning wedge so two spins never stop on an
 * identical pixel — bounded to 70% of the wedge so the jitter can never reach a neighbour.
 */
export function rotationFor(winner, count, currentRotation, turns = 5) {
  const wedge = 360 / count;
  const centre = winner * wedge + wedge / 2;
  const jitter = (Math.random() - 0.5) * wedge * 0.7;
  // The pointer sits at the top (−90° in SVG terms); bringing a wedge there means rotating
  // by the negative of its angle.
  const desired = ((-centre - jitter) % 360 + 360) % 360;
  const base = Math.ceil(currentRotation / 360) * 360;
  return base + turns * 360 + desired;
}

/** Which wedge is under the pointer at a given absolute rotation — the inverse, for tests. */
export function segmentAt(rotation, count) {
  const wedge = 360 / count;
  const under = ((-rotation % 360) + 360) % 360;
  return Math.floor(under / wedge) % count;
}

const TINT = {
  anime: 'var(--wheel-a)',
  movie: 'var(--wheel-b)',
  'live-action': 'var(--wheel-c)',
  game: 'var(--wheel-d)',
};

const SIZE = 380;
const R = SIZE / 2;

function wedgePath(index, count) {
  const step = (Math.PI * 2) / count;
  const from = index * step - Math.PI / 2;
  const to = from + step;
  const x1 = R + R * Math.cos(from), y1 = R + R * Math.sin(from);
  const x2 = R + R * Math.cos(to), y2 = R + R * Math.sin(to);
  const large = step > Math.PI ? 1 : 0;
  return `M ${R} ${R} L ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} Z`;
}

/** The SVG wheel. Text rides each wedge; the artwork belongs to the reveal, not to a 33° slice. */
export function buildWheel(items) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${SIZE} ${SIZE}`);
  svg.setAttribute('class', 'wheel__disc');

  const count = items.length;
  const step = 360 / count;

  items.forEach((item, index) => {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', wedgePath(index, count));
    path.setAttribute('fill', TINT[item.kind] || 'var(--wheel-a)');
    path.setAttribute('class', 'wheel__wedge');
    svg.append(path);

    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    const mid = index * step + step / 2 - 90;
    label.setAttribute('class', 'wheel__label');
    label.setAttribute('x', String(R + R * 0.94));
    label.setAttribute('y', String(R));
    label.setAttribute('text-anchor', 'end');
    label.setAttribute('dominant-baseline', 'middle');
    label.setAttribute('transform', `rotate(${mid} ${R} ${R})`);
    label.textContent = item.title.length > 22 ? `${item.title.slice(0, 21)}…` : item.title;
    svg.append(label);
  });

  const hub = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  hub.setAttribute('cx', String(R)); hub.setAttribute('cy', String(R)); hub.setAttribute('r', '34');
  hub.setAttribute('class', 'wheel__hub');
  svg.append(hub);
  return svg;
}
