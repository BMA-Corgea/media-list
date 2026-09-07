/**
 * What each kind of thing is called.
 *
 * One place decides that a game is PLAYED and a film is WATCHED. T-9's rating flow reads
 * from here rather than re-deciding it, so the two screens can never disagree.
 */

const VERBS = {
  game: { past: 'played', imperative: 'Mark as played', noun: 'game' },
  anime: { past: 'watched', imperative: 'Mark as watched', noun: 'anime' },
  movie: { past: 'watched', imperative: 'Mark as watched', noun: 'film' },
  'live-action': { past: 'watched', imperative: 'Mark as watched', noun: 'series' },
  // A book is READ. The fallback below would have called it 'finished', which is not wrong
  // so much as nobody's word for it — and the whole point of this map is that the one place
  // deciding a game is PLAYED also decides a book is READ.
  book: { past: 'read', imperative: 'Mark as read', noun: 'book' },
};

const FALLBACK = { past: 'finished', imperative: 'Mark as finished', noun: 'title' };

export const verbFor = (kind) => VERBS[kind] || FALLBACK;

/**
 * Every kind the filter chips offer, `all` first — the queue, the archive and the wheel
 * each used to keep their own copy of this array, so a new kind (T-16's `book`) reached
 * `kinds.js` and nowhere else: visible under `all`, unfilterable and unspinnable
 * everywhere it mattered. One list here means the next kind is one edit, not four.
 * The order is the display order, not `VERBS`' insertion order — kept as it was before this
 * list existed, with each new kind appended rather than however `Object.keys` happens to run.
 */
export const KIND_FILTERS = ['all', 'anime', 'movie', 'live-action', 'game', 'book'];
