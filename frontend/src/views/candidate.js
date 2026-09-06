/**
 * The description screen for a search result — not yet a row on the list.
 *
 * T-17, AC1: reaching this screen is the whole effect of pressing a card in `views/add.js`.
 * Landing here adds NOTHING; the only way onto the list from here is the Add button below,
 * and it calls the exact same `addCandidate` the search grid's `+` button calls (AC3) — this
 * screen is a second DOOR onto adding, never a second implementation of it.
 *
 * AC6: kind-agnostic on purpose. Nothing here branches on `record.kind` — a game candidate
 * from IGDB and a show candidate from TMDB render through the same cover/summary/facts
 * shape, and T-16's books land on this same screen without touching this file.
 */

import { api } from '../api.js';
import { navigate } from '../router.js';
import { addCandidate } from '../add-candidate.js';

const SOURCE_LABEL = { tmdb: 'TMDB', igdb: 'IGDB' };

function fact(label, value) {
  if (value === null || value === undefined || value === '') return null;
  const item = document.createElement('div');
  item.className = 'fact';
  item.append(
    Object.assign(document.createElement('dt'), { textContent: label }),
    Object.assign(document.createElement('dd'), { textContent: value }),
  );
  return item;
}

function problem(source, sourceId, message) {
  const page = document.createElement('main');
  page.className = 'page';
  page.innerHTML = `<div class="empty"><h2>Could not load that title</h2><p>${message}</p></div>`;
  const back = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Back to search' });
  back.addEventListener('click', () => navigate('/add'));
  page.querySelector('.empty').append(back);
  return page;
}

export async function candidateView(source, sourceId, mediaType) {
  const page = document.createElement('main');
  page.className = 'page page--title';

  const controller = new AbortController();
  // T-15's unmount hook (router.js `dismiss`): leaving before the fetch resolves must
  // cancel it, the same way `transfer.js` cancels its preview.
  page.cleanup = () => controller.abort();

  let record;
  try {
    record = await api.details(source, sourceId, mediaType, controller.signal);
  } catch (error) {
    if (error.name === 'AbortError') return page; // the screen is already gone
    return problem(source, sourceId, error.message);
  }

  // ── hero: cover, kind, title, year ───────────────────────────────────────────────────
  const hero = document.createElement('section');
  hero.className = 'hero';
  if (record.backdrop_path) {
    hero.classList.add('hero--art');
    hero.style.backgroundImage = `url("${record.backdrop_path}")`;
  }
  hero.append(Object.assign(document.createElement('div'), { className: 'scrim' }));

  const poster = document.createElement('div');
  poster.className = 'poster hero__poster';
  // AC5: a real, reproducible no-art candidate (TMDB tv/332437) has neither a poster nor a
  // backdrop. The card in `views/add.js` already says so honestly instead of a broken
  // image or a blank box; this screen has to say the same thing for the same reason.
  if (record.poster_path) poster.style.backgroundImage = `url("${record.poster_path}")`;
  else poster.append(Object.assign(document.createElement('span'), { className: 'poster__none', textContent: 'no art' }));

  const head = document.createElement('div');
  head.className = 'hero__head';
  head.append(
    Object.assign(document.createElement('span'), { className: 'kind', textContent: record.kind }),
    Object.assign(document.createElement('h1'), { className: 'title__name', textContent: record.title }),
  );
  if (record.year) head.append(Object.assign(document.createElement('p'), { className: 'title__year', textContent: record.year }));

  hero.append(poster, head);
  page.append(hero);

  // ── body ──────────────────────────────────────────────────────────────────────────
  const body = document.createElement('section');
  body.className = 'title__body';

  if (record.summary) body.append(Object.assign(document.createElement('p'), { className: 'title__summary', textContent: record.summary }));

  const facts = document.createElement('dl');
  facts.className = 'facts';
  const sourceFact = fact('Source', SOURCE_LABEL[record.source] || record.source);
  if (sourceFact) facts.append(sourceFact);
  if (facts.children.length) body.append(facts);

  // The one text input in this whole flow (T-17's decision — see the handoff): typing why
  // it's on the list happens HERE, deliberately, not on the quick `+` door.
  const whyLabel = Object.assign(document.createElement('p'), { className: 'section-title', textContent: 'Why it is on the list' });
  const why = Object.assign(document.createElement('input'), {
    className: 'field', type: 'text', maxLength: 140, id: 'why',
    placeholder: 'why? (optional — who recommended it, what hooked you)',
  });
  why.setAttribute('aria-label', 'Why you want to watch it');
  body.append(whyLabel, why);

  const hint = Object.assign(document.createElement('p'), { className: 'hint' });

  // ── actions: Add, and a Back that adds nothing (AC2) ────────────────────────────────
  const actions = document.createElement('div');
  actions.className = 'actions';
  const add = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Add to the list' });
  const back = Object.assign(document.createElement('button'), { className: 'btn btn--ghost', textContent: 'Back — add nothing' });
  back.addEventListener('click', () => navigate('/add'));

  add.addEventListener('click', async () => {
    add.disabled = true;
    back.disabled = true;
    add.textContent = 'Adding…';
    try {
      const stored = await addCandidate(record, why.value);
      hint.textContent = `Added ${stored.title}. It is at the end of your queue.`;
      hint.className = 'hint ok';
      actions.replaceChildren();
      const view = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'View it on your list' });
      view.addEventListener('click', () => navigate(`/title/${stored.id}`));
      const another = Object.assign(document.createElement('button'), { className: 'btn btn--ghost', textContent: 'Add another' });
      another.addEventListener('click', () => navigate('/add'));
      actions.append(view, another);
    } catch (error) {
      hint.textContent = error.status === 409 ? error.message : `Could not add that — ${error.message}`;
      hint.className = 'hint bad';
      add.disabled = false;
      back.disabled = false;
      add.textContent = 'Add to the list';
    }
  });

  actions.append(add, back);
  body.append(actions, hint);
  page.append(body);
  return page;
}
