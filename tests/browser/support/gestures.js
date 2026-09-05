/**
 * Pointer sequences shared by the carousel and queue specs.
 *
 * Both surfaces are built on real Pointer Events (`pointerdown`/`pointermove`/`pointerup`,
 * `setPointerCapture`) rather than HTML5 drag-and-drop, so these use `page.mouse` — Playwright
 * dispatches those through each engine's own input-injection path, which is what actually
 * produces trusted pointer events cross-engine (a synthetic `dispatchEvent` in page-context
 * JS would not).
 */

/** Press, move in `steps` increments, optionally pause, then release. No pause between the
 * down and the first move — a slow first segment is what a real flick does not have. */
export async function drag(page, { from, to, steps = 10, pauseBeforeUp = 0 }) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps });
  if (pauseBeforeUp > 0) await page.waitForTimeout(pauseBeforeUp);
  await page.mouse.up();
}
