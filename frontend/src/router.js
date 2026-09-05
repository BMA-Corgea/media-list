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
 * Tell a view its screen is gone.
 *
 * `replaceChildren` drops the ELEMENT; it does not stop anything the view started. A view
 * that owns work outliving its DOM — a request still streaming, a timer, a listener on
 * `window` — hangs a `cleanup` function on the node it returns, and this is the one place
 * that calls it. Without it, navigating away from a running import preview left the request
 * open and the server resolving a thousand rows for a screen nobody could see (T-15 F2).
 *
 * Called exactly once per node, and never for a node still on screen.
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
  const node = await found.view(...found.args);
  if (current() !== token) {
    // This node is never displayed, so nothing later will ever dismiss it. If it started
    // anything on the way up, this is its only chance to stop.
    dismiss(node);
    return;
  }
  dismiss(mounted);
  mounted = node;
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
