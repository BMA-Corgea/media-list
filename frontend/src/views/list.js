/** The list, as a plain grid. T-5 replaces the home page with the carousel; this stays as
 *  the honest full view of everything that has been added. */

import { api } from '../api.js';
import { navigate } from '../router.js';

function titleCard(record, onRemove) {
  const card = document.createElement('article');
  card.className = 'card';

  const poster = document.createElement('div');
  poster.className = 'poster';
  if (record.poster_path) poster.style.backgroundImage = `url("${record.poster_path}")`;

  const remove = Object.assign(document.createElement('button'), {
    className: 'card__remove', type: 'button', textContent: '×', title: `Remove ${record.title}`,
  });
  remove.setAttribute('aria-label', `Remove ${record.title}`);
  remove.addEventListener('click', (event) => { event.stopPropagation(); onRemove(record); });

  const frame = document.createElement('div');
  frame.className = 'card__frame';
  frame.append(poster, remove);

  const title = Object.assign(document.createElement('span'), { className: 'card__title', textContent: record.title });
  const meta = document.createElement('span');
  meta.className = 'card__meta';
  meta.append(
    Object.assign(document.createElement('span'), { className: 'kind', textContent: record.kind }),
    document.createTextNode(` ${record.year || ''}`),
  );

  card.append(frame, title, meta);
  if (record.why) card.append(Object.assign(document.createElement('p'), { className: 'card__why', textContent: record.why }));
  return card;
}

export async function listView() {
  const page = document.createElement('main');
  page.className = 'page';

  let records = [];
  try {
    records = await api.titles();
  } catch (error) {
    page.innerHTML = `<div class="empty"><h2>Could not reach the list</h2><p>${error.message}</p></div>`;
    return page;
  }

  const heading = Object.assign(document.createElement('p'), {
    className: 'section-title',
    textContent: records.length ? `Up next — ${records.length}` : 'Up next',
  });
  page.append(heading);

  if (!records.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.innerHTML = `<h2>Nothing on the list yet</h2><p>Search for something and click its poster.</p>`;
    const go = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Add something' });
    go.addEventListener('click', () => navigate('/add'));
    empty.append(go);
    page.append(empty);
    return page;
  }

  const grid = document.createElement('div');
  grid.className = 'grid';
  const remove = async (record) => {
    await api.remove(record.id);
    navigate('/');
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  };
  grid.append(...records.map((r) => titleCard(r, remove)));
  page.append(grid);
  return page;
}
