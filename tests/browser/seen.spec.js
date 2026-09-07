/**
 * T-16 round 2, F3 — `book` was missing from the seen archive's kind filter chips too:
 * visible under `all` (the filter is `filter === 'all' ? all : all.filter(...)`, so nothing
 * hid it), but with no chip to narrow the archive down to it. This is the browser-level
 * proof the chip exists and actually narrows the grid, not a grep of `kinds.js`'s source.
 */
import { test, expect } from '../../frontend/browser-fixtures.js';

test('F3 — a seen book can be filtered to in the archive', async ({ page, seed }) => {
  seed([
    { title: 'Seen Movie', kind: 'movie', status: 'seen', stars: 5, watched_at: '2026-01-01T00:00:00+00:00' },
    { title: 'Seen Book', kind: 'book', status: 'seen', stars: 4, watched_at: '2026-01-02T00:00:00+00:00' },
  ]);
  await page.goto('/#/seen');
  await expect(page.locator('.seen-card')).toHaveCount(2);

  const chip = page.getByRole('button', { name: 'book', exact: true });
  await expect(chip).toBeVisible();
  await chip.click();

  await expect(page.locator('.seen-card')).toHaveCount(1);
  await expect(page.locator('.seen-card .card__title')).toHaveText('Seen Book');
});
