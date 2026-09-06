/**
 * T-17 — "look before you commit": pressing a search result must open a description screen
 * that adds NOTHING (AC1/AC4), the description screen must have an explicit Add and a Back
 * that adds nothing (AC2), a `+` under each card must add directly (AC3), a no-art candidate
 * must render honestly rather than broken (AC5), and both the card and the plus button must
 * work from the keyboard (AC7).
 *
 * `/api/search`, `/api/details/*` and `POST /api/titles` are all stubbed at the BROWSER
 * network layer with `page.route` — this suite's server runs with fake TMDB/IGDB credentials
 * (tests/browser/global-setup.js) precisely so nothing here ever depends on, or could
 * accidentally reach, the real internet. `page.request` (used to read the real list back)
 * is a separate client that these routes do not touch, so "the list is unchanged" is read
 * from the real database every time, never from a mock.
 */
import { test, expect } from '../../frontend/browser-fixtures.js';

// A normal candidate: has art, is what most searches return.
const DUNE = {
  source: 'tmdb', source_id: '438631', media_type: 'movie',
  title: 'Dune', original_title: 'Dune', year: 2021, kind: 'movie',
  summary: 'Paul Atreides unites with the Fremen of Arrakis.',
  poster_url: 'https://image.tmdb.org/t/p/w500/dune.jpg',
  backdrop_url: 'https://image.tmdb.org/t/p/w1280/dune-bg.jpg',
  popularity: 500,
};

// AC5's real, reproducible fixture: TMDB tv/332437 — the announced "Dungeon Crawler Carl"
// adaptation the incident report names. Genuinely has neither a poster nor a backdrop.
const CARL_TV = {
  source: 'tmdb', source_id: '332437', media_type: 'tv',
  title: 'Dungeon Crawler Carl', original_title: null, year: null, kind: 'live-action',
  summary: 'An announced television adaptation.',
  poster_url: null, backdrop_url: null, popularity: 5,
};

// A game candidate (IGDB) — used once, to prove the description screen is kind-agnostic
// (AC6): the same view renders this with no branch on `kind`.
const HOLLOW_KNIGHT = {
  source: 'igdb', source_id: '9001', media_type: 'game',
  title: 'Hollow Knight', original_title: null, year: 2017, kind: 'game',
  summary: 'A vast ruined kingdom of insects and heroes.',
  poster_url: 'https://images.igdb.com/igdb/image/upload/t_cover_big/hk.jpg',
  backdrop_url: null, popularity: 80,
};

// AC6's real subject: ONE candidate, driven through the description screen as several
// kinds. Everything but `kind` is held fixed (same source, so even the `Source` fact is the
// same) and `source_id` varies only because the route and the details mock key off it.
// `book` is deliberately a kind this app does not have yet — T-16 puts books on this exact
// screen, and AC6 is the clause promising they land there without a branch in
// `views/candidate.js`.
const EVERY_KIND = ['live-action', 'movie', 'anime', 'game', 'book'];

function oneCandidateAs(kind, index) {
  return {
    source: 'tmdb', source_id: String(7000 + index), media_type: 'thing',
    title: 'One Candidate, Many Kinds', original_title: null, year: 2019, kind,
    summary: 'The same summary, whatever this thing turns out to be.',
    poster_url: 'https://image.tmdb.org/t/p/w500/same.jpg', backdrop_url: null, popularity: 1,
  };
}

/**
 * The whole rendered screen, with the kind's own NAME blanked out — i.e. everything
 * `views/candidate.js` puts on the page except the vocabulary `frontend/src/kinds.js`
 * owns. Two kinds whose shapes differ here differ structurally, which is exactly what AC6
 * forbids; comparing the markup rather than a hand-picked list of fields is the point
 * (round 2, F3 — the old test read four cosmetic fields and never looked at the body, so
 * `if (record.summary && record.kind !== 'game')` sailed straight past it).
 */
function renderedShape(page) {
  return page.evaluate(() => {
    const strip = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return `MISSING ${selector}`;
      const clone = node.cloneNode(true);
      for (const el of clone.querySelectorAll('.kind')) el.textContent = '<kind>';
      return clone.outerHTML;
    };
    return { hero: strip('.hero'), body: strip('.title__body') };
  });
}

function searchEnvelope(results) {
  const sources = {};
  for (const r of results) sources[r.source] = { ok: true, count: results.length };
  return { query: 'q', results, sources, disabled: [] };
}

/** `/api/details/<source>/<source_id>` echoes the candidate plus the fields only the
 * details endpoint adds (genres, imdb_id, detail, and the cached art paths). */
function detailsFor(candidate, extra = {}) {
  return {
    ...candidate,
    poster_path: candidate.poster_url,
    backdrop_path: candidate.backdrop_url,
    genres: [],
    imdb_id: null,
    detail: {},
    ...extra,
  };
}

/** Returns the `q` values actually sent to `/api/search`, in order — T-18's AC5 needs to
 * prove restoring a search costs no NEW round trip, which means counting the real ones. */
async function mockSearch(page, results) {
  const hits = [];
  await page.route('**/api/search**', (route) => {
    hits.push(new URL(route.request().url()).searchParams.get('q'));
    return route.fulfill({ json: searchEnvelope(results) });
  });
  return hits;
}

/** Like `mockSearch`, but a DIFFERENT result set per query text — T-18 AC3 needs to tell
 * "query A's grid" and "query B's grid" apart by more than just presence/absence. */
function mockSearchPerQuery(page, resultsByQuery) {
  const hits = [];
  return {
    hits,
    async install() {
      await page.route('**/api/search**', (route) => {
        const q = new URL(route.request().url()).searchParams.get('q');
        hits.push(q);
        return route.fulfill({ json: searchEnvelope(resultsByQuery[q] || []) });
      });
    },
  };
}

/** Returns the `<source>:<source_id>` keys the page actually asked for, so a test can
 * assert the description screen was NOT fetched as easily as that it was. */
async function mockDetails(page, byKey) {
  const hits = [];
  await page.route('**/api/details/**', (route) => {
    const url = new URL(route.request().url());
    // pathname is "/api/details/<source>/<source_id>" — split gives ['', 'api', 'details', source, id].
    const [, , , source, sourceId] = url.pathname.split('/');
    hits.push(`${source}:${sourceId}`);
    const record = byKey[`${source}:${sourceId}`];
    if (!record) return route.fulfill({ status: 404, json: { detail: `no fixture for ${source}:${sourceId}` } });
    return route.fulfill({ json: record });
  });
  return hits;
}

/** Records every POST to /api/titles and answers it with a fabricated stored row, without
 * ever letting the real backend re-fetch from a source (which is exactly the call this
 * suite must never make). */
function captureAdds(page, { id = 999 } = {}) {
  const posts = [];
  return {
    posts,
    async install() {
      await page.route('**/api/titles', async (route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        const payload = route.request().postDataJSON();
        posts.push(payload);
        return route.fulfill({
          status: 201,
          json: { id, title: payload.source_id === CARL_TV.source_id ? CARL_TV.title : 'Stored Title', status: 'queued', why: payload.why || null },
        });
      });
    },
  };
}

async function search(page, text) {
  await page.fill('#q', text);
  // The view debounces 250ms (add.js's DEBOUNCE_MS) before it calls /api/search.
  await page.waitForTimeout(350);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/#/add');
  await expect(page.locator('#q')).toBeVisible();
});

test('AC1/AC4 — pressing a card opens the description screen and adds nothing', async ({ page, seed }) => {
  const [existingId] = seed([{ title: 'Existing One', kind: 'movie' }]);
  const adds = captureAdds(page);
  await adds.install();
  await mockSearch(page, [DUNE]);
  await mockDetails(page, { 'tmdb:438631': detailsFor(DUNE) });

  await search(page, 'Dune');
  await expect(page.locator('.card__open')).toHaveCount(1);
  await page.locator('.card__open').click();

  await expect(page).toHaveURL(/#\/add\/tmdb\/438631\/movie$/);
  await expect(page.locator('.hero .title__name')).toHaveText('Dune');
  await expect(page.locator('.title__summary')).toContainText('Paul Atreides');

  // The whole point: reaching this screen must not itself have added anything.
  expect(adds.posts).toEqual([]);
  const titles = await page.request.get('/api/titles');
  const body = await titles.json();
  expect(body.map((t) => t.id)).toEqual([existingId]);
  expect(body[0].title).toBe('Existing One');
});

test('AC2 — Back adds nothing and returns to search; the browser\'s own back button works too', async ({ page, seed }) => {
  seed([]);
  const adds = captureAdds(page);
  await adds.install();
  await mockSearch(page, [DUNE]);
  await mockDetails(page, { 'tmdb:438631': detailsFor(DUNE) });

  await search(page, 'Dune');
  await page.locator('.card__open').click();
  await expect(page.locator('.hero .title__name')).toHaveText('Dune');

  await page.getByRole('button', { name: 'Back — add nothing' }).click();
  await expect(page).toHaveURL(/#\/add$/);
  expect(adds.posts).toEqual([]);

  // Reaching the screen again and using the browser's OWN back button must behave the same
  // way (T-17 locate F4: a real route makes this ordinary navigation, not a rescue). T-18
  // means "Back — add nothing" no longer lands on a guaranteed-empty screen — it restores
  // the 'Dune' search left behind above — but re-filling `#q` with the same text is a no-op
  // either way, so this is agnostic to which screen it landed on.
  await search(page, 'Dune');
  await page.locator('.card__open').click();
  await expect(page.locator('.hero .title__name')).toHaveText('Dune');
  await page.goBack();
  await expect(page).toHaveURL(/#\/add$/);
  expect(adds.posts).toEqual([]);
});

test('AC3 — the + button adds directly, stays put, and sends the same payload shape the description screen sends', async ({ page, seed }) => {
  seed([]);
  const adds = captureAdds(page);
  await adds.install();
  await mockSearch(page, [DUNE]);
  // Pressing `+` must never open the description screen, so this mock should never be hit.
  // It is installed precisely so that a regression cannot hide behind an unmocked call
  // (round 2, F2): with the nested-button trap kb/wiki/lessons.md records put back —
  // `open.append(add)` instead of `card.append(open, add)` — the `+` click also bubbles to
  // `.card__open` and navigates. With `/api/details` unmocked, that navigation was still in
  // flight against a request this server can only fail, while the mocked POST had already
  // answered; so the assertions below ran against the OLD, still-mounted screen and passed,
  // mid-navigation to a broken one.
  const detailHits = await mockDetails(page, { 'tmdb:438631': detailsFor(DUNE) });

  await search(page, 'Dune');
  const card = page.locator('.card--pick');
  await card.locator('.card__add').click();

  // The side effect that must NOT happen, asserted directly rather than inferred from
  // whichever piece of DOM the test happens to read first.
  await expect(page).toHaveURL(/#\/add$/);

  await expect(page.locator('.hint.ok')).toContainText('Added');
  await expect(card).toHaveClass(/is-added/);
  // Computed style, not stylesheet text (AC5's own constraint, applied here too): the
  // "added" outline actually resolves, it is not merely a rule that says it should.
  const outline = await card.locator('.poster').evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe('none');

  expect(adds.posts).toHaveLength(1);
  expect(adds.posts[0]).toMatchObject({ source: 'tmdb', source_id: '438631', media_type: 'movie' });
  expect(Object.keys(adds.posts[0]).sort()).toEqual(['media_type', 'source', 'source_id', 'why']);

  // Still on the search screen once everything has settled, and the description screen was
  // never so much as asked for.
  await expect(page).toHaveURL(/#\/add$/);
  expect(detailHits).toEqual([]);
});

test('AC3 — the description screen\'s Add sends the same payload shape as the + button', async ({ page, seed }) => {
  seed([]);
  const adds = captureAdds(page);
  await adds.install();
  await mockSearch(page, [DUNE]);
  await mockDetails(page, { 'tmdb:438631': detailsFor(DUNE) });

  await search(page, 'Dune');
  await page.locator('.card__open').click();
  await page.fill('#why', 'a friend swore by it');
  await page.getByRole('button', { name: 'Add to the list' }).click();

  await expect(page.locator('.hint.ok')).toContainText('Added');
  expect(adds.posts).toHaveLength(1);
  expect(adds.posts[0]).toMatchObject({ source: 'tmdb', source_id: '438631', media_type: 'movie', why: 'a friend swore by it' });
  // Same shape as the + button's payload (previous test) — one function, two doors (AC3).
  expect(Object.keys(adds.posts[0]).sort()).toEqual(['media_type', 'source', 'source_id', 'why']);
});

test('AC5 — a no-art candidate (TMDB tv/332437) renders honestly on the card and the description screen', async ({ page, seed }) => {
  seed([]);
  await mockSearch(page, [CARL_TV]);
  await mockDetails(page, { 'tmdb:332437': detailsFor(CARL_TV, { poster_path: null, backdrop_path: null, detail: { status: 'Planned' } }) });

  await search(page, 'Dungeon Crawler Carl');
  const poster = page.locator('.card--pick .poster').first();
  await expect(poster.locator('.poster__none')).toHaveText('no art');
  // Never a broken image and never a silent blank: no background-image was set at all.
  expect(await poster.evaluate((el) => getComputedStyle(el).backgroundImage)).toBe('none');

  await page.locator('.card__open').click();
  await expect(page.locator('.hero .title__name')).toHaveText('Dungeon Crawler Carl');
  const heroPoster = page.locator('.hero__poster');
  await expect(heroPoster.locator('.poster__none')).toHaveText('no art');
  expect(await heroPoster.evaluate((el) => getComputedStyle(el).backgroundImage)).toBe('none');
  await expect(page.locator('.hero')).not.toHaveClass(/hero--art/);
});

test('AC5 — the same no-art row, already on the list, renders honestly on its own title page', async ({ page, seed }) => {
  // Mirrors the owner's actual row (id 17 in his real list): a stored TMDB tv title with no
  // cached poster and no cached backdrop (T-17 locate F3 — this is "the row on his list",
  // not the search result).
  const [id] = seed([{
    title: 'Dungeon Crawler Carl', kind: 'live-action', source: 'tmdb', source_id: '332437',
    poster_path: null, backdrop_path: null,
  }]);
  await page.goto(`/#/title/${id}`);
  await expect(page.locator('.title__name')).toHaveText('Dungeon Crawler Carl');
  const heroPoster = page.locator('.hero__poster');
  await expect(heroPoster.locator('.poster__none')).toHaveText('no art');
  expect(await heroPoster.evaluate((el) => getComputedStyle(el).backgroundImage)).toBe('none');
});

test('AC6 — an IGDB game candidate renders on the same description screen with no per-kind branch', async ({ page, seed }) => {
  seed([]);
  await mockSearch(page, [HOLLOW_KNIGHT]);
  await mockDetails(page, { 'igdb:9001': detailsFor(HOLLOW_KNIGHT) });

  await search(page, 'Hollow Knight');
  await page.locator('.card__open').click();
  await expect(page).toHaveURL(/#\/add\/igdb\/9001\/game$/);
  await expect(page.locator('.hero .title__name')).toHaveText('Hollow Knight');
  await expect(page.locator('.hero .kind')).toHaveText('game');
  await expect(page.locator('.fact dd')).toHaveText('IGDB');
});

test('AC6 — the same candidate as every kind renders the identical screen, vocabulary aside', async ({ page, seed }) => {
  seed([]);
  const byKey = {};
  EVERY_KIND.forEach((kind, i) => {
    const candidate = oneCandidateAs(kind, i);
    byKey[`tmdb:${candidate.source_id}`] = detailsFor(candidate);
  });
  await mockDetails(page, byKey);

  const shapes = [];
  for (const [i, kind] of EVERY_KIND.entries()) {
    const candidate = oneCandidateAs(kind, i);
    await page.goto(`/#/add/tmdb/${candidate.source_id}/${candidate.media_type}`);

    // Positive first: an empty screen would be "identical" for every kind too, so each
    // kind has to actually render the whole thing before the comparison means anything.
    await expect(page.locator('.hero .title__name')).toHaveText(candidate.title);
    await expect(page.locator('.title__year')).toHaveText(String(candidate.year));
    await expect(page.locator('.title__summary')).toHaveText(candidate.summary);
    await expect(page.locator('.fact dd')).toHaveText('TMDB');
    await expect(page.locator('#why')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add to the list' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Back — add nothing' })).toBeVisible();

    // The one thing allowed to differ between kinds: the kind's own name.
    await expect(page.locator('.hero .kind')).toHaveText(kind);

    shapes.push({ kind, ...(await renderedShape(page)) });
  }

  const [first, ...rest] = shapes;
  for (const shape of rest) {
    expect(shape.hero, `the hero differs between "${first.kind}" and "${shape.kind}"`).toBe(first.hero);
    expect(shape.body, `the body differs between "${first.kind}" and "${shape.kind}"`).toBe(first.body);
  }
});

test('AC7 — the card and the + button both work from the keyboard', async ({ page, seed }) => {
  seed([]);
  const adds = captureAdds(page);
  await adds.install();
  await mockSearch(page, [DUNE]);
  await mockDetails(page, { 'tmdb:438631': detailsFor(DUNE) });

  await search(page, 'Dune');
  await page.locator('.card__open').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.hero .title__name')).toHaveText('Dune');
  expect(adds.posts).toEqual([]);

  await page.goBack();
  await search(page, 'Dune');
  await page.locator('.card__add').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.hint.ok')).toContainText('Added');
  expect(adds.posts).toHaveLength(1);
});

test('AC7 — a drag that starts on the + button never fires an add (T-5 pointer discipline)', async ({ page, seed }) => {
  seed([]);
  const adds = captureAdds(page);
  await adds.install();
  await mockSearch(page, [DUNE]);

  await search(page, 'Dune');
  const add = page.locator('.card__add');
  const box = await add.boundingBox();
  const startX = box.x + box.width / 2;
  const startY = box.y + box.height / 2;

  // Past the 6px threshold `views/add.js` enforces — a scroll or reorder attempt that
  // happens to start on the button, not a press.
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + 40, startY + 40, { steps: 10 });
  await page.mouse.up();

  expect(adds.posts).toEqual([]);
  await expect(page.locator('.card--pick')).not.toHaveClass(/is-adding|is-added/);
});

test('AC7 — an aborted drag on the + leaves it still answering the keyboard', async ({ page, seed }) => {
  seed([]);
  const adds = captureAdds(page);
  await adds.install();
  await mockSearch(page, [DUNE]);

  await search(page, 'Dune');
  const add = page.locator('.card__add');
  const box = await add.boundingBox();
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;

  // An ABORTED drag: out past the 6px threshold and back onto the button, released on it.
  // The add is correctly swallowed — that half is `AC7 — a drag that starts on the +`
  // above, and it is not what this test is about.
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 40, y + 40, { steps: 10 });
  await page.mouse.move(x, y, { steps: 10 });
  await page.mouse.up();
  expect(adds.posts).toEqual([]);

  // The gesture is over, so the button has to work again — including from the keyboard,
  // which fires no `pointerdown` and therefore never reset the old `moved` (round 2, F1).
  // The bug's whole signature is that nothing happens: no POST, no error, no change on
  // screen — exactly the silent failure this ticket exists to remove.
  await add.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.hint.ok')).toContainText('Added');
  expect(adds.posts).toHaveLength(1);
  expect(adds.posts[0]).toMatchObject({ source: 'tmdb', source_id: '438631', media_type: 'movie' });
});

/**
 * T-18 — "fix the back button too" (the owner, verbatim, after driving T-17). Pressing a
 * card opens a description screen (T-17); going back used to return to `#/add` with an
 * empty box and no results — measured live, not guessed (T-17's `live-feedback.md`:
 * `queryAfterBack: ""`, `resultsAfterBack: 0`). His workflow is look-decide-look-at-the-next,
 * and "Dungeon Crawler Carl" (a novel and a TV entry sharing a name) is exactly the case
 * comparing candidates exists for.
 */

test('T-18 AC1/AC5 — the browser back button restores the query and the grid it produced, with no new /api/search call', async ({ page, seed }) => {
  seed([]);
  const searchHits = await mockSearch(page, [DUNE]);
  await mockDetails(page, { 'tmdb:438631': detailsFor(DUNE) });

  await search(page, 'Dune');
  await expect(page.locator('.card__open')).toHaveCount(1);
  expect(searchHits).toEqual(['Dune']);

  await page.locator('.card__open').click();
  await expect(page.locator('.hero .title__name')).toHaveText('Dune');

  await page.goBack();
  await expect(page).toHaveURL(/#\/add$/);

  // AC1: the query AND the grid it produced are both back — no retyping.
  await expect(page.locator('#q')).toHaveValue('Dune');
  await expect(page.locator('.card__open')).toHaveCount(1);
  await expect(page.locator('.card__title')).toHaveText('Dune');

  // AC5: restoring it cost no new round trip — still exactly the one search from above.
  expect(searchHits).toEqual(['Dune']);
});

test('T-18 AC3 — leaving mid-debounce for a NEW query never restores the OLD query\'s grid under the new text', async ({ page, seed }) => {
  seed([]);
  const perQuery = mockSearchPerQuery(page, {
    // Two queries, two DIFFERENT, easily-told-apart result sets — standing in for the
    // Dungeon Crawler Carl novel-vs-TV case the ticket names: comparing candidates is the
    // whole point, so query A's card and query B's card must never be confusable.
    'Dungeon Crawler Carl': [CARL_TV],
    Carl: [DUNE],
  });
  await perQuery.install();
  await mockDetails(page, { 'tmdb:332437': detailsFor(CARL_TV) });

  await search(page, 'Dungeon Crawler Carl');
  await expect(page.locator('.card__open')).toHaveCount(1);
  await expect(page.locator('.card__title')).toHaveText('Dungeon Crawler Carl');

  // Edit the box to a different query and leave the view IMMEDIATELY — well inside the
  // 250ms debounce (add.js's DEBOUNCE_MS), so "Carl"'s search never reaches the network
  // before the navigation below tears this view down. The grid on screen at the moment of
  // the click is still query A's — that mismatch (box says "Carl", grid says A) is the
  // exact state the trap lives in.
  await page.fill('#q', 'Carl');
  await page.locator('.card__open').click();
  await expect(page).toHaveURL(/#\/add\/tmdb\/332437\/tv$/);

  await page.goBack();
  await expect(page).toHaveURL(/#\/add$/);

  // The box holds what was actually typed …
  await expect(page.locator('#q')).toHaveValue('Carl');
  // … and once things settle, the grid is query B's OWN result — freshly re-run, never A's
  // card wearing B's label.
  await expect(page.locator('.card__title')).toHaveText('Dune');
  // Proof it was actually RE-RUN, not silently served from the stale pair: two real
  // searches, "Carl" only after coming back, never a stray third from the cancelled timer.
  expect(perQuery.hits).toEqual(['Dungeon Crawler Carl', 'Carl']);
});

test('T-18 AC4 — a fresh #/add (no prior search this session) still shows an empty box and no results', async ({ page, seed }) => {
  seed([]);
  await expect(page.locator('#q')).toHaveValue('');
  await expect(page.locator('.card__open')).toHaveCount(0);
});
