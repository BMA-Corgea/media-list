/**
 * Stops the server started by global-setup.js and removes its scratch database.
 *
 * Kills by the exact PID this run itself spawned — never `pkill -f uvicorn` (that pattern
 * matches an agent's own shell command line as readily as the server's, see
 * kb/notes/handoff.md's gotchas). Runs in the same Playwright runner process as
 * global-setup.js, so the env vars it stashed there are still here.
 */
import { rmSync } from 'node:fs';

export default async function globalTeardown() {
  const pid = process.env.MEDIA_LIST_TEST_PID;
  if (pid) {
    try {
      process.kill(Number(pid), 'SIGTERM');
    } catch {
      // already gone
    }
  }

  const dataDir = process.env.MEDIA_LIST_TEST_DATADIR;
  if (dataDir) {
    rmSync(dataDir, { recursive: true, force: true });
  }
}
