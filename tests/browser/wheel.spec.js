/**
 * T-14, AC2 — the wheel on all three engines: a full spin completes and lands on the title
 * the reveal announces.
 *
 * `pickIndex`/`rotationFor`/`segmentAt` (frontend/src/wheel.js) are deliberately DOM-free, so
 * this file imports `segmentAt` directly (Node's ESM loader resolves it exactly like a
 * browser would — no bundler in the way) to turn the disc's own COMPUTED final rotation
 * back into a wedge index, rather than trusting a number this test invented. That is the
 * actual proof of AC2's "the landed title equals the announced one": the geometry the
 * browser rendered has to agree with the title the reveal panel shows, on all three engines.
 */
import { test, expect } from '../../frontend/browser-fixtures.js';
import { parseMatrix } from './support/transform.js';
import { segmentAt } from '../../frontend/src/wheel.js';

const ITEMS = [
  { title: 'Wheel One', kind: 'movie' },
  { title: 'Wheel Two', kind: 'anime' },
  { title: 'Wheel Three', kind: 'game' },
  { title: 'Wheel Four', kind: 'live-action' },
  { title: 'Wheel Five', kind: 'movie' },
  { title: 'Wheel Six', kind: 'anime' },
  // T-16 round 2, F3/F4: two books, so this suite actually exercises the fifth kind rather
  // than only the four that predate it. Two, like anime and movie above — a lone wedge
  // exercises a pre-existing single-item wheel-geometry edge case this ticket does not own.
  { title: 'Wheel Seven', kind: 'book' },
  { title: 'Wheel Eight', kind: 'book' },
];

test.beforeEach(async ({ page, seed }) => {
  seed(ITEMS);
  await page.goto('/#/wheel');
  await expect(page.locator('.wheel__disc')).toBeVisible();
});

/** Click Spin, wait out the long decelerating transition, and read back the disc's real
 * final rotation from its COMPUTED transform (AC3) — never the `rotation` variable the app
 * happens to hold, which would only prove the app agrees with itself. */
async function spinAndRead(page) {
  await page.getByRole('button', { name: 'Spin', exact: true }).click();
  // SPIN_MS is 4400ms plus a 400ms missed-transitionend fallback; 8s leaves real margin for
  // three different engines' timer/animation scheduling.
  await expect(page.locator('.reveal__card')).toBeVisible({ timeout: 8000 });

  const transformValue = await page.locator('.wheel__disc').evaluate((el) => getComputedStyle(el).transform);
  const matrix = parseMatrix(transformValue);
  expect(matrix, `unparseable disc transform: ${transformValue}`).not.toBeNull();

  const revealedTitle = await page.locator('.reveal__title').textContent();
  return { rotationDeg: matrix.rotationDeg, revealedTitle };
}

test('a full spin completes and lands on the title the reveal announces', async ({ page }) => {
  const { rotationDeg, revealedTitle } = await spinAndRead(page);
  const landedIndex = segmentAt(rotationDeg, ITEMS.length);
  expect(ITEMS[landedIndex].title).toBe(revealedTitle);
});

test('spinning inside a kind filter still lands on the announced title', async ({ page }) => {
  await page.getByRole('button', { name: 'anime', exact: true }).click();
  const eligible = ITEMS.filter((item) => item.kind === 'anime');
  await expect(page.locator('.wheel__disc .wheel__wedge')).toHaveCount(eligible.length);

  const { rotationDeg, revealedTitle } = await spinAndRead(page);
  const landedIndex = segmentAt(rotationDeg, eligible.length);
  expect(eligible[landedIndex].title).toBe(revealedTitle);
});

// ── T-16 round 2, F3/F4: the fifth kind ───────────────────────────────────────────────────

test('F3 — a book chip exists and spinning inside it still lands on the announced title', async ({ page }) => {
  const chip = page.getByRole('button', { name: 'book', exact: true });
  await expect(chip).toBeVisible();
  await chip.click();
  const eligible = ITEMS.filter((item) => item.kind === 'book');
  await expect(page.locator('.wheel__disc .wheel__wedge')).toHaveCount(eligible.length);

  const { rotationDeg, revealedTitle } = await spinAndRead(page);
  const landedIndex = segmentAt(rotationDeg, eligible.length);
  expect(eligible[landedIndex].title).toBe(revealedTitle);
});

test('F4 — a book wedge never shares anime\'s computed colour', async ({ page }) => {
  // Every wedge, `all` filter, so both kinds sit on the disc at once and their
  // COMPUTED fills (the `var(--wheel-*)` resolved by the browser, not the attribute text)
  // can be compared directly.
  await expect(page.locator('.wheel__disc .wheel__wedge')).toHaveCount(ITEMS.length);

  const fillFor = (kind) => {
    const index = ITEMS.findIndex((item) => item.kind === kind);
    return page.locator('.wheel__disc .wheel__wedge').nth(index).evaluate((el) => getComputedStyle(el).fill);
  };

  const animeFill = await fillFor('anime');
  const bookFill = await fillFor('book');
  expect(animeFill).not.toBe('none');
  expect(bookFill).not.toBe('none');
  expect(bookFill, `book resolved to the same fill as anime: ${bookFill}`).not.toBe(animeFill);
});
