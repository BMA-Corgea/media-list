/**
 * Pointer sequences shared by the carousel and queue specs.
 *
 * Both surfaces are built on real Pointer Events (`pointerdown`/`pointermove`/`pointerup`,
 * `setPointerCapture`) rather than HTML5 drag-and-drop, so these use `page.mouse` — Playwright
 * dispatches those through each engine's own input-injection path, which is what actually
 * produces trusted pointer events cross-engine (a synthetic `dispatchEvent` in page-context
 * JS would not).
 */

/**
 * Press, move in `steps` increments, optionally settle, then release. No pause between the
 * down and the first move — a slow first segment is what a real flick does not have.
 *
 * `settleMs` makes the release velocity-free, which is what a "where did you drop it" test
 * needs in order to isolate position handling from the momentum branch:
 *
 *   - `frontend/src/carousel.js` recomputes velocity on every `pointermove` as
 *     `-((event.clientX - lastX) / CARD_STEP) * (16 / dt)`. A move delivered at the SAME
 *     coordinates makes that first factor exactly 0, so velocity becomes exactly 0 no matter
 *     how fast the gesture was — one extra event, not an approximation.
 *   - The wait before it is load-bearing, not cosmetic: the app guards that line with
 *     `if (dt > 0)`. A settle move delivered inside the same millisecond as the last real
 *     move would be skipped entirely and the stale velocity would survive to `pointerup`.
 *
 * Measured on this host, five trials per engine, by instrumenting `carousel.js::endDrag` to
 * report its internal velocity at `pointerup` (T-14 round 2). WITHOUT the settle move the
 * app's own residual |velocity| was 0.0428–0.0446 (chromium) / 0.0303–0.0606 (firefox) for
 * the 90px/12-step gesture and 0.0221–0.0298 / 0.0216–0.0238 for the 40px/8-step one — above
 * `MIN_VELOCITY` (0.02) in **10 of 10** trials, i.e. the momentum branch was firing in both
 * of the tests whose comments said it could not. WITH it, |velocity| was 0.0000 in 10 of 10,
 * and the app's `pointermove` count went 12→13 and 8→9 on both engines, confirming neither
 * engine coalesces a zero-delta move away. See kb/wiki/lessons.md's T-14 entry.
 *
 * (There is deliberately no pause-only variant. Pausing before `pointerup` does NOT drop the
 * velocity in this app — nothing recomputes it between moves — so a parameter that only
 * waited would read like momentum control while changing nothing. The previous
 * `pauseBeforeUp`, which had no call sites at all, was exactly that.)
 */
export async function drag(page, { from, to, steps = 10, settleMs = 0 }) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps });
  if (settleMs > 0) {
    await page.waitForTimeout(settleMs);
    await page.mouse.move(to.x, to.y);
  }
  await page.mouse.up();
}
