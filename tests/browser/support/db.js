/**
 * JS-side wrapper around `reset_and_seed.py` — see that file for why seeding shells out to
 * Python rather than reaching into the SQLite file from Node: it lets specs reuse the exact
 * same insert shape as `tests/conftest.py::insert_title` instead of a second copy of it.
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const SCRIPT = path.join(HERE, 'reset_and_seed.py');

/**
 * Wipe `titles` and insert exactly `rows`, in order. Each entry may override any column
 * from the schema (source, kind, why, queue_position, ...); anything left out gets the
 * same defaults `insert_title` uses. Returns the inserted ids, in the same order as `rows`.
 */
export function resetAndSeed(rows) {
  const result = spawnSync(PYTHON, [SCRIPT], {
    cwd: REPO_ROOT,
    // PYTHONPATH so `import backend` resolves regardless of the script's own directory;
    // MEDIA_LIST_DB (and everything else) comes through via process.env, inherited from
    // global-setup.js.
    env: { ...process.env, PYTHONPATH: REPO_ROOT },
    input: JSON.stringify(rows),
    encoding: 'utf-8',
  });
  if (result.status !== 0) {
    throw new Error(`reset_and_seed.py failed (exit ${result.status}):\n${result.stderr}`);
  }
  return JSON.parse(result.stdout);
}
