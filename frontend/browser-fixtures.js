/**
 * The one file allowed to `import ... from '@playwright/test'` outside playwright.config.js.
 *
 * It has to live here, inside `frontend/`, rather than next to the specs in
 * `tests/browser/`: `@playwright/test` is installed into `frontend/node_modules` (AC1 — a
 * real devDependency, not the borrowed sibling-project install), and Node resolves a bare
 * specifier by walking UP from the importing file's own directory. A file under
 * `tests/browser/` has no such ancestor. Relative imports don't have that restriction, which
 * is why the specs reach this file (and it reaches `tests/browser/support/db.js`) by path
 * rather than by package name.
 *
 * `seed` is this suite's `clean_db` + `insert_title` (tests/conftest.py) in one call: wipe
 * the shared scratch database and write exactly the rows this test needs. Every spec in a
 * run shares one server and one database (see playwright.config.js's `workers: 1`), so nothing
 * here depends on another test's leftovers, or leaves any behind for the next one.
 */
import { test as base, expect } from '@playwright/test';
import { resetAndSeed } from '../tests/browser/support/db.js';

export const test = base.extend({
  seed: async ({}, use) => {
    await use((rows) => resetAndSeed(rows));
  },
});

export { expect };
