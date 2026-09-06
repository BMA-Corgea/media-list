/**
 * T-14, AC2 — the queue's drag-reorder on every engine this host can run (Chromium and
 * Firefox; the webkit project stays wired in playwright.config.js so the gap stays visible,
 * see .autodev/specs/T-14.md), including the filtered case the plan calls out by name: a
 * reorder computed from what a `kind` filter shows must never touch a row the filter is
 * hiding (the id-not-index guarantee, kb/notes/handoff.md §6).
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
  // The request itself, so a spec can assert what the client SENT and not only what came
  // back — for the filtered case below that payload is the guarantee, in one object.
  return { url: response.url(), payload: response.request().postDataJSON() };
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

test('a reorder inside a kind filter uses the ids the filter SHOWS, never the unfiltered order', async ({ page, seed }) => {
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

  // An INTERIOR drop target, and that is the whole point of the gesture. Drop Anime A
  // between Anime B and Anime C — index 1 of the filtered list.
  //
  // Dropping at either END of the filtered view cannot tell the two implementations apart:
  // the first and last rows of the anime view are also the first and last anime rows of the
  // unfiltered queue, so `visible()` and `all` yield the SAME neighbour id and a green test
  // proves nothing (that is exactly how the previous version of this test passed with
  // `neighboursFor` reading the unfiltered array — round 1, F1). Interior is where the two
  // lists disagree: the row above index 1 is Anime B (30) in the filtered list and Movie M
  // (20) — a row the filter is hiding — in the unfiltered one.
  const fromBox = await rowLocator(page, animeA).boundingBox();
  const overBox = await rowLocator(page, animeB).boundingBox();

  const { url, payload } = await dragAndWaitForMove(page, {
    from: { x: fromBox.x + fromBox.width / 2, y: fromBox.y + fromBox.height / 2 },
    // Past Anime B's midpoint (so the drop index is 1) and well short of Anime C's, which
    // is a whole row lower — see `views/queue.js`'s midpoint scan during `pointermove`.
    to: { x: overBox.x + overBox.width / 2, y: overBox.y + overBox.height * 0.75 },
    steps: 15,
  });

  // 1. The guarantee, read straight off the wire: the only ids this move sent are ids of
  //    rows the filter was SHOWING. A hidden row's id appearing here IS the regression —
  //    no index was involved, but the neighbour was read from a list the user cannot see.
  expect(url).toContain(`/titles/${animeA}/move`);
  const sentIds = Object.entries(payload)
    .filter(([key]) => key === 'after_id' || key === 'before_id')
    .map(([, value]) => value)
    .filter((value) => value !== null && value !== undefined);
  expect(
    sentIds,
    `move sent ${JSON.stringify(payload)}; Anime B is ${animeB}, and the hidden rows are `
      + `Movie M ${movieM} / Movie N ${movieN}`,
  ).toEqual([animeB]);

  // 2. The result, read after a RELOAD rather than off the live DOM. `views/queue.js`
  //    reorders optimistically during the gesture, so between the move response landing and
  //    the repaint the list still shows the drop the user made — an assertion made in that
  //    window passes even when the server was told something else entirely. A reload has no
  //    such window: every row below comes from the database.
  await page.reload();
  await expect(page.locator('.qrow')).toHaveCount(5);

  // The whole queue, hidden rows included. Anime A landed in the gap its VISIBLE neighbour
  // defines — directly after Anime B — and Movie M and Movie N still sit exactly where they
  // sat, on either side of it. Read as ORDER, not as literal `queue_position` numbers: the
  // previous version asserted `queue_position === 20` and `=== 40`, which cannot fail for
  // any frontend bug (`backend/main.py::move_title` only ever UPDATEs the single moved row)
  // and would fail for a legitimate backend `_renumber`. Order is the thing actually
  // promised, and it does fail when the neighbour ids are wrong.
  expect(await visibleIds(page)).toEqual([movieM, animeB, animeA, movieN, animeC].map(String));

  await page.getByRole('button', { name: 'anime', exact: true }).click();
  await expect(page.locator('.qrow')).toHaveCount(3);
  expect(await visibleIds(page)).toEqual([animeB, animeA, animeC].map(String));
});
