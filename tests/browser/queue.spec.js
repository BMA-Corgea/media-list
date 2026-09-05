/**
 * T-14, AC2 — the queue's drag-reorder on all three engines, including the filtered case
 * the plan calls out by name: a reorder computed from what a `kind` filter shows must never
 * touch a row the filter is hiding (the id-not-index guarantee, kb/notes/handoff.md §6).
 */
import { test, expect } from '../../frontend/browser-fixtures.js';
import { drag } from './support/gestures.js';

function rowLocator(page, id) {
  return page.locator(`.qrow[data-id="${id}"]`);
}

function visibleIds(page) {
  return page.locator('.qrow').evaluateAll((rows) => rows.map((row) => row.dataset.id));
}

/**
 * Perform the drag AND wait for the resulting `POST .../move` to actually complete.
 *
 * The DOM reorders optimistically the moment a drag crosses a sibling's midpoint (see
 * `views/queue.js`'s `insertBefore` during `pointermove`) — well before `commit()`'s
 * `api.move()` round-trip lands. Checking the DOM (or, worse, the server) right after
 * `drag()` returns is a race: on a fast round-trip it happens to pass, but nothing
 * guarantees the request has landed. `page.waitForResponse` has to be armed BEFORE the
 * gesture starts (Promise.all, not sequential awaits), or a response that arrives between
 * arming and starting the drag would be missed.
 */
async function dragAndWaitForMove(page, options) {
  const [response] = await Promise.all([
    page.waitForResponse((res) => res.url().includes('/move') && res.request().method() === 'POST'),
    drag(page, options),
  ]);
  if (!response.ok()) {
    throw new Error(`move request failed: ${response.status()} ${await response.text()}`);
  }
}

test('drag-reorder persists across a reload', async ({ page, seed }) => {
  const [a, b, c] = seed([
    { title: 'Row A', kind: 'movie' },
    { title: 'Row B', kind: 'movie' },
    { title: 'Row C', kind: 'movie' },
  ]);
  await page.goto('/#/queue');
  await expect(page.locator('.qrow')).toHaveCount(3);
  expect(await visibleIds(page)).toEqual([String(a), String(b), String(c)]);

  const fromBox = await rowLocator(page, a).boundingBox();
  const toBox = await rowLocator(page, c).boundingBox();

  // Row A, dragged past the bottom of row C, must land last.
  await dragAndWaitForMove(page, {
    from: { x: fromBox.x + fromBox.width / 2, y: fromBox.y + fromBox.height / 2 },
    to: { x: toBox.x + toBox.width / 2, y: toBox.y + toBox.height + 20 },
    steps: 15,
  });

  await expect.poll(() => visibleIds(page)).toEqual([String(b), String(c), String(a)]);

  await page.reload();
  await expect(page.locator('.qrow')).toHaveCount(3);
  expect(await visibleIds(page)).toEqual([String(b), String(c), String(a)]);
});

test('reordering inside a kind filter moves the right neighbour and never touches a hidden row', async ({ page, seed }) => {
  const [animeA, movieM, animeB, movieN, animeC] = seed([
    { title: 'Anime A', kind: 'anime', queue_position: 10 },
    { title: 'Movie M', kind: 'movie', queue_position: 20 },
    { title: 'Anime B', kind: 'anime', queue_position: 30 },
    { title: 'Movie N', kind: 'movie', queue_position: 40 },
    { title: 'Anime C', kind: 'anime', queue_position: 50 },
  ]);

  await page.goto('/#/queue');
  await expect(page.locator('.qrow')).toHaveCount(5);

  await page.getByRole('button', { name: 'anime', exact: true }).click();
  await expect(page.locator('.qrow')).toHaveCount(3);
  expect(await visibleIds(page)).toEqual([String(animeA), String(animeB), String(animeC)]);

  // Drag the LAST visible row (Anime C) above the FIRST (Anime A) — entirely inside the
  // filtered view. Movie M and Movie N sit between them in the real order and are hidden by
  // the filter for the whole gesture.
  const fromBox = await rowLocator(page, animeC).boundingBox();
  const toBox = await rowLocator(page, animeA).boundingBox();

  await dragAndWaitForMove(page, {
    from: { x: fromBox.x + fromBox.width / 2, y: fromBox.y + fromBox.height / 2 },
    to: { x: toBox.x + toBox.width / 2, y: toBox.y - 5 },
    steps: 15,
  });

  await expect.poll(() => visibleIds(page)).toEqual([String(animeC), String(animeA), String(animeB)]);

  const all = await page.evaluate(() => fetch('/api/titles?status=queued').then((response) => response.json()));
  const byId = Object.fromEntries(all.map((row) => [row.id, row]));

  // The guarantee itself: rows the filter was hiding kept the exact position they already
  // had, byte-for-byte, because the move only ever sent the ids of rows it could SEE.
  expect(byId[movieM].queue_position).toBe(20);
  expect(byId[movieN].queue_position).toBe(40);

  const [posC, posA, posB] = [animeC, animeA, animeB].map((id) => byId[id].queue_position);
  expect(posC).toBeLessThan(posA);
  expect(posA).toBeLessThan(posB);
});
