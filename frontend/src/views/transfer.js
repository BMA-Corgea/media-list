/**
 * Import and export.
 *
 * The importer is a RESOLVER: loose rows in, candidates back, a human settles anything
 * ambiguous, and only then does anything get written. Preview and commit are separate calls
 * so "nothing is written until you confirm" is structural rather than a promise.
 */

import { api } from '../api.js';
import { navigate } from '../router.js';

const STATE_LABEL = {
  matched: 'ready',
  choose: 'needs a choice',
  unmatched: 'no match found',
  duplicate: 'already on your list',
};

function candidateChip(candidate, selected, onPick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `cand${selected ? ' is-chosen' : ''}`;
  const art = document.createElement('span');
  art.className = 'cand__art';
  if (candidate.poster_url) art.style.backgroundImage = `url("${candidate.poster_url}")`;
  button.append(art, Object.assign(document.createElement('span'), {
    className: 'cand__meta',
    textContent: `${candidate.title}\n${candidate.year || '—'} · ${candidate.kind}`,
  }));
  button.addEventListener('click', () => onPick(candidate));
  return button;
}

export async function transferView() {
  const page = document.createElement('main');
  page.className = 'page';
  page.innerHTML = `
    <p class="section-title">Import &amp; export</p>
    <p class="hint">Paste a CSV — a chatbot's raw output is fine, code fence and all. Only a
      <code>title</code> column is required. Nothing is written until you confirm.</p>
    <textarea class="field" id="csv" rows="7" placeholder="title,year,kind,why&#10;Cowboy Bebop,1998,anime,Everyone says the jazz soundtrack alone is worth it"></textarea>
    <div class="actions" id="top-actions"></div>
    <div id="report"></div>
  `;

  const text = page.querySelector('#csv');
  const actions = page.querySelector('#top-actions');
  const report = page.querySelector('#report');

  const file = Object.assign(document.createElement('input'), { type: 'file', accept: '.csv,text/csv', hidden: true });
  const upload = Object.assign(document.createElement('button'), { className: 'btn', textContent: 'Choose a file…' });
  upload.addEventListener('click', () => file.click());
  file.addEventListener('change', async () => {
    const picked = file.files?.[0];
    if (picked) text.value = await picked.text();
  });

  const preview = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'Preview import' });
  const exportBtn = Object.assign(document.createElement('a'), {
    className: 'btn', href: '/api/export.csv', textContent: 'Export everything as CSV', download: 'media-list-export.csv',
  });
  actions.append(preview, upload, file, Object.assign(document.createElement('span'), { className: 'grow' }), exportBtn);

  preview.addEventListener('click', async () => {
    preview.disabled = true;
    preview.textContent = 'Resolving…';
    report.replaceChildren();
    try {
      const result = await api.importPreview(text.value);
      renderReport(result);
    } catch (error) {
      report.innerHTML = `<p class="hint bad">${error.message}</p>`;
    } finally {
      preview.disabled = false;
      preview.textContent = 'Preview import';
    }
  });

  function renderReport(result) {
    report.replaceChildren();
    if (!result.rows.length) {
      report.innerHTML = `<p class="hint bad">${result.problems.join(' · ') || 'Nothing to import.'}</p>`;
      return;
    }

    const summary = document.createElement('p');
    summary.className = 'hint';
    summary.textContent = Object.entries(result.counts)
      .map(([state, n]) => `${n} ${STATE_LABEL[state] || state}`).join(' · ');
    report.append(summary);
    for (const problem of result.problems) {
      report.append(Object.assign(document.createElement('p'), { className: 'hint bad', textContent: problem }));
    }

    const list = document.createElement('div');
    list.className = 'import';

    for (const entry of result.rows) {
      const item = document.createElement('div');
      item.className = `imp imp--${entry.state}`;

      const head = document.createElement('div');
      head.className = 'imp__head';
      head.append(
        Object.assign(document.createElement('span'), { className: 'imp__title', textContent: entry.row.title }),
        Object.assign(document.createElement('span'), { className: 'kind', textContent: STATE_LABEL[entry.state] || entry.state }),
      );
      if (entry.row.year) head.append(Object.assign(document.createElement('span'), { className: 'card__meta', textContent: entry.row.year }));
      item.append(head);

      if (entry.note) item.append(Object.assign(document.createElement('p'), { className: 'hint', textContent: entry.note }));

      if (entry.candidates?.length) {
        const strip = document.createElement('div');
        strip.className = 'cands';
        const paint = () => {
          strip.replaceChildren(...entry.candidates.map((c) => candidateChip(
            c,
            entry.chosen && c.source === entry.chosen.source && c.source_id === entry.chosen.source_id,
            (picked) => {
              entry.chosen = picked;
              // A hand-picked candidate can itself already be on the list. Re-check it, or
              // the button below promises a number the commit will not deliver.
              const key = `${picked.source}:${picked.source_id}`;
              entry.state = (result.existing || []).includes(key) ? 'duplicate' : 'matched';
              renderReport(result);
            },
          )));
        };
        paint();
        item.append(strip);
      } else if (entry.chosen) {
        item.append(Object.assign(document.createElement('p'), { className: 'hint',
          textContent: `→ ${entry.chosen.title} ${entry.chosen.year ? `(${entry.chosen.year})` : ''}` }));
      }

      list.append(item);
    }
    report.append(list);

    const ready = result.rows.filter((e) => e.state === 'matched' && e.chosen);
    const commit = Object.assign(document.createElement('button'), {
      className: 'btn btn--primary',
      textContent: ready.length ? `Import ${ready.length} title${ready.length > 1 ? 's' : ''}` : 'Nothing ready to import',
    });
    commit.disabled = !ready.length;
    commit.addEventListener('click', async () => {
      commit.disabled = true;
      commit.textContent = 'Importing…';
      try {
        const outcome = await api.importCommit(ready);
        const done = document.createElement('div');
        done.className = 'empty';
        done.innerHTML = `<h2>Imported ${outcome.counts.added}</h2>
          <p>${outcome.counts.skipped} already on your list${outcome.counts.failed ? `, ${outcome.counts.failed} failed` : ''}.</p>`;
        const go = Object.assign(document.createElement('button'), { className: 'btn btn--primary', textContent: 'See the wall' });
        go.addEventListener('click', () => navigate('/'));
        done.append(go);
        report.replaceChildren(done);
      } catch (error) {
        commit.disabled = false;
        commit.textContent = 'Import failed — try again';
        report.append(Object.assign(document.createElement('p'), { className: 'hint bad', textContent: error.message }));
      }
    });
    const foot = document.createElement('div');
    foot.className = 'actions';
    foot.append(commit);
    report.append(foot);
  }

  return page;
}
