/**
 * T-14, AC2 — the coverflow wall on every engine this host can run (Chromium and Firefox;
 * the webkit project stays wired in playwright.config.js so the gap stays visible, see
 * .autodev/specs/T-14.md).
 *
 * This is the riskiest surface in the app: Pointer Events, `setPointerCapture`, and a 3D
 * transform recomputed every frame (frontend/src/carousel.js). Every assertion here reads a
 * COMPUTED style or a real DOM attribute — never stylesheet text (AC3) — so a browser that
 * silently disagrees about the geometry, or drops a custom property, fails loudly instead of
 * looking fine.
 */
import { test, expect } from '../../frontend/browser-fixtures.js';
import { drag } from './support/gestures.js';
import { parseMatrix } from './support/transform.js';

const TITLES = ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot', 'Golf', 'Hotel'];
const KINDS = ['movie', 'anime', 'game', 'live-action'];

test.beforeEach(async ({ page, seed }) => {
  seed(TITLES.map((title, index) => ({ title, kind: KINDS[index % KINDS.length] })));
  await page.goto('/');
  await expect(page.locator('.coverflow')).toBeVisible();
});

/** The card the wheel considers centred right now — by DOM state, not by an index we kept
 * on the test side (AC2: "the front card is the one the caption names"). */
function centreCard(page) {
  return page.locator('.cf-card.is-centre');
}

async function stageCentre(page) {
  const box = await page.locator('.coverflow__stage').boundingBox();
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test('renders the first title centred, and the caption names it', async ({ page }) => {
  await expect(centreCard(page)).toHaveAttribute('data-index', '0');
  await expect(page.locator('.caption__title')).toHaveText('Alpha');

  // Computed style, not the stylesheet: the centre card's 3D transform must actually
  // resolve to zero horizontal/depth offset, not merely have a rule that says it should.
  const transform = await centreCard(page).evaluate((el) => getComputedStyle(el).transform);
  const matrix = parseMatrix(transform);
  expect(matrix, `unparseable transform: ${transform}`).not.toBeNull();
  expect(Math.abs(matrix.translateX)).toBeLessThan(1);
  if (matrix.is3d) expect(Math.abs(matrix.translateZ)).toBeLessThan(1);
});

test('side buttons step exactly one card, never a compounding spin', async ({ page }) => {
  const next = page.getByRole('button', { name: 'Next title' });
  for (const expected of ['Bravo', 'Charlie', 'Delta']) {
    await next.click();
    await expect(page.locator('.caption__title')).toHaveText(expected);
  }
  await expect(centreCard(page)).toHaveAttribute('data-index', '3');

  const prev = page.getByRole('button', { name: 'Previous title' });
  await prev.click();
  await expect(page.locator('.caption__title')).toHaveText('Charlie');
});

test('keyboard steps match the buttons, including Home and End', async ({ page }) => {
  // `.click()` would land on a non-focusable `.cf-card` and blur the carousel instead of
  // focusing it (only the exact clicked element gets focus, not a focusable ancestor) — use
  // `.focus()` directly, same as the app's own `queueMicrotask` on load.
  await page.locator('.coverflow').focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('.caption__title')).toHaveText('Charlie');

  await page.keyboard.press('ArrowLeft');
  await expect(page.locator('.caption__title')).toHaveText('Bravo');

  await page.keyboard.press('End');
  await expect(page.locator('.caption__title')).toHaveText('Hotel');
  await expect(centreCard(page)).toHaveAttribute('data-index', String(TITLES.length - 1));

  await page.keyboard.press('Home');
  await expect(page.locator('.caption__title')).toHaveText('Alpha');
});

test('a drag past the halfway point advances exactly one card once velocity is zero', async ({ page }) => {
  const centre = await stageCentre(page);
  // CARD_STEP is 168px, so a 90px drag is position 90/168 = 0.536 — past the 0.5 (84px)
  // snap point, by arithmetic with no timing term in it. `settleMs` sends a real
  // zero-delta `pointermove` before `pointerup`, which forces the app's own velocity to
  // exactly zero (support/gestures.js documents the mechanism and the measurement), so this
  // is a pure "where did you drop it" case, deliberately free of momentum and isolated from
  // the next test's throw. Until T-14 round 2 `settleMs` was silently dropped by `drag()`
  // and this gesture actually released at |velocity| 0.030–0.061 — ABOVE MIN_VELOCITY
  // (0.02) on both engines — so the card was carried to ~0.96 by momentum and this test
  // passed for a reason its own comment denied.
  await drag(page, { from: centre, to: { x: centre.x - 90, y: centre.y }, steps: 12, settleMs: 60 });
  await expect(page.locator('.caption__title')).toHaveText('Bravo');
  await expect(centreCard(page)).toHaveAttribute('data-index', '1');
});

test('a quick flick carries further than an equal-distance drag with no velocity (momentum)', async ({ page }) => {
  const centre = await stageCentre(page);
  // 40px alone is position 40/168 = 0.238, well under the 0.5 snap point — a drag that ends
  // with zero velocity must fall back to the start card. `settleMs` is what makes that
  // velocity actually zero (see the test above and support/gestures.js); the throw below
  // deliberately omits it, and the contrast between the two is the whole test.
  await drag(page, { from: centre, to: { x: centre.x - 40, y: centre.y }, steps: 8, settleMs: 60 });
  await expect(page.locator('.caption__title')).toHaveText('Alpha');
  await expect(centreCard(page)).toHaveAttribute('data-index', '0');

  // The identical 40px, thrown fast, must carry past that same threshold on velocity alone
  // — this is the actual "throw" behaviour AC2 asks for. `steps: 1` (one decisive jump, not
  // several) is deliberate: the app's velocity term is computed ONLY from the delta since
  // the PREVIOUS pointermove (frontend/src/carousel.js), so with more than one intermediate
  // step, whichever step happens to land last dominates the throw — and measurement showed
  // that final inter-event gap swinging from ~5ms to ~150ms on both engines under Playwright
  // (steps > 1 asks the browser to schedule several synthetic moves, and the LAST one's
  // delivery jitter is what the app actually feels). A single jump has exactly one
  // measured segment, whose timing was consistently ~15ms on both engines — see
  // kb/wiki/lessons.md's T-14 entry for the full measurement.
  await drag(page, { from: centre, to: { x: centre.x - 40, y: centre.y }, steps: 1 });
  await expect
    .poll(async () => centreCard(page).getAttribute('data-index'), {
      message: 'a fast flick of the same distance should not settle back on the start card',
    })
    .not.toBe('0');
});

test('dragging suspends the card transition; releasing restores it (computed style)', async ({ page }) => {
  const card = page.locator('.cf-card').first();
  const idleDuration = await card.evaluate((el) => getComputedStyle(el).transitionDuration);
  expect(idleDuration).not.toBe('0s');

  const centre = await stageCentre(page);
  await page.mouse.move(centre.x, centre.y);
  await page.mouse.down();
  await page.mouse.move(centre.x - 30, centre.y, { steps: 5 });
  await expect(page.locator('.coverflow.is-dragging')).toBeVisible();

  // AC3: read the computed style WHILE the drag class is applied, not the rule that claims
  // it. A browser that needs an explicit reflow to drop a transition would fail exactly
  // here rather than in the stylesheet.
  const draggingDuration = await card.evaluate((el) => getComputedStyle(el).transitionDuration);
  expect(draggingDuration).toBe('0s');

  await page.mouse.up();
  await expect(page.locator('.coverflow.is-dragging')).toHaveCount(0);
  const restoredDuration = await page.locator('.cf-card').first().evaluate((el) => getComputedStyle(el).transitionDuration);
  expect(restoredDuration).not.toBe('0s');
});
