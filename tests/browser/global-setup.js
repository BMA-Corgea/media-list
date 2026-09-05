/**
 * Boots the real app once for the whole three-engine run.
 *
 * This is the first Playwright code in the repo (T-14) and the first fixture that binds a
 * port at all — T-13's suite deliberately needs none. Copies T-13's `tests/conftest.py`
 * isolation story for a real subprocess rather than an in-process `TestClient`:
 *
 *   - a throwaway `MEDIA_LIST_DB`, created fresh here, never `data/media-list.db`
 *   - fixed fake source credentials, so `available()` is deterministic and nothing here
 *     ever has a reason to make a real TMDB/AniList/IGDB/Pexels call
 *   - the scratch port `playwright.config.js` already picked (via `MEDIA_LIST_TEST_PORT`,
 *     set during config evaluation, before this function runs) — never 7799
 *
 * Runs in the Playwright runner's main process, not a worker, so the env vars set at the
 * bottom are inherited by every worker process Playwright spawns after this returns — the
 * documented way to hand data from global setup to tests (see support/db.js, which reads
 * `MEDIA_LIST_DB` back out to seed rows for each spec).
 */
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../..');

export default async function globalSetup() {
  const port = process.env.MEDIA_LIST_TEST_PORT;
  if (!port) throw new Error('MEDIA_LIST_TEST_PORT was not set by playwright.config.js');

  // `tempPrefix` doubles as the belt-and-suspenders marker support/reset_and_seed.py checks
  // before it will touch a database at all.
  const dataDir = mkdtempSync(path.join(tmpdir(), 'media-list-pw-'));
  const dbPath = path.join(dataDir, 'test.db');

  const env = {
    ...process.env,
    MEDIA_LIST_DB: dbPath,
    MEDIA_LIST_HOST: '127.0.0.1',
    MEDIA_LIST_PORT: port,
    // Fixed, obviously-fake — same reasoning as tests/conftest.py: deterministic, and never
    // trusted even if a real .env sits beside this repo (load_dotenv does not override an
    // already-set variable).
    TMDB_API_KEY: 'test-tmdb-key',
    IGDB_CLIENT_ID: 'test-igdb-client-id',
    IGDB_CLIENT_SECRET: 'test-igdb-client-secret',
    PEXELS_API_KEY: 'test-pexels-key',
  };

  const python = path.join(REPO_ROOT, '.venv', 'bin', 'python');
  const server = spawn(python, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', port], {
    cwd: REPO_ROOT,
    env,
  });

  let output = '';
  server.stdout.on('data', (chunk) => { output += chunk; });
  server.stderr.on('data', (chunk) => { output += chunk; });

  const baseURL = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 30_000;
  let ready = false;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`media-list server exited before it came up (code ${server.exitCode}):\n${output}`);
    }
    try {
      const response = await fetch(`${baseURL}/api/health`);
      if (response.ok) { ready = true; break; }
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (!ready) {
    server.kill('SIGTERM');
    throw new Error(`media-list server never answered /api/health on ${baseURL}:\n${output}`);
  }

  // Handed to global-teardown.js and to every worker (see support/db.js) via inherited env.
  process.env.MEDIA_LIST_TEST_PID = String(server.pid);
  process.env.MEDIA_LIST_DB = dbPath;
  process.env.MEDIA_LIST_TEST_DATADIR = dataDir;
}
