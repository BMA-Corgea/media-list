/**
 * Add a title — search, then look before you commit.
 *
 * T-17: a card used to BE the add — one press on a poster committed the candidate straight
 * to the list, no preview, no way to notice a wrong match before it landed (see
 * .autodev/specs/T-17.md's incident). Now a card is a preview onto the description screen
 * (`views/candidate.js`) that adds NOTHING, and a separate `+` button underneath it is the
 * only thing on this page that adds directly — for when the owner already knows what he
 * wants. Both doors call the same `addCandidate` (AC3); neither implements adding itself.
 */

import { api } from '../api.js';
import { navigate } from '../router.js';
import { addCandidate } from '../add-candidate.js';

const DEBOUNCE_MS = 250;
// px of pointer movement before a press on the `+` button is a drag, not a tap (T-5's
// discipline) — a scroll or reorder gesture that happens to start on the button must never
// fire an add.
const DRAG_THRESHOLD = 6;

function candidateCard(candidate, onOpen, onQuickAdd) {
  const card = document.createElement('div');
  card.className = 'card card--pick';

  // The open door: everything but the `+` button lives inside this real <button>, so the
  // whole preview area is one keyboard-reachable control (AC7) that never adds anything.
  const open = document.createElement('button');
  open.type = 'button';
  open.className = 'card__open';
  open.setAttribute('aria-label', `${candidate.title} — see details before adding`);

  const poster = document.createElement('div');
  poster.className = 'poster';
  if (candidate.poster_url) poster.style.backgroundImage = `url("${candidate.poster_url}")`;
  else poster.append(Object.assign(document.createElement('span'), { className: 'poster__none', textContent: 'no art' }));

  const title = Object.assign(document.createElement('span'), { className: 'card__title', textContent: candidate.title });
  const meta = document.createElement('span');
  meta.className = 'card__meta';
  meta.append(
    Object.assign(document.createElement('span'), { className: 'kind', textContent: candidate.kind }),
    document.createTextNode(` ${candidate.year || ''}`),
  );

  open.append(poster, title, meta);
  open.addEventListener('click', () => onOpen(candidate));

  // The quick door: a real <button>, never a click handler on a div (AC7).
  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'card__add';
  add.textContent = '+ Add';
  add.setAttribute('aria-label', `Add ${candidate.title} directly, without opening its description`);

  let startX = 0;
  let startY = 0;
  let moved = 0;
  add.addEventListener('pointerdown', (event) => {
    startX = event.clientX;
    startY = event.clientY;
    moved = 0;
    // Captured so movement is measured accurately even once the pointer leaves the
    // button's own box — the same reason `carousel.js` captures on its stage.
    try { add.setPointerCapture(event.pointerId); } catch { /* not every pointer type supports capture */ }
  });
  add.addEventListener('pointermove', (event) => {
    if (!add.hasPointerCapture?.(event.pointerId)) return;
    moved = Math.max(moved, Math.hypot(event.clientX - startX, event.clientY - startY));
  });
  const releaseCapture = (event) => {
    try { add.releasePointerCapture(event.pointerId); } catch { /* already released */ }
  };
  add.addEventListener('pointerup', releaseCapture);
  add.addEventListener('pointercancel', releaseCapture);
  add.addEventListener('click', (event) => {
    // Past the threshold this was a gesture, not a press: swallow the click the browser
    // is about to synthesise, exactly as `carousel.js`'s `endDrag` does for a card open.
    if (moved > DRAG_THRESHOLD) { event.preventDefault(); return; }
    onQuickAdd(candidate, add, card);
  });

  card.append(open, add);
  return card;
}

export async function addView() {
  const page = document.createElement('main');
  page.className = 'page';
  page.innerHTML = `
    <p class="section-title">Add to the list</p>
    <div class="addbar">
      <input class="field" id="q" type="search" autocomplete="off" spellcheck="false"
             placeholder="Search a film, series, anime or game…" aria-label="Search for a title" />
    </div>
    <p class="hint" id="hint">Type a few words. Click a card to see it before you add it, or
      press its <strong>+</strong> to add it straight away.</p>
    <div class="grid" id="results"></div>
  `;

  const input = page.querySelector('#q');
  const hint = page.querySelector('#hint');
  const results = page.querySelector('#results');

  let timer = null;
  let inFlight = null;

  const say = (text, tone = '') => {
    hint.textContent = text;
    hint.className = `hint ${tone}`;
  };

  function openCandidate(candidate) {
    // AC1: this is the WHOLE effect of pressing a card. Nothing is added, nothing is sent
    // — just a navigation, to a route the candidate's source/id/media_type describe.
    navigate(`/add/${encodeURIComponent(candidate.source)}/${encodeURIComponent(candidate.source_id)}/${encodeURIComponent(candidate.media_type || '')}`);
  }

  async function quickAdd(candidate, button, card) {
    button.disabled = true;
    card.classList.add('is-adding');
    try {
      const stored = await addCandidate(candidate);
      say(`Added ${stored.title}. It is at the end of your queue.`, 'ok');
      card.classList.remove('is-adding');
      card.classList.add('is-added');
    } catch (error) {
      say(error.status === 409 ? error.message : `Could not add that — ${error.message}`, 'bad');
      card.classList.remove('is-adding');
      button.disabled = false;
    }
  }

  async function run(query) {
    // Abandon whatever is still in the air. Without this, a slow early response can land
    // after a fast later one and the grid answers a query the user has already typed past.
    if (inFlight) inFlight.abort();
    const controller = new AbortController();
    inFlight = controller;

    try {
      const data = await api.search(query, controller.signal);
      if (controller.signal.aborted) return;
      results.replaceChildren(...data.results.map((c) => candidateCard(c, openCandidate, quickAdd)));

      const broken = Object.entries(data.sources || {}).filter(([, s]) => !s.ok);
      if (!data.results.length) say(`Nothing found for “${query}”.`);
      else if (broken.length) say(`${data.results.length} results — but ${broken.map(([n, s]) => `${n} failed (${s.error})`).join(', ')}`, 'bad');
      else if (data.disabled?.length) say(`${data.results.length} results. ${data.disabled.join(', ')} is not configured, so those are missing.`);
      else say(`${data.results.length} results. Click one to look, or press + to add it now.`);
    } catch (error) {
      if (error.name === 'AbortError') return;
      say(`Search failed — ${error.message}`, 'bad');
    }
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 2) {
      results.replaceChildren();
      say('Type a few words. Click a card to see it before you add it, or press its + to add it straight away.');
      return;
    }
    say('Searching…');
    timer = setTimeout(() => run(query), DEBOUNCE_MS);
  });

  queueMicrotask(() => input.focus());
  return page;
}
