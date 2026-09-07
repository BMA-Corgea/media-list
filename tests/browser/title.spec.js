/**
 * T-16 round 2, F2 and F8 — a book's own title page.
 *
 * F2 (AC1 unmet): `views/title.js`'s `facts()` branched `game` vs. everything else, and a
 * book took the screen-title branch (Studio, Season, Episodes, Runtime, Status) — all null
 * for a book, so the author `openlibrary.details` already stores never reached the screen.
 * This asserts the ACTUAL RENDERED FACT, not a grep of the source for the word "Author".
 *
 * F8 — `tests/test_books.py::test_a_book_gets_read_not_finished_in_the_kind_map` greps
 * `kinds.js` for a line starting `book:` containing `'read'`; it never calls `verbFor`,
 * never renders anything, and would stay green if `verbFor` stopped consulting `VERBS`
 * entirely. The real assertion belongs here: open a book's page and read the ACTUAL button
 * text and the ACTUAL past-tense text once it is marked read — both are
 * `frontend/src/kinds.js`'s VERBS map, read by the running app, not by this test file.
 */
import { test, expect } from '../../frontend/browser-fixtures.js';

function seedBook(seed, overrides = {}) {
  const [id] = seed([{
    title: 'The Dispossessed',
    kind: 'book',
    source: 'openlibrary',
    source_id: 'OL59863W',
    summary: 'Shevek, a brilliant physicist, attempts to reconcile two worlds.',
    detail: {
      author: 'Ursula K. Le Guin',
      pages: 341,
      openlibrary_url: 'https://openlibrary.org/works/OL59863W',
    },
    status: 'queued',
    ...overrides,
  }]);
  return id;
}

/** The `.fact` div whose `<dt>` is exactly `label`, so a page with several facts (Author,
 * Pages, Genres) never falls back to "whichever `.fact dd` happens to be first". */
function factByLabel(page, label) {
  return page.locator('.fact').filter({ has: page.locator('dt', { hasText: label }) });
}

test('F2/AC1 — a book renders its author and page count, not the screen-title facts', async ({ page, seed }) => {
  const id = seedBook(seed);
  await page.goto(`/#/title/${id}`);

  await expect(page.locator('.title__name')).toHaveText('The Dispossessed');
  await expect(page.locator('.title__summary')).toContainText('Shevek');

  await expect(factByLabel(page, 'Author').locator('dd')).toHaveText('Ursula K. Le Guin');
  await expect(factByLabel(page, 'Pages').locator('dd')).toHaveText('341');

  // The screen-title branch's facts must NOT render for a book — proof this took the BOOK
  // branch rather than falling through to "everything else" (the exact shape of the bug).
  await expect(page.locator('dt', { hasText: 'Studio' })).toHaveCount(0);
  await expect(page.locator('dt', { hasText: 'Episodes' })).toHaveCount(0);
});

test('F8 — the mark-as-read verb is genuinely consulted, both before and after', async ({ page, seed }) => {
  const id = seedBook(seed);
  await page.goto(`/#/title/${id}`);

  // Queued: the button reads verbFor('book').imperative ("Mark as read"). If `kinds.js`
  // ever lost its `book` entry, this would read the FALLBACK's "Mark as finished" instead —
  // exactly the regression the grep test cannot see.
  const prompt = page.getByRole('button', { name: 'Mark as read', exact: true });
  await expect(prompt).toBeVisible();
  await prompt.click();

  await expect(page.locator('.rating__ask .section-title')).toHaveText('How was it? (required)');
  // Picking a star IS the action for a fresh rating — the 4th star, 1-indexed.
  await page.locator('.rating__ask .stars--pick button').nth(3).click();

  // Now "seen": the past tense next to the stars is the SAME map entry's `.past`, read from
  // the live page, not from a string embedded in this test.
  await expect(page.locator('.rating .card__meta')).toContainText('read');
  await expect(page.locator('.rating .card__meta')).not.toContainText('finished');
  await expect(page.getByRole('button', { name: 'Put it back in the queue' })).toBeVisible();
});
