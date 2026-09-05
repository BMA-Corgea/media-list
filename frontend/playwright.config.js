/**
 * Playwright config for T-14's three-engine run.
 *
 * Lives in `frontend/` because that is where `@playwright/test` is actually installed
 * (AC1 — no more borrowing the sibling project's copy); `testDir` reaches back out to
 * `tests/browser/` at the repo root so the browser specs sit next to the rest of the test
 * suite rather than being split into a second tree.
 *
 * The scratch port is picked ONCE, synchronously, while this file is evaluated — before
 * `globalSetup` runs — because `use.baseURL` below has to be a real value at config-load
 * time. `global-setup.js` reads it back from `process.env` (same process, so this is the
 * documented Playwright pattern for handing data from config to global setup) and boots
 * the real FastAPI server on it with a scratch `MEDIA_LIST_DB` — never port 7799 (the
 * owner's reserved one, see ../../PROJECT_PORTS.md) and never data/media-list.db.
 */
import { defineConfig, devices } from '@playwright/test';
import { createServer } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** Bind :0 and read back whatever the OS handed out, then let it go — a real scratch port,
 * distinct from every port in PROJECT_PORTS.md by construction rather than by memory. */
function findFreePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.unref();
    probe.on('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

const PORT = process.env.MEDIA_LIST_TEST_PORT || String(await findFreePort());
process.env.MEDIA_LIST_TEST_PORT = PORT;

export default defineConfig({
  testDir: path.resolve(HERE, '../tests/browser'),
  globalSetup: path.resolve(HERE, '../tests/browser/global-setup.js'),
  globalTeardown: path.resolve(HERE, '../tests/browser/global-teardown.js'),

  // The specs share one server and one database across the whole run (seeded fresh by each
  // test via `resetAndSeed`, see support/db.js) — one worker keeps that shared state from
  // racing across projects, and the suite is small enough that this costs nothing.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,

  reporter: [['list']],

  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // AC2's wheel case is specifically the long decelerating spin — reduced motion would
    // skip straight to the reveal and test nothing about the transition.
    reducedMotion: 'no-preference',
    trace: 'retain-on-failure',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    // Real engine, not Safari — see kb/wiki/lessons.md's T-14 entry before reading webkit
    // results as "Safari passed".
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
