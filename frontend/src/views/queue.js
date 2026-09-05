/**
 * The queue — one global order, filterable by kind.
 *
 * The owner's explicit choice: ONE queue, not a queue per genre. The filter chips narrow what is
 * on screen and never fork the order. That is why a move sends the ids of the rows it can
 * SEE rather than an index: the server places the title next to exactly those two, and every
 * row the filter is hiding keeps the position it already had.
 */

import { api } from '../api.js';
import { navigate } from '../router.js';

const KINDS = ['all', 'anime', 'movie', 'live-action', 'game'];
const DRAG_THRESHOLD = 6;

export async function queueView() {
  const page = document.createElement('main');
  page.className = 'page';

  let all = [];
  try {
    all = await api.titles('queued');
  } catch (error) {
    page.innerHTML = `<div class="empty"><h2>Could not reach the queue</h2><p>${error.message}</p></div>`;
    return page;
  }

  let filter = 'all';
  const visible = () => (filter === 'all' ? all : all.filter((r) => r.kind === filter));

  const heading = Object.assign(document.createElement('p'), { className: 'section-title' });
  const chips = document.createElement('div');
  chips.className = 'nav filters';
  const list = document.createElement('ol');
  list.className = 'queue';

  // ── rows ────────────────────────────────────────────────────────────────────────────
  function row(record, index) {
    const item = document.createElement('li');
    item.className = 'qrow';
    item.dataset.id = String(record.id);
    item.tabIndex = 0;

    const handle = Object.assign(document.createElement('span'), { className: 'qrow__handle', textContent: '⠿' });
    handle.setAttribute('aria-hidden', 'true');
    const rank = Object.assign(document.createElement('span'), { className: 'qrow__rank', textContent: index + 1 });

    const art = document.createElement('span');
    art.className = 'qrow__art';
    if (record.poster_path) art.style.backgroundImage = `url("${record.poster_path}")`;

    const text = document.createElement('span');
    text.className = 'qrow__text';
    const line = document.createElement('span');
    line.className = 'qrow__line';
    line.append(
      Object.assign(document.createElement('span'), { className: 'qrow__title', textContent: record.title }),
      Object.assign(document.createElement('span'), { className: 'kind', textContent: record.kind }),
      Object.assign(document.createElement('span'), { className: 'card__meta', textContent: record.year || '' }),
    );
    text.append(line);
    if (record.why) text.append(Object.assign(document.createElement('span'), { className: 'qrow__why', textContent: record.why }));

    const open = Object.assign(document.createElement('button'), { className: 'btn btn--ghost qrow__open', textContent: 'Open' });
    open.addEventListener('click', (event) => { event.stopPropagation(); navigate(`/title/${record.id}`); });

    item.append(handle, rank, art, text, open);
    item.setAttribute('aria-label', `${index + 1}. ${record.title}. Alt plus arrow keys to reorder.`);
    return item;
  }

  function paint() {
    const rows = visible();
    heading.textContent = rows.length
      ? `${rows.length} ${filter === 'all' ? 'queued' : filter} — drag to reorder`
      : `Nothing ${filter === 'all' ? 'queued' : `in ${filter}`}`;
    list.replaceChildren(...rows.map(row));
    for (const chip of chips.children) chip.setAttribute('aria-pressed', String(chip.dataset.kind === filter));
  }

  for (const kind of KINDS) {
    const chip = Object.assign(document.createElement('button'), { className: 'chip', type: 'button', textContent: kind });
    chip.dataset.kind = kind;
    chip.addEventListener('click', () => { filter = kind; paint(); });
    chips.append(chip);
  }

  // ── moving a title ──────────────────────────────────────────────────────────────────
  async function commit(id, neighbours) {
    all = await api.move(id, neighbours);
    paint();
  }

  /** Neighbours in the VISIBLE list — never an index, so hidden rows are untouched. */
  function neighboursFor(id, targetIndex) {
    const rows = visible().filter((r) => r.id !== id);
    const above = rows[targetIndex - 1];
    const below = rows[targetIndex];
    return above ? { after_id: above.id } : { before_id: below?.id ?? null };
  }

  // ── drag ────────────────────────────────────────────────────────────────────────────
  let dragging = null;
  let startY = 0;
  let moved = 0;
  let placeholderIndex = 0;

  list.addEventListener('pointerdown', (event) => {
    const item = event.target.closest('.qrow');
    if (!item || event.target.closest('button')) return;
    dragging = item;
    startY = event.clientY;
    moved = 0;
    placeholderIndex = [...list.children].indexOf(item);
    list.setPointerCapture(event.pointerId);
    item.classList.add('is-dragging');
  });

  list.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const dy = event.clientY - startY;
    moved = Math.max(moved, Math.abs(dy));
    if (moved < DRAG_THRESHOLD) return;
    dragging.style.transform = `translateY(${dy}px)`;

    const siblings = [...list.children].filter((n) => n !== dragging);
    let index = 0;
    for (const node of siblings) {
      const box = node.getBoundingClientRect();
      if (event.clientY > box.top + box.height / 2) index += 1;
    }
    if (index !== placeholderIndex) {
      placeholderIndex = index;
      const reference = siblings[index] ?? null;
      list.insertBefore(dragging, reference);
      // The element moved under the cursor, so the offset it is translating from changed.
      startY = event.clientY;
      dragging.style.transform = '';
    }
  });

  async function endDrag(event) {
    if (!dragging) return;
    const item = dragging;
    dragging = null;
    list.releasePointerCapture(event.pointerId);
    item.classList.remove('is-dragging');
    item.style.transform = '';
    // Same lesson the carousel taught: below the threshold this was a click, not a gesture.
    if (moved < DRAG_THRESHOLD) return;
    await commit(Number(item.dataset.id), neighboursFor(Number(item.dataset.id), placeholderIndex));
  }
  list.addEventListener('pointerup', endDrag);
  list.addEventListener('pointercancel', endDrag);

  // ── keyboard: reordering must work without a mouse ─────────────────────────────────
  list.addEventListener('keydown', async (event) => {
    if (!event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return;
    const item = event.target.closest('.qrow');
    if (!item) return;
    event.preventDefault();

    const id = Number(item.dataset.id);
    const rows = visible();
    const from = rows.findIndex((r) => r.id === id);
    const to = event.key === 'ArrowUp' ? from - 1 : from + 1;
    if (to < 0 || to >= rows.length) return;

    await commit(id, neighboursFor(id, to));
    const again = list.querySelector(`.qrow[data-id="${id}"]`);
    again?.focus();
  });

  page.append(heading, chips, list);
  paint();

  if (!all.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.innerHTML = `<h2>Nothing queued</h2><p>Add something and it lands at the end of this list.</p>`;
    const go = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Add something' });
    go.addEventListener('click', () => navigate('/add'));
    empty.append(go);
    page.append(empty);
  }
  return page;
}
