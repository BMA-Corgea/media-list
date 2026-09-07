/**
 * The smallest router that does the job.
 *
 * Hash-based on purpose: the backend already serves index.html for any unknown path, but a
 * hash route cannot be broken by a proxy, a subpath deployment, or a stale build — and this
 * app has exactly one origin and a handful of screens.
 *
 * T-5 (carousel), T-6 (title page), T-8 (wheel) and T-9 (archive) register here rather than
 * each inventing their own navigation.
 */

const routes = [];
let outlet = null;
let chrome = null;
let mounted = null;
// Whether `mounted` has still to be dismissed. Since T-18 a view is dismissed when the user
// LEAVES it rather than when its replacement is ready, so "on screen" and "still live"
// stopped being the same question and `mounted` alone can no longer answer both.
let mountedIsLive = false;

/** `pattern` is a string ('add') or a RegExp whose capture groups become the view's args. */
export function route(pattern, view) {
  routes.push({ pattern, view });
}

export function navigate(path) {
  window.location.hash = path.startsWith('#') ? path : `#${path}`;
}

export function current() {
  return window.location.hash.replace(/^#\/?/, '') || '';
}

function match(path) {
  for (const { pattern, view } of routes) {
    if (typeof pattern === 'string') {
      if (pattern === path) return { view, args: [] };
    } else {
      const found = pattern.exec(path);
      if (found) return { view, args: found.slice(1) };
    }
  }
  return null;
}

/**
 * Tell a view the user has left it.
 *
 * `replaceChildren` drops the ELEMENT; it does not stop anything the view started. A view
 * that owns work outliving its DOM — a request still streaming, a timer, a listener on
 * `window` — hangs a `cleanup` function on the node it returns, and this is the one place
 * that calls it. Without it, navigating away from a running import preview left the request
 * open and the server resolving a thousand rows for a screen nobody could see (T-15 F2).
 *
 * Called exactly once per node — `mountedIsLive` is what keeps that true now that the call
 * no longer coincides with the swap (T-18 round 2, F1; see `render`).
 *
 * NOT the same thing as "the node is off screen". A dismissed node stays displayed until
 * the incoming view resolves and `replaceChildren` runs, so a view's `cleanup` must be the
 * one that gives up work, not the one that tears its own DOM apart.
 */
function dismiss(node) {
  if (!node || typeof node.cleanup !== 'function') return;
  try {
    node.cleanup();
  } catch (error) {
    // A view failing on its way out must not stop the next screen from rendering.
    console.error('view cleanup failed', error);
  }
}

async function render() {
  const path = current();
  const found = match(path) ?? match('');
  if (!found || !outlet) return;

  // Views may be async (most fetch). Guard against a slow view painting over a newer one
  // the user has already navigated to.
  const token = path;

  // ── The outgoing view is dismissed HERE, before the incoming one is built ────────────
  //
  // It used to be the other way round: `await found.view(...)` first, `dismiss(mounted)`
  // after. That made a view's lifecycle depend on how the NEXT view happens to be written.
  // Every view in this app awaits a network call on the way up except `views/add.js`,
  // which is synchronous — so navigating Add → a slow screen → Add built the second Add
  // mount while the first was still queued behind the slow screen's `await`, and T-18's
  // search hand-off (a module-scoped value written at unmount, read at mount) was read
  // before it was ever written. The query the owner was promised would be kept came back
  // empty, silently, which is the exact symptom T-18 exists to remove (round 2, F1).
  //
  // Versioning the hand-off instead would have stopped a stale mount CLOBBERING a fresh
  // one, but the fresh one would still have been built from nothing — the ordering is the
  // bug, not the write. Doing it here, synchronously, before the first `await`, means
  // dismissals happen in `hashchange` order and can never overtake a later mount.
  //
  // What that costs, plainly: `dismiss` does not remove the node (`replaceChildren` below
  // does, later), so between here and the swap the outgoing screen is visible but inert.
  // That is the browser's own behaviour — the old page stays up until the new one paints —
  // and it is the honest reading of `cleanup`: the user leaves at the navigation, not
  // whenever the next screen finishes loading. T-15's import stream is cancelled at the
  // click now rather than seconds later, which is what "walking away stops the searches"
  // always meant. The one thing given up is a keystroke typed into a screen already
  // navigated away from, during that window; nothing is owed to it.
  if (mountedIsLive) {
    mountedIsLive = false;
    dismiss(mounted);
  }

  const node = await found.view(...found.args);
  if (current() !== token) {
    // This node is never displayed, so nothing later will ever dismiss it. If it started
    // anything on the way up, this is its only chance to stop.
    dismiss(node);
    return;
  }
  // The liveness decision above is made BEFORE the await and acted on after — different
  // moments. Two render() calls for the SAME path both pass the `current() !== token`
  // guard, so both reach here; without this, the second overwrites `mounted` and the node
  // the first one already mounted and displayed never has its `cleanup` run (round 2, F4).
  // The dismissal above keeps `dismiss` at-most-once; this keeps it at-least-once.
  if (mountedIsLive) dismiss(mounted);
  mounted = node;
  mountedIsLive = true;
  outlet.replaceChildren(node);
  if (chrome) chrome(path);
  window.scrollTo({ top: 0 });
}

/** `onRoute` lets the shell (nav highlighting) react without knowing about views. */
export function start(mountPoint, onRoute) {
  outlet = mountPoint;
  chrome = onRoute;
  window.addEventListener('hashchange', render);
  return render();
}
