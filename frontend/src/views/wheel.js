/** Can't decide? Spin. */

import { api } from '../api.js';
import { navigate } from '../router.js';
import { pickIndex, rotationFor, buildWheel } from '../wheel.js';

const KINDS = ['all', 'anime', 'movie', 'live-action', 'game'];
const SPIN_MS = 4400;

const prefersReducedMotion = () =>
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

export async function wheelView() {
  const page = document.createElement('main');
  page.className = 'page';

  let all = [];
  try {
    all = await api.titles('queued');
  } catch (error) {
    page.innerHTML = `<div class="empty"><h2>Could not reach the list</h2><p>${error.message}</p></div>`;
    return page;
  }

  let filter = 'all';
  let rotation = 0;
  let spinning = false;
  const eligible = () => (filter === 'all' ? all : all.filter((r) => r.kind === filter));

  const chips = document.createElement('div');
  chips.className = 'nav filters';
  const stage = document.createElement('div');
  stage.className = 'wheel';
  const reveal = document.createElement('div');
  reveal.className = 'reveal';
  const spin = Object.assign(document.createElement('button'), { className: 'btn btn--primary btn--spin', textContent: 'Spin' });

  function showReveal(item, note) {
    reveal.replaceChildren();
    if (!item) return;
    const card = document.createElement('div');
    card.className = 'reveal__card panel';
    const art = document.createElement('div');
    art.className = 'poster reveal__art';
    if (item.poster_path) art.style.backgroundImage = `url("${item.poster_path}")`;

    const text = document.createElement('div');
    text.className = 'reveal__text';
    if (note) text.append(Object.assign(document.createElement('p'), { className: 'reveal__note', textContent: note }));
    text.append(
      Object.assign(document.createElement('h2'), { className: 'reveal__title', textContent: item.title }),
      Object.assign(document.createElement('p'), { className: 'card__meta', textContent: `${item.kind} · ${item.year || ''}` }),
    );
    if (item.why) text.append(Object.assign(document.createElement('p'), { className: 'caption__why', textContent: `“${item.why}”` }));

    const open = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Open it' });
    open.addEventListener('click', () => navigate(`/title/${item.id}`));
    const again = Object.assign(document.createElement('button'), { className: 'btn', textContent: 'Spin again' });
    again.addEventListener('click', () => doSpin());
    const actions = document.createElement('div');
    actions.className = 'actions';
    actions.append(open, again);
    text.append(actions);

    card.append(art, text);
    reveal.append(card);
  }

  function paint() {
    const items = eligible();
    for (const chip of chips.children) chip.setAttribute('aria-pressed', String(chip.dataset.kind === filter));
    stage.replaceChildren();
    reveal.replaceChildren();
    rotation = 0;

    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.innerHTML = `<h2>Nothing to spin for</h2><p>${filter === 'all' ? 'Your queue is empty.' : `Nothing in ${filter} is queued.`}</p>`;
      stage.append(empty);
      spin.disabled = true;
      return;
    }

    spin.disabled = false;
    if (items.length === 1) {
      // No theatre for a foregone conclusion.
      spin.textContent = 'Well, obviously';
      return;
    }
    spin.textContent = 'Spin';

    const pointer = Object.assign(document.createElement('div'), { className: 'wheel__pointer' });
    const disc = buildWheel(items);
    disc.style.transform = `rotate(${rotation}deg)`;
    stage.append(pointer, disc);
  }

  async function doSpin() {
    if (spinning) return;
    const items = eligible();
    if (!items.length) return;

    // The winner is decided HERE, by the RNG, before anything moves.
    const winner = pickIndex(items.length);

    if (items.length === 1) {
      showReveal(items[0], 'Only one thing in this list, so:');
      return;
    }

    if (prefersReducedMotion()) {
      // Same picker, no theatre. Honest, not a different lottery.
      showReveal(items[winner], 'Picked at random:');
      return;
    }

    spinning = true;
    spin.disabled = true;
    reveal.replaceChildren();
    const disc = stage.querySelector('.wheel__disc');
    rotation = rotationFor(winner, items.length, rotation);
    // Fast off the line, then a long decelerating tail — the difference between a spin and
    // a rotation.
    disc.style.transition = `transform ${SPIN_MS}ms cubic-bezier(.12, .75, .12, 1)`;
    requestAnimationFrame(() => { disc.style.transform = `rotate(${rotation}deg)`; });

    const done = () => {
      spinning = false;
      spin.disabled = false;
      spin.textContent = 'Spin again';
      showReveal(items[winner]);
    };
    disc.addEventListener('transitionend', done, { once: true });
    // A missed transitionend (tab hidden mid-spin) must not strand the button forever.
    setTimeout(() => { if (spinning) done(); }, SPIN_MS + 400);
  }

  for (const kind of KINDS) {
    const chip = Object.assign(document.createElement('button'), { className: 'chip', type: 'button', textContent: kind });
    chip.dataset.kind = kind;
    chip.addEventListener('click', () => { if (!spinning) { filter = kind; paint(); } });
    chips.append(chip);
  }
  spin.addEventListener('click', () => doSpin());

  page.append(
    Object.assign(document.createElement('p'), { className: 'section-title', textContent: "Can't decide" }),
    chips, stage,
    Object.assign(document.createElement('div'), { className: 'wheel__controls' }).appendChild(spin).parentElement,
    reveal,
  );
  paint();
  return page;
}
