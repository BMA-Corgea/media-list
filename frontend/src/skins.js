/**
 * The skin registry — the whole of what it costs to add a look.
 *
 * ── The contract (ported from ../repo-tour/src/skins.ts) ──────────────────────────────
 * A skin is ONE file at `src/skins/<name>.css` whose rules all live under
 * `:root[data-theme="<name>"]`, plus ONE row in `SKINS` below. Nothing else changes: the
 * file is bundled, the option appears in the switcher, and the choice applies on load and
 * persists across reloads, automatically.
 *
 * `base.css` is imported first and is the special one — it owns the bare `:root`, so it
 * carries the tokens AND the component layer. That is why an alternate can be seventy lines
 * of pure token overrides and still restyle the whole app, including surfaces built by
 * tickets that did not exist when the alternate was written.
 *
 * `system` is not a file: it is the ABSENCE of a `data-theme` attribute, which lets the
 * base's `prefers-color-scheme` block decide. It is first because an app that opens in the
 * wrong brightness for someone's desk is an app they close.
 *
 * Alternates are imported AFTER the base so a scoped override wins ties on equal specificity.
 */

import './skins/base.css';
import './skins/nocturne.css';
import './skins/paperback.css';

/** @typedef {{name: string, label: string, note: string}} Skin */

/** @type {readonly Skin[]} — add a skin by writing the CSS file and appending one row here. */
export const SKINS = [
  { name: 'system',    label: 'System',    note: 'Follows your OS light or dark setting.' },
  { name: 'nocturne',  label: 'Nocturne',  note: 'A cinema before the film starts: blue-black ground, projector amber.' },
  { name: 'paperback', label: 'Paperback', note: 'A secondhand bookshop shelf in daylight: cream paper, faded stamp red.' },
];

/** The skin an unconfigured browser opens in. */
export const DEFAULT_SKIN = 'system';

export const STORAGE_KEY = 'media-list:skin';

/** Apply a skin. `system` means removing the attribute so the media query takes over. */
export function applySkin(name) {
  const root = document.documentElement;
  if (!name || name === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', name);
}

export function storedSkin() {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_SKIN;
  } catch {
    // Private windows and blocked site data throw on access rather than returning null.
    return DEFAULT_SKIN;
  }
}

/** Build the switcher and wire it to storage. Returns the element for the caller to place. */
export function skinPicker() {
  const select = document.createElement('select');
  select.className = 'skinpick';
  select.id = 'skinpick';
  select.setAttribute('aria-label', 'Skin');

  for (const skin of SKINS) {
    const option = document.createElement('option');
    option.value = skin.name;
    option.textContent = skin.label;
    option.title = skin.note;
    select.append(option);
  }

  select.value = storedSkin();
  select.addEventListener('change', () => {
    applySkin(select.value);
    try {
      localStorage.setItem(STORAGE_KEY, select.value);
    } catch {
      // A skin that cannot be remembered is still a skin that works for this session.
    }
  });

  return select;
}
