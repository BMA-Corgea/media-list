/**
 * Add a title — search and pick.
 *
 * The one rule this view exists to honour: THE USER NEVER TYPES METADATA. There is exactly
 * one text input for content here, and it is `why`. Everything else arrives from the source
 * when a poster is clicked.
 */

import { api } from '../api.js';
import { navigate } from '../router.js';

const DEBOUNCE_MS = 250;

function candidateCard(candidate, onPick) {
  const card = document.createElement('button');
  card.className = 'card card--pick';
  card.type = 'button';

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

  card.append(poster, title, meta);
  card.addEventListener('click', () => onPick(candidate, card));
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
      <input class="field field--why" id="why" type="text" maxlength="140"
             placeholder="why? (optional — who recommended it, what hooked you)" aria-label="Why you want to watch it" />
    </div>
    <p class="hint" id="hint">Type a few words. Click a poster to add it — nothing else to fill in.</p>
    <div class="grid" id="results"></div>
  `;

  const input = page.querySelector('#q');
  const why = page.querySelector('#why');
  const hint = page.querySelector('#hint');
  const results = page.querySelector('#results');

  let timer = null;
  let inFlight = null;

  const say = (text, tone = '') => {
    hint.textContent = text;
    hint.className = `hint ${tone}`;
  };

  async function pick(candidate, card) {
    card.disabled = true;
    card.classList.add('is-adding');
    try {
      const stored = await api.add({
        source: candidate.source,
        source_id: candidate.source_id,
        // Carried through deliberately: TMDB movie and tv ids are separate namespaces, and a
        // stored title that forgets which one it came from cannot be refreshed later.
        media_type: candidate.media_type,
        why: why.value,
      });
      say(`Added ${stored.title}. It is at the end of your queue.`, 'ok');
      card.classList.add('is-added');
      why.value = '';
    } catch (error) {
      say(error.status === 409 ? error.message : `Could not add that — ${error.message}`, 'bad');
      card.disabled = false;
      card.classList.remove('is-adding');
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
      results.replaceChildren(...data.results.map((c) => candidateCard(c, pick)));

      const broken = Object.entries(data.sources || {}).filter(([, s]) => !s.ok);
      if (!data.results.length) say(`Nothing found for “${query}”.`);
      else if (broken.length) say(`${data.results.length} results — but ${broken.map(([n, s]) => `${n} failed (${s.error})`).join(', ')}`, 'bad');
      else if (data.disabled?.length) say(`${data.results.length} results. ${data.disabled.join(', ')} is not configured, so those are missing.`);
      else say(`${data.results.length} results. Click one.`);
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
      say('Type a few words. Click a poster to add it — nothing else to fill in.');
      return;
    }
    say('Searching…');
    timer = setTimeout(() => run(query), DEBOUNCE_MS);
  });

  queueMicrotask(() => input.focus());
  return page;
}
