/** The wall — the carousel, plus the caption for whatever is centred. */

import { api } from '../api.js';
import { navigate } from '../router.js';
import { createCarousel } from '../carousel.js';

export async function homeView() {
  const page = document.createElement('main');
  page.className = 'page page--wall';

  let items = [];
  try {
    items = await api.titles('queued');
  } catch (error) {
    page.innerHTML = `<div class="empty"><h2>Could not reach the list</h2><p>${error.message}</p></div>`;
    return page;
  }

  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.innerHTML = `<h2>Nothing on the list yet</h2>
      <p>Search for a film, series, anime or game and click its poster. Everything else fills itself in.</p>`;
    const go = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Add something' });
    go.addEventListener('click', () => navigate('/add'));
    empty.append(go);
    page.append(Object.assign(document.createElement('p'), { className: 'section-title', textContent: 'Up next' }), empty);
    return page;
  }

  const caption = document.createElement('div');
  caption.className = 'caption';

  const carousel = createCarousel({
    items,
    onOpen: (item) => navigate(`/title/${item.id}`),
    onSelect: (item, index) => {
      caption.innerHTML = '';
      const line = document.createElement('div');
      line.className = 'caption__line';
      line.append(
        Object.assign(document.createElement('span'), { className: 'kind', textContent: item.kind }),
        Object.assign(document.createElement('h2'), { className: 'caption__title', textContent: item.title }),
        Object.assign(document.createElement('span'), { className: 'caption__year', textContent: item.year || '' }),
      );
      caption.append(line);
      if (item.why) caption.append(Object.assign(document.createElement('p'), { className: 'caption__why', textContent: `“${item.why}”` }));
      caption.append(Object.assign(document.createElement('p'), {
        className: 'caption__pos', textContent: `${index + 1} of ${items.length}`,
      }));
    },
  });

  page.append(
    Object.assign(document.createElement('p'), { className: 'section-title', textContent: 'Up next' }),
    carousel.element,
    caption,
  );
  queueMicrotask(() => carousel.element.focus({ preventScroll: true }));
  return page;
}
