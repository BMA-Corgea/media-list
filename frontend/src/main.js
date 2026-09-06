/**
 * media-list — app shell.
 *
 * Owns the bar and the router outlet; every screen lives in `views/` and registers a route.
 */

import { skinPicker } from './skins.js';
import { route, start, navigate, current } from './router.js';
import { queueView } from './views/queue.js';
import { wheelView } from './views/wheel.js';
import { seenView } from './views/seen.js';
import { transferView } from './views/transfer.js';
import { homeView } from './views/home.js';
import { titleView } from './views/title.js';
import { addView } from './views/add.js';
import { candidateView } from './views/candidate.js';

const NAV = [
  { path: '', label: 'Up next' },
  { path: 'queue', label: 'The queue' },
  { path: 'wheel', label: "Can't decide" },
  { path: 'seen', label: 'Seen' },
  { path: 'add', label: 'Add' },
  { path: 'transfer', label: 'Import' },
];

function shell() {
  const bar = document.createElement('header');
  bar.className = 'topbar';

  const brand = Object.assign(document.createElement('button'), { className: 'brand', type: 'button' });
  brand.innerHTML = 'media<em>·</em>list';
  brand.addEventListener('click', () => navigate('/'));

  const nav = document.createElement('nav');
  nav.className = 'nav';
  for (const item of NAV) {
    const link = Object.assign(document.createElement('button'), { className: 'chip', type: 'button', textContent: item.label });
    link.dataset.path = item.path;
    link.addEventListener('click', () => navigate(`/${item.path}`));
    nav.append(link);
  }

  bar.append(brand, nav, Object.assign(document.createElement('span'), { className: 'grow' }), skinPicker());
  return { bar, nav };
}

route('', homeView);
route('queue', queueView);
route('wheel', wheelView);
route('seen', seenView);
route('add', addView);
route('transfer', transferView);
route(/^title\/(\d+)$/, titleView);
// A candidate has no database id yet (T-17 locate F4), so it cannot reuse the route above.
// `source_id` is opaque (TMDB and IGDB ids are both numeric strings today, but nothing
// requires that), so it is matched permissively; `media_type` is the one TMDB actually
// needs and every candidate carries one regardless of source (tmdb.search: 'movie'/'tv',
// igdb.search: always 'game').
route(/^add\/([^/]+)\/([^/]+)\/([^/]+)$/, candidateView);

const app = document.querySelector('#app');
const { bar, nav } = shell();
const outlet = document.createElement('div');
app.replaceChildren(bar, outlet);

start(outlet, (path) => {
  for (const link of nav.children) {
    link.setAttribute('aria-pressed', String(link.dataset.path === path));
  }
});
