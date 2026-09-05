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
};

const FALLBACK = { past: 'finished', imperative: 'Mark as finished', noun: 'title' };

export const verbFor = (kind) => VERBS[kind] || FALLBACK;
