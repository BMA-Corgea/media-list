/**
 * The one function that commits a candidate onto the list.
 *
 * T-17, AC3: the plus button on a search-result card and the description screen's Add
 * button are two DOORS onto adding, never two implementations of it. Both call this, so a
 * duplicate check, a payload field, or a future third door (T-16's books land on the same
 * description screen right after this ticket) can never drift between them.
 */

import { api } from './api.js';

export function addCandidate(candidate, why = '') {
  return api.add({
    source: candidate.source,
    source_id: candidate.source_id,
    // Carried through deliberately: TMDB movie and tv ids are separate namespaces
    // (sources/tmdb.details) — a stored title that forgets which one it came from cannot
    // be refreshed later.
    media_type: candidate.media_type,
    why: (why || '').trim(),
  });
}
