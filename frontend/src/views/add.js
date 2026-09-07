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

/**
 * T-18: the one thing that survives `addView()`'s own unmount — the query and the results it
 * produced, kept as ONE value so they can never be shown paired with each other's opposite
 * number (AC3). Module scope, not a property on the page or a closure that dies with it: a
 * router-level route swap (`router.js`'s `replaceChildren`) destroys the DOM `addView()`
 * built, but the module itself stays loaded for the life of the app, so a `let` here is the
 * simplest thing that outlives one mount.
 *
 * Written from exactly one place: `page.cleanup()` below, at the T-15 unmount seam
 * (`router.js`'s `dismiss`) — the one guaranteed moment the live `input.value` and the last
 * verified `(query, data)` pair are both still readable, and the last moment before either
 * is gone. Never written mid-render, and never read as `input.value` — see `cleanup` for why.
 *
 * A hand-off between two mounts of the same view is only as good as the ORDER of the two
 * calls, and that order is the router's to keep, not this file's: `render()` dismisses the
 * outgoing view before it builds the incoming one, so this write always lands before the
 * next mount's read. It did not always — see the ordering note in `router.js` (T-18 round
 * 2, F1) before changing either side.
 */
let stash = null;

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
  // How far the pointer has travelled during the gesture currently in progress. It belongs
  // to ONE gesture and must not outlive it — see the click handler below.
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
  add.addEventListener('pointercancel', (event) => {
    releaseCapture(event);
    // A cancelled gesture (the browser took the pointer over for a scroll) synthesises no
    // click at all, so nothing downstream would ever clear `moved`. The gesture is over
    // here, so its distance ends here too.
    moved = 0;
  });
  add.addEventListener('click', (event) => {
    // A keyboard activation is a click with no pointer behind it (`detail === 0`); it
    // cannot be a drag, so it must never be judged by one (AC7).
    const fromPointer = event.detail > 0;
    const wasDrag = fromPointer && moved > DRAG_THRESHOLD;
    // Whichever way that went, the gesture that produced this click has ENDED and its
    // distance dies with it. `moved` used to be reset only in `pointerdown` (round 2, F1)
    // — so an aborted drag left the button deaf: the next Enter on it, which fires no
    // `pointerdown` at all, was swallowed by a gesture that had already finished, with no
    // POST, no error and nothing on screen to say so.
    moved = 0;
    // Past the threshold this was a gesture, not a press: swallow the click the browser
    // is about to synthesise, exactly as `carousel.js`'s `endDrag` does for a card open.
    if (wasDrag) { event.preventDefault(); return; }
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
             placeholder="Search a film, series, anime, game or book…" aria-label="Search for a title" />
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
  // This mount's own last SUCCESSFUL (query, data) pair — set only at the bottom of
  // `renderResults`, never from `input.value`. `cleanup()` is the only reader, and only at
  // the instant this view is torn down.
  let lastRun = null;

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

  // Paints the grid and the hint from an already-fetched search response — the ONE place
  // that turns `(query, data)` into pixels, so a fresh fetch (`run`) and a restored stash
  // (`addView`'s mount below) can never render it two different ways or drift out of sync.
  function renderResults(query, data) {
    results.replaceChildren(...data.results.map((c) => candidateCard(c, openCandidate, quickAdd)));

    const broken = Object.entries(data.sources || {}).filter(([, s]) => !s.ok);
    if (!data.results.length) say(`Nothing found for “${query}”.`);
    else if (broken.length) say(`${data.results.length} results — but ${broken.map(([n, s]) => `${n} failed (${s.error})`).join(', ')}`, 'bad');
    else if (data.disabled?.length) say(`${data.results.length} results. ${data.disabled.join(', ')} is not configured, so those are missing.`);
    else say(`${data.results.length} results. Click one to look, or press + to add it now.`);

    // T-18 AC3: recorded as trustworthy ONLY here, after a search that actually completed
    // (never aborted, never mid-flight) — this is the pairing `cleanup()` is allowed to
    // hand off to the next mount.
    lastRun = { query, data };
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
      renderResults(query, data);
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

  // T-18 AC1/AC3/AC5: restore what was on screen before this view was last torn down, if
  // anything was. Runs once, at mount, before the user has touched anything.
  if (stash) {
    input.value = stash.query;
    if (stash.data) {
      // Verified pair — repaint from it directly, no network round-trip (AC5).
      renderResults(stash.query, stash.data);
    } else {
      // The query survived but its results did not check out — re-run rather than showing
      // nothing, or worse, showing someone else's cards under this text (AC3).
      say('Searching…');
      run(stash.query);
    }
  }

  // T-15's unmount seam (`router.js`'s `dismiss`): the one guaranteed call, with the DOM
  // and `input.value` both still alive, right before this screen is gone for good.
  page.cleanup = () => {
    // Stop whatever this mount still has in the air. Left running, a debounced timer could
    // fire long after the user has moved on and silently overwrite `lastRun` — exactly how
    // a LATER mount's restore could end up built from an EARLIER, now-irrelevant search.
    if (inFlight) inFlight.abort();
    clearTimeout(timer);

    // What is actually on screen right now — read once, here, and nowhere else. Never
    // `input.value` read anywhere but this one moment (see the module-level `stash` doc).
    const query = input.value.trim();
    if (query.length < 2) {
      stash = null;
    } else if (lastRun && lastRun.query === query) {
      // The box and the grid still agree: hand the verified pair off whole.
      stash = lastRun;
    } else {
      // The box has moved past whatever last resolved (mid-debounce, or a request that was
      // still in flight — moot now that it is aborted above). The query text is still worth
      // keeping so the next mount does not have to be retyped, but it must not be paired
      // with stale results — the next mount re-runs it instead (AC3).
      stash = { query, data: null };
    }
  };

  queueMicrotask(() => input.focus());
  return page;
}
