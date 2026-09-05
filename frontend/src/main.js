/**
 * media-list — app entry.
 *
 * T-2 ships the shell: the bar, the skin switcher, and an honest empty state. Every surface
 * this app will grow (T-5's carousel, T-6's title page, T-7's queue, T-8's wheel, T-9's
 * archive) mounts into `#app` and reaches for the component classes in `skins/base.css`
 * rather than declaring colours of its own.
 */

import { skinPicker } from './skins.js';

async function health() {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error(String(response.status));
    return await response.json();
  } catch {
    return null;
  }
}

function topbar() {
  const bar = document.createElement('header');
  bar.className = 'topbar';
  bar.innerHTML = `
    <span class="brand">media<em>·</em>list</span>
    <span class="grow"></span>
  `;
  bar.append(skinPicker());
  return bar;
}

function emptyState(status) {
  const section = document.createElement('main');
  section.className = 'page';

  // Say what is actually true rather than implying a finished app with no data in it.
  const sources = status?.sources ?? {};
  const missing = Object.entries(sources)
    .filter(([, present]) => !present)
    .map(([name]) => name);

  section.innerHTML = `
    <p class="section-title">Up next</p>
    <div class="empty">
      <h2>Nothing on the list yet</h2>
      <p>The wall fills up once you can add things to it — that arrives with search-and-pick.</p>
      ${missing.length ? `<p style="margin-top:14px"><span class="kind">waiting on credentials</span> ${missing.join(', ')}</p>` : ''}
    </div>
  `;
  return section;
}

async function main() {
  const app = document.querySelector('#app');
  const status = await health();
  app.replaceChildren(topbar(), emptyState(status));
}

main();
