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

async function render() {
  const path = current();
  const found = match(path) ?? match('');
  if (!found || !outlet) return;

  // Views may be async (most fetch). Guard against a slow view painting over a newer one
  // the user has already navigated to.
  const token = path;
  const node = await found.view(...found.args);
  if (current() !== token) return;
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
