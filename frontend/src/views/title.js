/** One title, as a page worth landing on. */

import { api } from '../api.js';
import { navigate } from '../router.js';
import { verbFor } from '../kinds.js';
import { starsEl } from './seen.js';

/** A label/value pair, or nothing at all. Never renders an empty label. */
function fact(label, value) {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return null;
  const item = document.createElement('div');
  item.className = 'fact';
  item.append(
    Object.assign(document.createElement('dt'), { textContent: label }),
    Object.assign(document.createElement('dd'), { textContent: Array.isArray(value) ? value.join(' · ') : String(value) }),
  );
  return item;
}

/** The per-kind detail line. Screen titles and games carry different things entirely. */
function facts(record) {
  const d = record.detail || {};
  const list = document.createElement('dl');
  list.className = 'facts';

  const items = record.kind === 'game'
    ? [fact('Developer', d.developer), fact('Platforms', d.platforms), fact('Genres', record.genres)]
    : record.kind === 'book'
    ? [fact('Author', d.author), fact('Pages', d.pages), fact('Genres', record.genres)]
    : [
        fact('Studio', d.studio),
        fact('Season', d.season),
        fact('Episodes', d.episodes),
        fact('Runtime', d.runtime ? `${d.runtime} min` : null),
        fact('Status', d.status),
        fact('Genres', record.genres),
      ];

  const kept = items.filter(Boolean);
  if (!kept.length) return null;
  list.append(...kept);
  return list;
}

/** Romaji and English, without repeating one that equals the other or the main title. */
function altTitles(record) {
  const d = record.detail || {};
  const seen = new Set([record.title]);
  const names = [];
  for (const candidate of [d.title_english, d.title_romaji, record.original_title]) {
    if (candidate && !seen.has(candidate)) { seen.add(candidate); names.push(candidate); }
  }
  if (!names.length) return null;
  return Object.assign(document.createElement('p'), { className: 'title__alt', textContent: names.join(' · ') });
}

function notFound(id) {
  const page = document.createElement('main');
  page.className = 'page';
  page.innerHTML = `<div class="empty"><h2>No such title</h2><p>Nothing on your list has id ${id}. It may have been removed.</p></div>`;
  const back = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Back to the wall' });
  back.addEventListener('click', () => navigate('/'));
  page.querySelector('.empty').append(back);
  return page;
}

export async function titleView(id) {
  let record;
  try {
    record = await api.title(id);
  } catch (error) {
    if (error.status === 404) return notFound(id);
    const page = document.createElement('main');
    page.className = 'page';
    page.innerHTML = `<div class="empty"><h2>Could not load that title</h2><p>${error.message}</p></div>`;
    return page;
  }

  const verb = verbFor(record.kind);
  const page = document.createElement('main');
  page.className = 'page page--title';

  // ── hero ──────────────────────────────────────────────────────────────────────────
  const hero = document.createElement('section');
  hero.className = 'hero';
  if (record.backdrop_path) {
    hero.classList.add('hero--art');
    hero.style.backgroundImage = `url("${record.backdrop_path}")`;
  }
  hero.append(Object.assign(document.createElement('div'), { className: 'scrim' }));

  const poster = document.createElement('div');
  poster.className = 'poster hero__poster';
  // T-17 AC5: this is the exact gap the incident report named — a stored row with no
  // poster (TMDB tv/332437 has neither a poster nor a backdrop) used to render a blank box
  // here, which reads as broken rather than as "this source has no image".
  if (record.poster_path) poster.style.backgroundImage = `url("${record.poster_path}")`;
  else poster.append(Object.assign(document.createElement('span'), { className: 'poster__none', textContent: 'no art' }));

  const head = document.createElement('div');
  head.className = 'hero__head';
  head.append(
    Object.assign(document.createElement('span'), { className: 'kind', textContent: record.kind }),
    Object.assign(document.createElement('h1'), { className: 'title__name', textContent: record.title }),
  );
  const alt = altTitles(record);
  if (alt) head.append(alt);
  if (record.year) head.append(Object.assign(document.createElement('p'), { className: 'title__year', textContent: record.year }));

  hero.append(poster, head);
  page.append(hero);

  // ── body ──────────────────────────────────────────────────────────────────────────
  const body = document.createElement('section');
  body.className = 'title__body';

  if (record.summary) body.append(Object.assign(document.createElement('p'), { className: 'title__summary', textContent: record.summary }));

  const detail = facts(record);
  if (detail) body.append(detail);

  // ── why: the user's own words, editable in place ──────────────────────────────────
  const whyBlock = document.createElement('div');
  whyBlock.className = 'why';
  const render = () => {
    whyBlock.replaceChildren();
    const label = Object.assign(document.createElement('p'), { className: 'section-title', textContent: 'Why it is on the list' });
    const text = Object.assign(document.createElement('p'), {
      className: record.why ? 'why__text' : 'why__text why__text--empty',
      textContent: record.why ? `“${record.why}”` : 'No reason recorded.',
    });
    const edit = Object.assign(document.createElement('button'), { className: 'btn btn--ghost', textContent: record.why ? 'Edit' : 'Add a reason' });
    edit.addEventListener('click', () => {
      const field = Object.assign(document.createElement('input'), { className: 'field', type: 'text', maxLength: 140, value: record.why || '' });
      const save = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Save' });
      const cancel = Object.assign(document.createElement('button'), { className: 'btn btn--ghost', textContent: 'Cancel' });
      save.addEventListener('click', async () => {
        save.disabled = true;
        record = await api.patch(record.id, { why: field.value });
        render();
      });
      cancel.addEventListener('click', render);
      const row = document.createElement('div');
      row.className = 'why__edit';
      row.append(field, save, cancel);
      whyBlock.replaceChildren(label, row);
      field.focus();
    });
    whyBlock.append(label, text, edit);
  };
  render();
  body.append(whyBlock);

  // ── actions ───────────────────────────────────────────────────────────────────────
  const actions = document.createElement('div');
  actions.className = 'actions';

  if (record.link) {
    const link = Object.assign(document.createElement('a'), {
      className: 'btn', href: record.link, target: '_blank', rel: 'noreferrer noopener',
      textContent: `View on ${record.link_label}`,
    });
    actions.append(link);
  }
  // No link row at all when there is nothing to link to — never a dead link.

  // ── rating ────────────────────────────────────────────────────────────────────────
  const rating = document.createElement('div');
  rating.className = 'rating';

  function renderRating() {
    rating.replaceChildren();
    if (record.status === 'seen') {
      const row = document.createElement('div');
      row.className = 'rating__row';
      // Re-rating is just picking again; there is no separate edit mode for a score.
      row.append(
        starsEl(record.stars, { interactive: true, onPick: async (n) => { record = await api.patch(record.id, { stars: n }); renderRating(); } }),
        Object.assign(document.createElement('span'), {
          className: 'card__meta',
          textContent: record.watched_at ? `${verb.past} ${new Date(record.watched_at).toLocaleDateString()}` : verb.past,
        }),
      );

      const review = Object.assign(document.createElement('textarea'), {
        className: 'field', rows: 3, maxLength: 1000,
        placeholder: `What did you think? (optional)`, value: record.review || '',
      });
      const save = Object.assign(document.createElement('button'), { className: 'btn', textContent: 'Save review' });
      save.addEventListener('click', async () => {
        save.disabled = true; save.textContent = 'Saved';
        record = await api.patch(record.id, { review: review.value });
        setTimeout(() => { save.disabled = false; save.textContent = 'Save review'; }, 1200);
      });

      const undo = Object.assign(document.createElement('button'), { className: 'btn btn--ghost', textContent: 'Put it back in the queue' });
      undo.addEventListener('click', async () => {
        undo.disabled = true;
        record = await api.patch(record.id, { status: 'queued' });
        renderRating();
      });

      rating.append(
        Object.assign(document.createElement('p'), { className: 'section-title', textContent: 'Your verdict' }),
        row, review,
        Object.assign(document.createElement('div'), { className: 'actions' }),
      );
      rating.lastElementChild.append(save, undo);
      return;
    }

    const prompt = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: verb.imperative });
    prompt.addEventListener('click', () => {
      const ask = document.createElement('div');
      ask.className = 'rating__ask';
      ask.append(
        Object.assign(document.createElement('p'), { className: 'section-title', textContent: `How was it? (required)` }),
        // A rating is required, so picking a star IS the action — no separate confirm button
        // to leave a half-finished state behind.
        starsEl(0, { interactive: true, onPick: async (n) => {
          record = await api.patch(record.id, { stars: n, status: 'seen' });
          renderRating();
        } }),
      );
      rating.replaceChildren(ask);
    });
    rating.append(prompt);
  }
  renderRating();

  const top = Object.assign(document.createElement('button'), { className: 'btn', textContent: 'Move to top of queue' });
  if (record.status === 'seen') top.hidden = true;
  top.addEventListener('click', async () => {
    top.disabled = true;
    await api.patch(record.id, { move_to_top: true });
    navigate('/');
  });

  const remove = Object.assign(document.createElement('button'), { className: 'btn btn--ghost', textContent: 'Remove from list' });
  remove.addEventListener('click', async () => {
    remove.disabled = true;
    await api.remove(record.id);
    navigate('/');
  });

  actions.append(top, remove);
  body.append(rating, actions);
  page.append(body);
  return page;
}
