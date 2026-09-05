/**
 * The carousel — a coverflow you can throw.
 *
 * This is the screen T-1 is actually about. A list that is merely correct is the spreadsheet
 * it replaces, so the feel of this thing is the requirement, not decoration on top of one.
 *
 * Three input paths, one state: drag, buttons, keyboard. All of them move the same
 * fractional `position`, and every frame renders from that single number — which is what
 * makes a flick mid-animation behave rather than fight whatever was already running.
 */

const DRAG_THRESHOLD = 6;   // px before a press becomes a drag rather than a click
const CARD_STEP = 168;      // px of horizontal travel that equals one card
const FRICTION = 0.94;      // per-frame velocity decay when thrown
const MIN_VELOCITY = 0.02;  // below this, settle onto the nearest card
const WINDOW = 6;           // cards rendered either side of centre — see AC5's 200-title case

export function createCarousel({ items, onOpen, onSelect }) {
  const root = document.createElement('div');
  root.className = 'coverflow';
  root.tabIndex = 0;
  root.setAttribute('role', 'listbox');
  root.setAttribute('aria-label', 'Your list');

  const stage = document.createElement('div');
  stage.className = 'coverflow__stage';

  const prev = button('‹', 'Previous title');
  const next = button('›', 'Next title');
  root.append(prev, stage, next);

  /** Fractional so a drag can sit between two cards. */
  let position = 0;
  let velocity = 0;
  let frame = null;
  const nodes = new Map();   // index -> element, so we build each card once

  const clamp = (n) => Math.max(0, Math.min(items.length - 1, n));
  const centre = () => clamp(Math.round(position));

  function button(glyph, label) {
    const element = document.createElement('button');
    element.className = 'btn btn--round coverflow__step';
    element.type = 'button';
    element.textContent = glyph;
    element.setAttribute('aria-label', label);
    return element;
  }

  function card(item, index) {
    const element = document.createElement('div');
    element.className = 'cf-card';
    element.setAttribute('role', 'option');
    element.dataset.index = String(index);

    const poster = document.createElement('div');
    // Fixed 2:3 frame with cover fill. IGDB box art measures 0.75 and TMDB posters 0.67, so
    // without this a game would letterbox next to a film on the same wall.
    poster.className = 'poster';
    if (item.poster_path) poster.style.backgroundImage = `url("${item.poster_path}")`;
    else poster.append(Object.assign(document.createElement('span'), { className: 'poster__none', textContent: item.title }));

    element.append(poster);
    return element;
  }

  function render() {
    const middle = Math.round(position);

    // Only the cards near the centre exist in the DOM. With 200 titles this keeps the tree
    // at ~13 nodes instead of 200, which is the difference between smooth and not.
    for (const [index, node] of nodes) {
      if (Math.abs(index - middle) > WINDOW) { node.remove(); nodes.delete(index); }
    }

    for (let index = middle - WINDOW; index <= middle + WINDOW; index += 1) {
      if (index < 0 || index >= items.length) continue;
      let node = nodes.get(index);
      if (!node) {
        node = card(items[index], index);
        nodes.set(index, node);
        stage.append(node);
      }

      const offset = index - position;
      const distance = Math.abs(offset);
      const sign = Math.sign(offset);
      const x = offset * 132;
      const depth = -Math.min(distance, 4) * 88;
      const turn = -sign * Math.min(distance, 3) * 38;
      const scale = Math.max(0.62, 1 - distance * 0.1);

      node.style.transform = `translateX(${x}px) translateZ(${depth}px) rotateY(${turn}deg) scale(${scale})`;
      node.style.zIndex = String(100 - Math.round(distance * 10));
      node.style.opacity = String(Math.max(0, 1 - distance * 0.18));
      node.classList.toggle('is-centre', index === clamp(Math.round(position)));
      node.setAttribute('aria-selected', String(index === clamp(Math.round(position))));
    }

    onSelect?.(items[centre()], centre());
  }

  function settle() {
    // One loop drives both the thrown decay and the snap home, so a new grab mid-settle just
    // changes the numbers rather than racing a separate animation.
    cancelAnimationFrame(frame);
    const step = () => {
      if (Math.abs(velocity) > MIN_VELOCITY) {
        position = clamp(position + velocity);
        velocity *= FRICTION;
      } else {
        const target = clamp(Math.round(position));
        const delta = target - position;
        if (Math.abs(delta) < 0.001) { position = target; render(); return; }
        position += delta * 0.22;
      }
      render();
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
  }

  function goTo(index) {
    velocity = 0;
    position = clamp(index);
    settle();
  }

  // ── drag ────────────────────────────────────────────────────────────────────────────
  let pointerId = null;
  let startX = 0;
  let startPosition = 0;
  let moved = 0;
  let lastX = 0;
  let lastAt = 0;
  // The card the press STARTED on. Captured here because `setPointerCapture` retargets
  // every later pointer event to the stage: by `pointerup`, `event.target` is the stage
  // and `closest('.cf-card')` walks upward and finds nothing, so a click on the centre
  // card silently did nothing at all.
  let pressedCard = null;

  stage.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 && event.pointerType === 'mouse') return;
    pointerId = event.pointerId;
    stage.setPointerCapture(pointerId);
    cancelAnimationFrame(frame);
    velocity = 0;
    startX = lastX = event.clientX;
    lastAt = performance.now();
    startPosition = position;
    moved = 0;
    pressedCard = event.target.closest('.cf-card');
    root.classList.add('is-dragging');
  });

  stage.addEventListener('pointermove', (event) => {
    if (event.pointerId !== pointerId) return;
    const dx = event.clientX - startX;
    moved = Math.max(moved, Math.abs(dx));
    position = clamp(startPosition - dx / CARD_STEP);

    const now = performance.now();
    const dt = now - lastAt;
    if (dt > 0) velocity = -((event.clientX - lastX) / CARD_STEP) * (16 / dt);
    lastX = event.clientX;
    lastAt = now;
    render();
  });

  function endDrag(event) {
    if (event.pointerId !== pointerId) return;
    stage.releasePointerCapture(pointerId);
    pointerId = null;
    root.classList.remove('is-dragging');

    // AC4: a drag must never navigate. Past the threshold this was a gesture, so we settle
    // and swallow the click the browser is about to synthesise.
    if (moved > DRAG_THRESHOLD) { settle(); return; }

    const hit = pressedCard;
    pressedCard = null;
    if (hit) {
      const index = Number(hit.dataset.index);
      if (index === centre()) onOpen?.(items[index], index);
      else goTo(index);
    }
  }
  stage.addEventListener('pointerup', endDrag);
  stage.addEventListener('pointercancel', endDrag);
  stage.addEventListener('click', (event) => { if (moved > DRAG_THRESHOLD) event.stopPropagation(); }, true);

  // ── buttons: exactly one card, never a compounding spin ─────────────────────────────
  prev.addEventListener('click', () => goTo(centre() - 1));
  next.addEventListener('click', () => goTo(centre() + 1));

  // ── keyboard ────────────────────────────────────────────────────────────────────────
  root.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft') { goTo(centre() - 1); event.preventDefault(); }
    else if (event.key === 'ArrowRight') { goTo(centre() + 1); event.preventDefault(); }
    else if (event.key === 'Enter' || event.key === ' ') { onOpen?.(items[centre()], centre()); event.preventDefault(); }
    else if (event.key === 'Home') { goTo(0); event.preventDefault(); }
    else if (event.key === 'End') { goTo(items.length - 1); event.preventDefault(); }
  });

  render();
  return { element: root, goTo, get index() { return centre(); } };
}
