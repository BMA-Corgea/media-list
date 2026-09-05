/** The Seen archive — a trophy case, not a graveyard. */

import { api } from '../api.js';
import { navigate } from '../router.js';
import { verbFor } from '../kinds.js';

const KINDS = ['all', 'anime', 'movie', 'live-action', 'game'];

export function starsEl(n, { interactive = false, onPick } = {}) {
  const wrap = document.createElement(interactive ? 'div' : 'span');
  wrap.className = interactive ? 'stars stars--pick' : 'stars';
  for (let i = 1; i <= 5; i += 1) {
    if (!interactive) {
      const s = document.createElement('span');
      s.className = i <= (n || 0) ? '' : 'off';
      s.textContent = '★';
      wrap.append(s);
      continue;
    }
    const b = Object.assign(document.createElement('button'), { type: 'button', textContent: '★' });
    b.className = i <= (n || 0) ? '' : 'off';
    b.setAttribute('aria-label', `${i} star${i > 1 ? 's' : ''}`);
    b.addEventListener('click', () => onPick(i));
    wrap.append(b);
  }
  return wrap;
}

export async function seenView() {
  const page = document.createElement('main');
  page.className = 'page';

  let all = [];
  try {
    all = await api.titles('seen');
  } catch (error) {
    page.innerHTML = `<div class="empty"><h2>Could not reach the archive</h2><p>${error.message}</p></div>`;
    return page;
  }

  let filter = 'all';
  let sort = 'date';

  const heading = Object.assign(document.createElement('p'), { className: 'section-title' });
  const chips = document.createElement('div');
  chips.className = 'nav filters';
  const sorter = document.createElement('div');
  sorter.className = 'nav filters';
  const grid = document.createElement('div');
  grid.className = 'grid grid--seen';

  const rows = () => {
    const list = filter === 'all' ? [...all] : all.filter((r) => r.kind === filter);
    return sort === 'rating'
      ? list.sort((a, b) => (b.stars || 0) - (a.stars || 0) || String(b.watched_at).localeCompare(String(a.watched_at)))
      : list;   // the API already returns most-recently-finished first
  };

  function card(record) {
    const item = document.createElement('article');
    item.className = 'card seen-card';

    const art = document.createElement('div');
    art.className = 'poster';
    if (record.poster_path) art.style.backgroundImage = `url("${record.poster_path}")`;
    art.addEventListener('click', () => navigate(`/title/${record.id}`));

    const line = document.createElement('div');
    line.className = 'seen-card__line';
    line.append(starsEl(record.stars), Object.assign(document.createElement('span'), {
      className: 'card__meta',
      textContent: record.watched_at ? new Date(record.watched_at).toLocaleDateString() : '',
    }));

    item.append(art, Object.assign(document.createElement('span'), { className: 'card__title', textContent: record.title }), line);
    if (record.review) item.append(Object.assign(document.createElement('p'), { className: 'card__why', textContent: `“${record.review}”` }));
    return item;
  }

  function paint() {
    const list = rows();
    heading.textContent = all.length ? `Seen — ${list.length}${filter === 'all' ? '' : ` ${filter}`}` : 'Seen';
    for (const chip of chips.children) chip.setAttribute('aria-pressed', String(chip.dataset.kind === filter));
    for (const chip of sorter.children) chip.setAttribute('aria-pressed', String(chip.dataset.sort === sort));
    grid.replaceChildren(...list.map(card));
  }

  for (const kind of KINDS) {
    const chip = Object.assign(document.createElement('button'), { className: 'chip', type: 'button', textContent: kind });
    chip.dataset.kind = kind;
    chip.addEventListener('click', () => { filter = kind; paint(); });
    chips.append(chip);
  }
  for (const [key, label] of [['date', 'most recent'], ['rating', 'best rated']]) {
    const chip = Object.assign(document.createElement('button'), { className: 'chip', type: 'button', textContent: label });
    chip.dataset.sort = key;
    chip.addEventListener('click', () => { sort = key; paint(); });
    sorter.append(chip);
  }

  const banner = document.createElement('div');
  banner.className = 'archive-banner';
  banner.innerHTML = `<h2>Everything you have finished</h2>
    <p>The shelf, not the bin — it is meant to be worth opening.</p>`;
  page.append(banner, heading, chips, sorter, grid);
  paint();

  if (!all.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.innerHTML = `<h2>Nothing here yet</h2><p>Finish something and rate it, and it lands here for good.</p>`;
    const go = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'See what is up next' });
    go.addEventListener('click', () => navigate('/'));
    empty.append(go);
    page.replaceChildren(banner, heading, empty);
  }
  return page;
}
