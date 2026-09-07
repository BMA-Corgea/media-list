---
name: lessons
description: Durable lessons this project has learned
type: reference
---

# lessons

Durable lessons land here as the project runs — one entry per lesson, newest first, each
citing the ticket/incident it came from.

## `CREATE TABLE IF NOT EXISTS` makes a schema file lie about every database that already exists (T-16)

`backend/db.py::bootstrap` applies `schema.sql` on every boot and every statement in it is
`IF NOT EXISTS`. It is tempting to read that as "this file is the whole migration story for
as long as changes are additive" — a new column feels harmless the way a new CHECK does not.
**That reading is false for a column exactly as much as for a constraint, and round 1 of this
very ticket's own review shipped it as advice before catching itself.** `IF NOT EXISTS`
guards the STATEMENT — whether `titles` exists at all — not anything inside it. Once a
database has the table, `CREATE TABLE IF NOT EXISTS titles (...)` is a total no-op, so
neither a new column nor a changed constraint in that parenthesised list ever reaches an
existing database. The owner's real database was verified still carrying
`CHECK (kind IN ('anime','movie','live-action','game'))` long after the file said otherwise,
and it genuinely rejected a book insert; **proved again for a plain column**, not just a
constraint — adding `pages INTEGER` to schema.sql on an already-migrated database, without
bumping `SCHEMA_VERSION`, gave `'pages' in table -> False` on the next boot and
`no such column: pages` on the first insert naming it.

Nothing warns you. The file reads correctly, a fresh `rm -rf data` boot behaves correctly,
the tests (which build fresh databases) pass — and the one machine that matters is the only
place the old shape survives. **The fresh-install path and the upgrade path are different
code paths, and only one of them is exercised by a test suite that starts from an empty
directory.** SQLite cannot `ALTER` a CHECK, so the fix for a constraint is a full table
rebuild: create, copy, drop, rename. A plain column needs the exact same rebuild — there is
no cheaper path for either one.

**The one statement in `schema.sql` that genuinely is self-applying is a NEW
`CREATE INDEX IF NOT EXISTS`.** That is not a special case of the rule above, it is a
different rule: the object a `CREATE INDEX` statement guards is the index itself, and a
brand-new index name really is absent from an old database, so the statement actually runs.
A `CREATE TABLE` statement guards the table, and the table is exactly the thing that is
*not* absent — so bumping `SCHEMA_VERSION` is required for a new column or a changed
constraint, and required for neither only when the new thing is an index.

## `PRAGMA foreign_keys` is a silent no-op inside a transaction (T-16)

SQLite's own table-rebuild procedure requires `PRAGMA foreign_keys=OFF` around the swap, and
`db.py::_connect` turns them ON for every connection this app opens. The trap is that the
pragma is **ignored, without any error, if a transaction is already open** — so
`BEGIN; PRAGMA foreign_keys=OFF; ...` looks exactly like the correct code and does nothing.
It has to be flipped BEFORE `BEGIN` and restored after `COMMIT`, and `_rebuild_titles` reads
it back and raises rather than trusting that it took. A pragma that fails by returning
success is worth a verification line, not a comment.

## A migration's version stamp must commit in the same transaction as the change it describes (T-16)

The gate for "has this database been migrated?" is `PRAGMA user_version`. The obvious
arrangement — apply `schema.sql`, then migrate — is backwards and silently fatal, because
`schema.sql` stamps `user_version` itself: every old database would be marked current before
anything had looked at its actual table, and the migration would never run on the one file
it exists for. So `migrate()` runs BEFORE `executescript`.

The subtler half: the rebuild replays `schema.sql`'s own `PRAGMA user_version` INSIDE its
transaction, so the version and the table shape it describes commit together. Stamping it
after the commit leaves a window where the shape is new and the version says old — a crash
there causes a second, pointless rebuild. Stamping before leaves the opposite window, which
loses the migration entirely. **Version and shape are one fact; write them once.**

## What a naive table rebuild silently loses (T-16)

Three things, none of which raises:

* **`SELECT *`.** `INSERT INTO new SELECT * FROM old` shifts every value one column left the
  first time someone inserts a column into the MIDDLE of the schema file. Column order is not
  a contract; column names are. Copy by name, on both sides, from `PRAGMA table_info`.
* **The indexes.** `DROP TABLE` takes them with it. Losing the UNIQUE one does not raise —
  it just quietly starts letting duplicates onto the list.
* **The AUTOINCREMENT high-water mark.** `sqlite_sequence` is rebuilt from the copied rows,
  so it resets to `max(id)` and the next insert reuses the id of a row the user deleted. A
  test only catches this if its fixture has a deleted row; if `seq == max(id)` the bug is
  invisible.

And a fourth, which is a refusal rather than a loss: if the new schema lacks a column the old
table has, that is silent data destruction, not a migration. `_rebuild_titles` raises.

The rebuild also builds its staging table FROM `schema.sql` (renaming the statement) rather
than from a hand-copied `CREATE TABLE` in Python. A second declaration of the same table is
free to drift from the first, which is the exact class of bug this whole ticket was about.

## Crash-safety needs a real kill — an exception tests the cleanup path, not the crash (T-16)

To prove the rebuild is interrupt-safe, the tests spawn a real interpreter and stop it with
`os._exit(9)` at three points inside the transaction, the important one being immediately
after `DROP TABLE titles`, when the original is gone and the only copy of the list lives in
an uncommitted staging table. `os._exit` skips finally-blocks, connection close and
interpreter shutdown — which is what a SIGKILL or a power cut does.

Raising an exception in-process instead would have exercised the `except: ROLLBACK` handler.
That is a *weaker and different* claim: it proves the code tidies up while it is still
running, which is not the scenario anyone is afraid of. The tests also assert the child
really died (exit code 9), so a trigger string that stops matching any statement fails loudly
instead of quietly interrupting nothing and passing.

## `.gitignore` protects a filename pattern, not a category of secret (T-16)

The privacy rule is a glob: `media-list-export*.csv`, alongside `data/` and `*.db`. AC6
needed a pre-change CSV export kept as a test fixture, and the obvious file —
`tests/fixtures/pre-t16-export.csv`, holding a real export of the owner's list and his
personal "why" notes — sails straight past that glob **on its name alone** and would have
been committed to a public repo by a rule that exists to prevent exactly that.

The fixture was rebuilt as synthetic rows through the same pre-change code, and the real
export kept out of the tree. When a file is about to be committed, the question is not
"is it gitignored?" but "what does it contain?" — the ignore rules encode the answer for the
filenames somebody thought of.

## A `cd` at the front of a compound command does not survive a backgrounded job (T-16)

A verification step written as
`cd <worktree> && rm -rf data && <start server> & ... ; ls -la data/` ran its first half in
the worktree and its second half in the **main checkout**, because backgrounding resets the
shell the later statements run in. The `ls` and a following `sqlite3` therefore opened the
OWNER'S real database instead of the throwaway one — read-only as it turned out, and it was
proved byte-identical afterwards, but it was luck rather than design that the destructive
statement sat before the `&` and not after it.

Absolute paths everywhere in agent shell commands, not a leading `cd` — and when a command
mixes a background job with filesystem work, put the paths in a script file where they cannot
be re-interpreted. The nearby rule this reinforces: a step that says "this must never touch
X" needs its own positive check that X is unchanged (`scripts/test.sh` already does this for
the database's mtime, which is why the near-miss was detectable at all).

## A gitignored build output makes the whole suite lie after a merge (T-17)

`dist/` is gitignored, so **a merge never updates it**. Merging T-17 into a checkout that already
had a bundle left that bundle six commits behind the source, and both the pytest harness and
`scripts/test.sh` built the frontend *only if `dist` was **missing***, so neither noticed.

What each layer did, and the lesson is in the difference:

- **T-13's bundle-marker test caught it immediately and loudly** — two failures naming exactly
  `views/add.js` and `views/candidate.js`, the two modules the merge had brought in. That check
  exists because a green `vite build` once hid an unimported module; here it caught a stale build
  instead. It earned its place twice.
- **The browser suite did not.** It spent **9.5 minutes** driving a stale application and then
  failed with 20 of 42 tests — a result that looks like a regression in the merged code and is
  not. Slow, confusing, and pointing at the wrong thing.

**The rule: build when the output is missing OR older than its sources, never "once if missing."**
Both `tests/conftest.py` and `scripts/test.sh` now compare mtimes. A guard that works is no help
if the harness feeds it yesterday's artifact — and the failure mode of a *stale* input is much
harder to read than the failure mode of a *missing* one, because everything still runs.


## A mocked call answers before an unmocked one fails — so the test passed against a page mid-navigation to a broken screen (T-17 round 2)

`tests/browser/add.spec.js`'s AC3 test is the one written to prove that the `+` under a search
result adds directly. Put back the nested-button trap the entry below already records as
rejected — `open.append(add)` instead of `card.append(open, add)` — and **it still passed**, on
both engines. Only AC7's keyboard test failed, and only by accident.

The mechanism, traced rather than guessed. With the nesting, a click on `+` bubbles to
`.card__open` as well, so one press fires **two** things: an add, and a navigation to the
description screen. The test mocked `POST /api/titles` but not `GET /api/details/*`. So:

1. the mocked POST answers in about a millisecond, and `quickAdd` writes "Added" into the hint
   and puts `is-added` on the card;
2. the navigation is meanwhile still waiting on a real `/api/details` request, which this
   suite's server — deliberately given fake TMDB/IGDB credentials — can only fail, slowly;
3. `router.js` awaits the view before it swaps the outlet, so **the old screen is still
   mounted, and still correct**;
4. every assertion runs inside that window, and passes.

The test was reading a true fact about a page that was already on its way to a broken screen.
Nothing about its assertions was weak — they were simply pointed at the half of the outcome the
bug does not touch. AC7's test caught it only because *it* mocks `/api/details`, so the bad
navigation resolved fast enough to wipe the hint before the assertion ran. Luck, not design.

**The rule worth keeping: when a bug's signature is an EXTRA side effect, assert that side
effect's absence directly — never infer it from whatever DOM state you happen to observe
first.** The DOM you read is in a race with the side effect you did not name. Here that means
two assertions, and the fixed test makes both:

- `await expect(page).toHaveURL(/#\/add$/)` — the navigation that must not happen, named;
- `mockDetails` now returns the keys it was asked for, and the test asserts `[]` — the fetch
  that must not happen, named.

A corollary for any suite that stubs the network: **an unmocked endpoint is not neutral.** It is
a slow failure, and a slow failure holds the old screen in place long enough to make a broken
app look right. Mock the calls a correct run will never make, precisely so a wrong run cannot
hide inside their latency.

**This is the seventh instance of the pattern this file has been counting since T-13** — a
green test guarding a rule it cannot actually see. The table in *"An assertion that cannot fail
and a scenario that cannot discriminate"* below names the first four; the count stood at six by
the time T-17 was reviewed. The **eighth** arrived in the same review, and belongs here because
its fix is the same shape: AC6's test proved that four cosmetic fields render and never looked
at the body, so `record.kind !== 'game'` in front of the summary — the exact per-kind branch AC6
forbids, and the clause T-16's books depend on — sailed straight past it. Stop reading a chosen
list of fields; compare **the whole rendered markup**, one candidate driven through the screen
as every kind, with only the kind's own name blanked out. Both fixes were verified by watching
them go red on both engines against the regression put back in a scratch copy under `/tmp`, the
bundle rebuilt each time — still the only step that tells a guard from a decoration.

## A `<button>` cannot host a second door onto a different action — split the card, don't nest it (T-17)

`views/add.js`'s search-result card used to be exactly one `<button>` whose only behaviour was
add (the ticket's own incident: one press on "Dungeon Crawler Carl" committed the wrong TMDB
match with no preview). AC3 gave the card a second, independent action — a `+` that adds
directly, alongside an "open the description screen" action that must add nothing at all — and
the shape that looks obvious is nesting: `<button class="card">…<button class="card__add">+
</button></button>`.

That shape does not work, for a reason that has nothing to do with this app's own logic.
`<button>` inside `<button>` is invalid content model — browsers still render it, which is
exactly what makes the trap easy to miss in a quick check — and a `click` on the inner button
still BUBBLES to the outer one. Built that way, pressing `+` would fire the inner listener
(add) AND the outer one (open), so every "quick add" would also silently navigate to the
description screen right after adding. There is no `event.stopPropagation()` fix that isn't
fragile: it has to be remembered on every future button the card grows, forever, by everyone
who touches it — exactly the kind of rule a codebase forgets one refactor later.

The real fix was structural, not defensive: `.card--pick` stopped being a button and became a
plain wrapper `<div>`; the poster/title/meta press became its own `<button class="card__open">`
(a SIBLING, not a parent); `<button class="card__add">` sits next to it, not inside it. Two
doors, two independent buttons, one non-interactive frame around both — no event plumbing
required to keep them from firing each other. Any card that is about to grow a second action
should reach for this shape before reaching for `stopPropagation()`.

A second, smaller trap the same change tripped: `tests/test_bundle.py` fingerprints each view
module by one UI string assumed unique to it across `frontend/src/**/*.js`
(`test_each_marker_string_is_unique_to_its_module`). This ticket deliberately put the literal
string `"no art"` in `add.js`, `candidate.js` AND `title.js` — the whole point of AC5 is that a
missing-artwork placeholder reads the same everywhere — which silently broke `add.js`'s needle,
because `"no art"` had been its needle before it needed to be shared text. The uniqueness test
caught it immediately and said exactly what was wrong; the trap is not noticing that
deliberately-shared UI copy can no longer serve as any one module's fingerprint. Its needle
has to come from that module's own unique surroundings instead (here, an aria-label sentence
`add.js` alone constructs) — never from the phrase that is now shared on purpose.

## An assertion that cannot fail and a scenario that cannot discriminate are two different bugs — and the second one hides behind the first (T-14 round 2)

`tests/browser/queue.spec.js`'s filtered-reorder test guarded `kb/notes/handoff.md` §6's
id-not-index rule. Reintroducing exactly the regression it names — `views/queue.js`'s
`neighboursFor` computing neighbours from the unfiltered `all` array instead of `visible()` —
left it **passing 4/4 on both engines**. It had two independent defects, and only one of them
is visible from reading the assertions.

**Defect 1, the one you can see: an assertion that cannot fail.** The test's headline claim
was that hidden rows keep their positions *"byte-for-byte"*:

```js
expect(byId[movieM].queue_position).toBe(20);
expect(byId[movieN].queue_position).toBe(40);
```

`backend/main.py::move_title` only ever runs `UPDATE titles SET queue_position = ? WHERE id
= ?` for the single moved title. **No other row's position can change, whatever `after_id` /
`before_id` the client sends.** The assertion is true under every possible frontend bug, so
it constrains nothing. (It is also fragile in the other direction: `move_title` calls
`_renumber` when a gap is too small to divide, which rewrites everyone's number legitimately.
Assert the *order*, which is what is actually promised; never the literal integers, which are
an implementation detail that is simultaneously unfalsifiable and brittle.)

**Defect 2, the one that survives a careful reading of Defect 1: a scenario that cannot
discriminate.** Delete the tautologies and the test still passes with the regression in
place, because the *gesture* was blind. It dragged the **last** visible row above the
**first**. Anime A is the first anime row in the filtered list and also the first anime row
in the unfiltered queue, so `visible()` and `all` compute the **same** `{before_id: animeA}`.
The two implementations are indistinguishable at that input. Every assertion downstream —
however sharp — is being fed a case where correct and broken agree.

An **interior** drop target is where the lists disagree. With Anime A dropped between Anime B
and Anime C, the row above index 1 is Anime B (visible) or Movie M (unfiltered, *hidden*) —
and the rewritten test fails on both engines with the regression restored:

```
Error: move sent {"after_id":2}; Anime B is 3, and the hidden rows are Movie M 2 / Movie N 4

expect(received).toEqual(expected) // deep equality

- Expected  - 1
+ Received  + 1

  Array [
-   3,
+   2,
  ]
```

`after_id: 2` is Movie M — a row the anime filter was hiding. That is the regression, named.

The lesson generalises past this test. **Before writing assertions, ask what inputs the
correct and the broken implementation would disagree on, and check that your fixture is one
of them.** Boundary cases — first, last, empty, single-element — are exactly where a filtered
view and an unfiltered view coincide, where an index and an id coincide, where a sorted and
an unsorted list coincide. They read like the natural thing to test and they are the worst
discriminators available. Assertion quality cannot rescue a scenario that has no signal in it.

What the rewritten test asserts instead, all three of which go red under the regression:

1. **the ids the client actually sent**, read off the wire via
   `response.request().postDataJSON()` — the id-not-index rule stated directly, in the one
   place it is decided;
2. **the full queue order after a reload**, hidden rows included — which is the hidden-row
   guarantee written so that it *can* fail (verified: it fails on both engines on its own,
   with the payload assertion disabled);
3. the **filtered** order after that same reload.

Note (2)'s reload. The first version checked the live DOM, and `views/queue.js` reorders
optimistically during the gesture — so between the move response landing and the repaint, the
DOM still shows the drop the user made even when the server was told something else entirely.
An `expect.poll` succeeds on its first match, so it can pass inside that window against a
broken client. Read the result from a fresh load, not from the optimistic view.

**This is the fourth green test on this branch that proved a path the real system never
takes.** The pattern is now the branch's defining defect, not a coincidence:

| # | Ticket | The test said | What it actually exercised |
| --- | --- | --- | --- |
| 1 | T-13 F1 | traversal is contained | httpx applied RFC 3986 dot-segment removal *before the request left the client*, so the handler saw a payload the real server never produces — it passed against `spa()` with containment deleted |
| 2 | T-13 F1 (point 4) | `/etc/passwd` is unreachable | a hardcoded `../` depth climbed out of an eight-deep worktree to a path that does not exist — it passed on a **miss** |
| 3 | T-15 F1 | walking away stops the searches | the test called `aclose()` explicitly, the one thing the real disconnect path never does; the real path leaves the generator suspended and ~390 searches running |
| 4 | T-14 F1 (this) | a filtered reorder never touches a hidden row | a boundary gesture where the filtered and unfiltered arrays yield the same id, plus an assertion the backend makes true unconditionally |

All four were green. **None was found by reading the test.** Every one was found the same
way: put the regression back in a scratch copy of the app and run the committed test against
it. That is the only step that distinguishes a guard from a decoration, and it is cheap — a
`rsync` of the tree, one edited line, a rebuild, one `playwright test` invocation. Budget it
for every test that claims to guard a named rule.

## A parameter no function destructures is a comment, not a mechanism — and the comment was wrong (T-14 round 2)

`tests/browser/wall.spec.js` passed `settleMs: 60` at two call sites and explained that it
*"forces the app's own velocity term to exactly zero … deliberately free of momentum."*
`drag()` in `tests/browser/support/gestures.js` destructured `{ from, to, steps,
pauseBeforeUp }`. **`settleMs` was silently dropped and had never done anything.** A grep
found the two call sites and the explanation, and never a definition — extra properties on a
destructured options object vanish without a warning from any tool in this stack.

The interesting part is what the phantom concealed. Instrumenting `carousel.js::endDrag` to
report its real internal velocity at `pointerup`, five trials per engine:

| gesture | without the settle move | with it |
| --- | --- | --- |
| 90px / 12 steps | 0.0428–0.0446 (chromium), 0.0303–0.0606 (firefox) | **0.0000** |
| 40px / 8 steps | 0.0221–0.0298 (chromium), 0.0216–0.0238 (firefox) | **0.0000** |

`MIN_VELOCITY` is `0.02`. The momentum branch was firing in **10 of 10** trials, in the two
tests whose comments said it could not — the 90px drag was being carried from position 0.536
to ~0.96 by momentum it was documented to be free of. Both tests passed on **headroom the
regression was allowed to eat**: with a real 15%-short drag-tracking bug injected into
`carousel.js`, the drag test stayed **green on both engines** with the phantom parameter and
went **red on both** once `settleMs` was implemented. Same broken app, same test body,
opposite verdicts.

Two things worth keeping:

- **The mechanism has to be checked, not assumed.** A same-position `pointermove` zeroes
  velocity because the app computes it as `-((event.clientX - lastX) / CARD_STEP) * (16 / dt)`
  — the first factor is exactly 0. But that line is guarded by `if (dt > 0)`, so a settle
  event delivered inside the same millisecond as the last real move would be skipped and the
  stale velocity would survive. The wait is load-bearing. Measurement confirmed the app sees
  the extra event on both engines (`pointermove` count 12→13 and 8→9, final `dx` 0, `dt`
  66–103ms) — neither engine coalesces a zero-delta move away.
- **A test that passes with margin it did not intend to have is not passing for its stated
  reason,** and the comment explaining why it is reliable is then actively misleading — it
  tells the next reader to trust a mechanism that does not exist. When a test's comment names
  a mechanism, either implement the mechanism or rewrite the comment to describe the
  incidental thing the test truly relies on. Leaving the two disagreeing is the worst of the
  three states.

## A cached WebKit binary is not a working WebKit — two of its runtime libraries aren't in this machine's own Ubuntu repos (T-14)

`~/.cache/ms-playwright/webkit-2336` (the build pinned by `@playwright/test@1.62.1`, chosen
specifically to reuse this cache — see AC1) is fully downloaded, and `MiniBrowser` is a real
executable. It still cannot launch:

```
Error: browserType.launch:
Host system is missing dependencies to run browsers.
Please install them with: sudo npx playwright install-deps
```

`ldd` against the actual GTK library (with `LD_LIBRARY_PATH` set the way Playwright sets it)
names four missing `.so`s: `libavif.so.16`, `libgstcodecparsers-1.0.so.0`, `libjxl.so.0.8`,
`libbacktrace.so.0`. This machine is Ubuntu **24.04.2 LTS (noble)** — checked via
`/etc/os-release`, and worth stating plainly because this is the same machine the owner
develops on, not a disposable CI box. Downloading the two packages Playwright's own
`install-deps` list actually names (`libavif16`, `libgstreamer-plugins-bad1.0-0` — fetchable
with plain `apt-get download`, no root needed, then `dpkg-deb -x` to inspect) resolves
`libavif.so.16` and `libgstcodecparsers-1.0.so.0` cleanly. The other two do not have a fix
this simple:

- **`libjxl.so.0.8` does not exist in noble's archives at any component or pocket.**
  `apt-cache madison libjxl0.7` — the only libjxl shared-lib package Ubuntu ships — tops out
  at `0.7.0`. This WebKit build was linked against a newer JPEG-XL ABI than Ubuntu 24.04
  packages at all, full stop, not "not installed yet."
- **`libbacktrace.so.0` has no providing package in the Ubuntu index either** (no `apt-file`
  hit, no `libbacktrace0`/`libbacktrace1` candidate — Debian/Ubuntu do not ship GCC's
  `libbacktrace` as a public shared object the way some other distros do).

The consequence: **`sudo npx playwright install-deps` would not actually fix this host.**
That command's own package list only covers the two libraries this ticket also resolved by
hand; it does not mention `libjxl` or `libbacktrace` at all, so running it as root would still
leave WebKit unable to launch. The honest fix is Microsoft's own `mcr.microsoft.com/playwright`
Docker image (built on whatever base actually satisfies this WebKit revision) or a newer
host distro — not a package this repo, or a `sudo` invocation on this machine, can supply.

**Cost of the workaround not taken:** none was applied. `playwright.config.js` still declares
a `webkit` project (AC5's "wired in" is about the runner, not about this host being able to
run it), and `scripts/test.sh --browsers` attempts it honestly — it fails loudly with the
exact Playwright error above rather than being silently skipped. T-14 shipped real, repeatable,
green coverage on **Chromium and Firefox only** in this environment; WebKit's specs are
written and will run the moment they execute somewhere with matching system libraries, but
nobody should read "webkit project exists in the config" as "WebKit passed here." It did not
run at all. (And when it does run somewhere: it's still a Linux WebKit build, not Safari.)

## Playwright's own inter-event timing, not a browser engine, is what starves a "velocity from the last pointermove" throw (T-14)

The carousel's throw physics (`frontend/src/carousel.js`) compute velocity from ONLY the
delta since the immediately-previous `pointermove` — `-((event.clientX - lastX) / CARD_STEP)
* (16 / dt)` — overwritten on every move, never accumulated. That is a reasonable design for
real input (consecutive samples from one continuous gesture are normally close together in
time), but it means the THROW's momentum is entirely at the mercy of whichever `pointermove`
happens to land last before `pointerup`.

A first attempt at a "flick" test used `page.mouse.move(x, y, { steps: 2 })` — deliberately
imitating a fast, coarse drag. Direct measurement (listening for real `pointermove` timestamps
via `performance.now()`) showed the gap between the last two synthesized move events swinging
from ~5ms to over 150ms, **on both Chromium and Firefox**, run to run, for the identical
gesture. When that final gap happened to be large, the resulting velocity fell under
`MIN_VELOCITY` (0.02) and the settle loop skipped the momentum branch entirely, snapping
straight back to the start card — reproduced empirically at roughly a 30-70% failure rate on
Firefox across repeated real `npx playwright test` runs (7 failures in 10; then 15/15 clean
after the fix below), fewer observed on Chromium in the same sampling but the same underlying
jitter was present in its raw timestamps too.

The fix is a TEST change, not an app change: `steps: 1` (one decisive jump, not several
interpolated ones) gives the gesture exactly one `pointermove`, whose delay since
`pointerdown` measured consistently around 14-16ms on both engines across 8 trials each —
compare the 5-150ms spread `steps: 2` produced. `tests/browser/wall.spec.js`'s momentum test
uses `steps: 1` for exactly this reason. The underlying app code was never touched: this is a
Playwright-multi-step-drag characteristic, not a defect in either engine's Pointer Events
implementation, and rewriting the carousel's velocity math to smooth over uneven real-world
input was out of this ticket's scope (AC4 — a fix belongs in the layer it belongs to, and nothing
here showed the *shipped* feel was actually broken for a real mouse or trackpad).

## An optimistic UI reorder can look "done" on screen before the request that would actually confirm it has even landed (T-14)

`views/queue.js`'s drag-reorder repaints the list live during the drag itself (`insertBefore`
on every threshold crossing, inside `pointermove`) — the row visually settles into its new
slot well before `endDrag` ever calls `commit()` → `api.move()`. A browser-test assertion that
checks `.qrow` DOM order right after the gesture (even via `expect.poll`) can therefore pass
on its very first attempt for a reason that has nothing to do with the server: the reorder it
is "confirming" is the same optimistic DOM state the drag itself already produced, not
evidence the `POST /titles/{id}/move` request has completed.

This surfaced as a real, reproducible (not one-off) Firefox failure: a trace (`trace: 
'retain-on-failure'`, extracted with plain `unzip`) showed the move request's own network
entry recorded with `"status": -1` — the harness's test-teardown closed the page before a
response the request was still waiting on ever arrived, and the row's server-side position
was left completely unchanged (byte-identical to its seeded value) despite the DOM already
showing the "corrected" order. The fix: arm `page.waitForResponse(...)` for the `/move`
request **before** starting the drag (`Promise.all`, not two sequential `await`s — a response
that lands in the gap between arming and starting would otherwise be missed), and don't check
anything else until that response is confirmed `.ok()`. `tests/browser/queue.spec.js`'s
`dragAndWaitForMove` helper is this pattern. The lesson generalises past this one ticket:
**for any optimistic-UI surface, wait for the network call that makes a change real, not
the visual state a client update already produced for free** — the same shape as T-13's
"a test you have never watched fail is not a regression test," one layer up the stack.
> **Note (merge, 2026-09-05):** T-13/T-15 and T-14 grew this page in parallel. Both sets
> are kept. The "TWICE NOW" entry below was written at two instances; the count reached
> **four** by the end of the branch — T-14's entry above carries the full table.

## TWICE NOW: a test that proves a path the real system does not take (T-13, T-15)

Read this one before writing the next test in this repo. It is not a fact about asyncio or
about httpx; it is the failure mode this project keeps producing, and it has cost two
loopbacks on two consecutive tickets.

| ticket | the test | the path it exercised | the path production takes |
| --- | --- | --- | --- |
| T-13 F1 | path traversal | httpx normalised `/../../.env` to `/.env` before it left the client | uvicorn passes `../../.env` through intact |
| T-15 F1 | abandoned preview | `await events.aclose()` throws into the generator, so its `finally` runs | Starlette cancels mid-`send`, the generator is never resumed, and its `finally` never runs |

Both tests passed. Both fixes were wrong. In both cases the test and the bug agreed with each
other about how the system behaves, so the test could not possibly catch it — the guard and
its proof shared one false assumption, which is the only way a green suite hides a live
defect.

**The tell is the same in both:** the test reached the behaviour under test through a
convenience the real caller does not have. `aclose()` and `client.get()` are both "the easy
way to make that happen", and easy was exactly the problem — the real caller is a socket
closing, or a byte string arriving off the wire, and neither is polite.

So, when a test covers what happens on an ABNORMAL path — a disconnect, a cancellation, a
timeout, a malformed request, a crash — write down the mechanism by which the real system
gets there, in one sentence, before writing the test. Then check the test uses that
mechanism and not a stand-in for it. If it uses a stand-in, say so in the test, and find a
second case that does not.

## An async generator's `finally` is not a cleanup guarantee (T-15)

The concrete case behind the entry above. `/api/import/preview` cancelled its resolver from
the streaming generator's `finally`:

```python
    worker = asyncio.create_task(run())
    try:
        ...
        yield _ndjson(progress)      # <- the client leaves while we are parked HERE
    finally:
        worker.cancel()              # <- and this never runs
```

An async generator's `finally` runs only when the FRAME IS RESUMED — by `athrow`, by
`aclose`, or by a garbage collector at some unspecified later time. Starlette's
`StreamingResponse.__call__` races `stream_response` against `listen_for_disconnect` in an
anyio task group and cancels the scope when the client goes, and where that cancellation
lands decides everything:

* inside `await body_iterator.__anext__()` — thrown into the generator, `finally` runs;
* inside `await send(chunk)` — the generator stays suspended at its `yield`, untouched.

The second is the branch production takes, because uvicorn awaits `flow.drain()` whenever the
write buffer is paused, which is exactly the state a large streamed response with a departing
client is in. Measured, 600 rows, disconnect after 40 searches: the in-anext shape stopped
dead; the in-send shape sent **1072 more searches** to TMDB and IGDB on behalf of a client
that had already gone.

**Hang cleanup off something with a defined moment, not off a frame that may never resume.**
For a `StreamingResponse` that is `background=BackgroundTask(...)`: `__call__` awaits it after
the task group unwinds, and an anyio cancel scope absorbs its own cancellation, so the line is
reached on the disconnect path exactly as on the success path — whatever the generator is
doing. `backend/main.py::_PreviewRun` is the shape.

Two things that make the new test able to fail: it drives the real
`StreamingResponse.__call__` over the real ASGI three-tuple with a `send` that never returns
(a paused write buffer, in one line), and it asserts that the searches stopped *while
`body_iterator.ag_frame` was still a frame* — i.e. the guarantee cannot be coming from
generator finalisation. And note `httpx.MockTransport` is no good for building that kind of
test: it calls a SYNC handler, so a whole request can complete without yielding to the loop
and nothing ever interleaves. `tests/factories.py::UpstreamTransport` has a real `await` in
it for that reason.

## "Nothing was added" is not proof that a rollback happened (T-15)

T-15 had to prove T-10's atomicity guarantee still holds with a concurrent fetch phase in
front of the insert loop: force a failure mid-commit inside a 500-row batch, show the row
count unchanged. The obvious test does exactly that and can pass for entirely the wrong
reason. `import_commit` resolves every record BEFORE it opens a transaction, and a failure
in that phase is recorded in `failures` and skipped — so if the sabotage lands in the fetch
rather than in an `INSERT`, the endpoint returns a perfectly correct answer, nothing is
added, the row count is unchanged, and **the transaction was never exercised at all**. The
test is green and the rollback is untested.

So the assertion has to be about what the transaction DID before it died, not only about
what survived. `tests/test_import_atomicity.py` counts the INSERTs that actually executed
and requires 251 of them — rows 0–249 succeeded, row 250 raised — because that number is the
only thing separating "one transaction that rolled back" from "the failure happened before
any writing started". Watch it fail, too: with the single `with connection()` replaced by a
connection per row, the same test reports `assert 252 == 2`, i.e. 250 rows survived.

The general form: **when a test proves an absence, prove the presence of the thing that was
supposed to make the absence hard.** An absence has too many causes.

## `TestClient` collects the whole response body before you can read a line of it (T-15)

AC3 needed proof that `/api/import/preview` reports progress *while it is still resolving*.
The obvious test streams the endpoint and timestamps each event:

```python
with client.stream("POST", "/api/import/preview", json={"text": csv}) as response:
    for line in response.iter_lines():   # every line arrives at the same instant
```

Every timestamp came back within 1ms of every other, on a request that genuinely takes ~1.4
seconds over a real socket. The server was streaming perfectly; the client is not.
`starlette.testclient._TestClientTransport.handle_request` writes each `http.response.body`
message into an `io.BytesIO` and finishes with
`raw_kwargs["stream"] = httpx.ByteStream(raw_kwargs["stream"].read())` — the response is
fully materialised before httpx ever hands it back. `iter_lines()` is then iterating a
buffer, and any timing assertion built on it is measuring that buffer.

This is the same trap as the path-traversal lesson below, in a different costume: **the
in-process test client is the one thing that cannot reproduce the property under test.** The
fix is the same shape, too — test the layer that does the work. `_preview_events` is an async
generator, so driving it directly and timestamping each `yield` measures exactly what a
socket reader would see, with nothing in between. Confirmed separately against a real uvicorn
on loopback: `transfer-encoding: chunked`, 246 progress events, first at 561ms, 50% at 971ms,
result at 1357ms.

Corollary for the other direction: **a latency stub that returns instantly cannot measure
concurrency.** A sequential loop and an eight-way-concurrent one over zero-cost awaits
produce the same wall clock, so the "after" number would have looked like a win with nothing
changed. `tests/test_import_scale.py`'s stubs sleep 2ms for exactly this reason, and the
sabotage run (`SEARCH_CONCURRENCY = 1`) is what proves the ceiling can still fail.

## A concurrency cap is not a rate limit, and 429 here is silent (T-15)

Two separate ceilings, and bounding one does nothing for the other. Eight requests in flight
at 200ms each is **40 requests/second** — ten times IGDB's published limit of 4/s, even
though "8 at once" is precisely IGDB's own open-request cap. `backend/sources/base.py`
carries both numbers per source for that reason: `open_requests` is a semaphore,
`per_second` is a departure clock, and a request has to satisfy both.

What makes this correctness rather than manners in this codebase: `raise_for` turns HTTP 429
into a `SourceError`, and the import resolver catches `SourceError` **per row** and marks
that row `unmatched`. Crossing the limit therefore does not fail loudly — it quietly turns a
thousand-row import into a thousand rows that "have no match", on the owner's real list, with
nothing anywhere saying the upstream refused. Before adding concurrency to anything that
talks to a rate-limited service, find out what that service does on refusal and what the
caller does with the refusal; if the answer is "swallows it per item", the bound is load
bearing.

## `asyncio.Lock`/`Semaphore` bind to the first event loop that touches them (T-15)

A module-scope `asyncio.Lock()` works in the first test and raises
`... is bound to a different event loop` in the second, because each `TestClient` (and each
`asyncio.run`) is a fresh loop while the singleton is not. The primitive latches its loop on
first use and never lets go. So any long-lived limiter, pool or gate that lives at module
scope has to rebuild its primitives when the running loop changes — `RateLimit._bind()` does
exactly that, and resetting the pacing clock alongside them is correct rather than sloppy,
since a new loop means none of our requests are in flight.

Two smaller ones from the same ticket, worth knowing before losing an hour to either:
`asyncio.gather` does **not** cancel its siblings when one child raises (only when the gather
itself is cancelled), so an unexpected failure leaves the other hundreds of tasks running
against the upstreams for a response nobody will read — cancel them explicitly. And
`sqlite3.Connection` has no instance `__dict__`, so `conn.execute = wrapper` is an
`AttributeError`, not a seam; `conn.set_trace_callback(fn)` is sqlite3's own hook and fires
per statement, the failing one included.

## A path-traversal test written the obvious way tests nothing — the HTTP client eats the `..` (T-13)

`client.get("/../../.env")` never delivers a `..` to the handler. `TestClient` is built on
**httpx**, and httpx applies RFC 3986 dot-segment removal to the URL *before the request
leaves the client*: what goes on the wire is `GET /.env`. The handler sees `full_path=".env"`,
`dist/.env` does not exist, the SPA shell comes back, the test goes green — and it would go on
green with the containment check in `backend/main.py::spa` deleted. T-13's first attempt
shipped exactly that: all 18 tests in `tests/test_privacy_boundary.py`, including the one
named *does not leak a real secret file*, passed against a copy of `spa()` with containment
removed (T-2's pre-fix shape).

The collapse is the **client's**, not the server's. Measured against a live uvicorn on
loopback with `curl --path-as-is`:

| sent raw | reaches the handler as | via TestClient |
| --- | --- | --- |
| `/../../.env` | `../../.env` — **intact** | `.env` (collapsed by httpx) |
| `/%2e%2e/%2e%2e/.env` | `../../.env` | `../../.env` |
| `/..%2f..%2f.env` | `../../.env` | `../../.env` |
| `/%252e%252e/%252e%252e/.env` | `%2e%2e/%2e%2e/.env` (decoded once) | `../../.env` (decoded twice) |

So the exploit is entirely real against a real server — uvicorn and Starlette do not remove
dot segments — and the in-process test client is the one thing that cannot reproduce it in its
plainest form. Note the last row: TestClient decodes once into `scope["path"]` and Starlette's
path convertor unquotes again, so a doubly-encoded payload behaves *differently* under
`TestClient` than under uvicorn. Neither is dangerous here (containment catches both), but do
not reason about encoding from the test client alone.

What to do when writing one of these:

1. **Call the route function directly** with the raw string a non-normalising client sends.
   No HTTP layer, nothing to soften the payload. This is the layer that does the work.
2. **Percent-encode** (`%2e%2e`, `%2E%2E`, `..%2f`) for the over-HTTP layer, and add a
   tripwire proving those still arrive as `..` — walk out of the served root and back in to a
   real asset and check the content type. If some future httpx collapses those too, the
   tripwire fails loudly instead of the whole layer going quietly blind.
3. **Aim at a file that exists.** Traversal to a missing path falls through to the shell
   anyway, so the test passes without proving anything. Plant a canary (under `tmp_path`,
   never at the repo root — see the next lesson) or use `/etc/passwd`.
4. **Never hard-code a `../` depth.** `../../../../../../etc/passwd` climbs out of an
   eight-deep worktree into `/tmp/claude-1000/etc/passwd`, which does not exist — the case
   then passes on a miss. Compute it: `os.path.relpath(target, served_root)`.

The rule underneath all four: **a regression test you have never watched fail is not a
regression test.** Strip the check out of a *copy* of the code and run the test against it.
Five minutes, and it is the only thing that distinguishes a guard from a decoration.

## The repo root is not a sandbox — plant test fixtures under `tmp_path` (T-13)

The same file asserted `not (repo_root / ".env").exists()` before writing a canary there. In
a disposable worktree that is true and the suite is green; on the owner's machine `.env` is a
live file with real API keys, so the suite failed on the one checkout it exists to protect —
and the failure was in the privacy test, which reads like a breach until you look. A test
must never write to, unlink, or depend on the *absence* of anything at the repo root: that
tree carries `.env`, `data/` and the owner's database. `tmp_path` is free and is deleted for
you; if a test needs a file at a particular *position* relative to the app (outside the
served root, say), compute the path to it rather than moving the file to where the arithmetic
is easy.

## `from module import name` binds a NAME, not a live reference back to the source module (T-13)

`backend/sources/tmdb.py`, `igdb.py`, `anilist.py` and `backend/artwork.py` all do
`from .sources.base import client` (or `from .base import client`). Each of those is its own
binding in the importing module's `__dict__`, made once at import time. **Monkeypatching
`backend.sources.base.client` does nothing to any of the other four** — they still hold the
original function object.

The rule this generalises to: before patching a shared helper for a test (or swapping an
implementation at runtime for any reason), grep every place it is imported and check *how*.
`import module` then `module.thing` stays live because the attribute lookup happens at call
time on the shared module object. `from module import thing` freezes a reference at import
time and needs patching wherever it landed. `tests/conftest.py::no_network` patches all five
module-level `client` bindings for exactly this reason — see its docstring for the full list.

## Module-scope side effects mean setup has to happen before FIRST import, not after (T-13)

`backend/config.py` builds `config = load_config()` at import. `backend/main.py` ends with
`app = create_app()` at module scope, which calls `bootstrap()` (creates/opens the database)
**and** decides once, via `dist.is_dir()`, whether the SPA catch-all route exists at all. A
fixture, test, or script that wants a different `MEDIA_LIST_DB`, or wants the SPA route to
exist, has to arrange that reality before `backend.main` — or even `backend.config` — is
imported for the first time in the process. After that point the decision is already baked
into the frozen `config` singleton or the registered route table, and nothing short of
re-importing (which Python won't naturally do) changes it.
`tests/conftest.py` is structured with a hard comment marker for exactly this reason: an
environment-setting line below the "everything past here may import backend" marker is a
bug, not a style choice.

## Evidence and plan documents describe intent; the code is the actual contract (T-13)

`.autodev/plans/T-13.md` described star validation as "0–5 integers accepted". The code
(`backend/main.py::update_title`) enforces `1 <= stars <= 5` — 0 is rejected — and T-9's own
evidence table already recorded `0 -> 400`. The plan was simply imprecise. When freezing
behaviour into tests, read the code path being frozen directly rather than trusting a prose
description of it, even one written for this exact ticket; use evidence documents to learn
*what to test*, not to learn *what the correct answer is*.

## `python-dotenv`'s `load_dotenv` does not override an already-set environment variable (T-13)

`config.py`'s own docstring says as much ("real environment variables win over it"), and it
is the lever that makes test credentials deterministic: setting `TMDB_API_KEY` (etc.) in
`os.environ` *before* `backend.config` is imported means the module's own
`load_dotenv(REPO_ROOT / ".env")` call is a no-op for those names, regardless of whether a
real `.env` with real keys happens to sit next to the code being tested.
