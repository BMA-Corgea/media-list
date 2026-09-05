"""AC4 — the bundle check is a test.

T-6's own history: "A green `vite build` once passed with a module never imported." A
successful build proves the toolchain ran; it does not prove any particular module's code
made it into the artifact actually served. One distinctive string per view module, grepped
out of the real built output, is the tripwire for that — cheap, and it already caught
something real once (T-7's evidence records applying exactly this check to `queue.js`).

A needle only works if it is unique to the module it stands for. `home.js`'s used to be
"Up next", which is also a nav label in `main.js` — the entry point, always bundled — so
dropping `home.js` from the imports (T-6's exact regression) left the string in the bundle
and the case still passed (T-13 round 2). `test_each_marker_string_is_unique_to_its_module`
is the guard against that rot returning: it is the reason a needle may be trusted at all.

Uses the `frontend_dist` fixture: conftest.py builds `frontend/dist` once per session
(before `backend.main` is ever imported — see conftest's top) if it is not already there,
skipping with a clear reason if npm is unavailable rather than failing outright.
"""

from __future__ import annotations

from pathlib import Path

import pytest

#: One string that can only be in the bundle if the module owning it was actually included.
#: Picked from real UI text / class names, not from code comments (which esbuild strips).
#: Every entry is enforced unique by `test_each_marker_string_is_unique_to_its_module` —
#: do not add one without running that test.
STRINGS_BY_MODULE = {
    "views/home.js": "Nothing on the list yet",
    "views/queue.js": "drag to reorder",
    "views/add.js": "no art",
    "views/seen.js": "Nothing here yet",
    "views/title.js": "How was it? (required)",
    "views/wheel.js": "btn--spin",
    "views/transfer.js": "Export everything as CSV",
}


@pytest.fixture(scope="module")
def bundle_text(frontend_dist: Path) -> str:
    """The built JavaScript, and only the JavaScript.

    Vite emits stylesheets as their own `assets/*.css` asset, so a needle that also appears
    in `skins/base.css` (`btn--spin` does) still cannot reach this text except through the
    module that owns it. `test_stylesheet_text_never_lands_in_the_script_bundle` is what pins
    that assumption; the uniqueness guard below is scoped to `*.js` because of it.
    """
    assets_dir = frontend_dist / "assets"
    assert assets_dir.is_dir(), f"{assets_dir} missing — build produced no assets/ directory"
    js_files = list(assets_dir.glob("*.js"))
    assert js_files, f"no .js files under {assets_dir} — the build produced no bundle"
    return "\n".join(f.read_text(encoding="utf-8") for f in js_files)


def test_bundle_was_actually_produced(frontend_dist: Path):
    assert (frontend_dist / "index.html").is_file()
    assert (frontend_dist / "assets").is_dir()


@pytest.mark.parametrize("module_path, needle", list(STRINGS_BY_MODULE.items()))
def test_each_view_modules_marker_string_reached_the_bundle(bundle_text, module_path, needle):
    assert needle in bundle_text, (
        f"{needle!r} (from frontend/src/{module_path}) is missing from the built bundle — "
        "that module's code did not make it into what actually gets served, even though "
        "the build itself reported success (T-6's exact regression)."
    )


def test_each_marker_string_is_unique_to_its_module(repo_root: Path):
    """The guard on the guard: a needle that appears in a second module proves nothing.

    Scoped to `*.js` under `frontend/src/` because those are exactly the files whose text can
    end up in the JavaScript bundle the test above greps — the sibling test below is what
    makes that scoping safe. A failure here means the *needle* is stale, not the app: pick a
    string the module genuinely owns.
    """
    src = repo_root / "frontend" / "src"
    modules = sorted(src.rglob("*.js"))
    assert modules, f"no JavaScript sources under {src}"

    for module_path, needle in STRINGS_BY_MODULE.items():
        owners = [
            str(f.relative_to(src)) for f in modules
            if needle in f.read_text(encoding="utf-8")
        ]
        assert owners == [module_path], (
            f"{needle!r} is supposed to identify frontend/src/{module_path} in the bundle, "
            f"but it appears in {owners or 'no source file at all'}. A needle shared with "
            "another module cannot prove its own module was bundled — the bundle would still "
            "contain it with that module dropped entirely. Pick a string unique to "
            f"{module_path} (T-13: this is how the 'Up next' needle rotted)."
        )


def test_stylesheet_text_never_lands_in_the_script_bundle(bundle_text: str, repo_root: Path,
                                                          frontend_dist: Path):
    """Pins the CSS/JS split the uniqueness guard's `*.js` scoping depends on.

    If a future Vite config inlined stylesheets into the JavaScript, a class-name needle that
    also lives in `skins/base.css` would be satisfied by the CSS text alone and would stop
    proving its module was bundled. `@keyframes` is stylesheet-only syntax: it must be in the
    built CSS and absent from the built JS.
    """
    css_files = list((frontend_dist / "assets").glob("*.css"))
    assert css_files, "the build emitted no stylesheet asset at all"
    css_text = "\n".join(f.read_text(encoding="utf-8") for f in css_files)

    assert "@keyframes" in css_text, "no @keyframes in the built CSS — pick another marker"
    assert "@keyframes" not in bundle_text, (
        "stylesheet text is being inlined into the JavaScript bundle. Needles shared with "
        "frontend/src/skins/*.css (btn--spin) are no longer proof that their module was "
        "bundled — widen test_each_marker_string_is_unique_to_its_module beyond *.js."
    )


def test_the_marker_strings_are_still_present_in_source(repo_root: Path):
    """Cheap sanity check on the fixture data itself: if a view is rewritten and a marker
    string genuinely goes away, this fails with a clear message pointing at THIS file,
    instead of the bundle test above failing and looking like a real regression."""
    for module_path, needle in STRINGS_BY_MODULE.items():
        source = (repo_root / "frontend" / "src" / module_path).read_text(encoding="utf-8")
        assert needle in source, (
            f"{needle!r} no longer appears in frontend/src/{module_path} — update "
            "STRINGS_BY_MODULE in tests/test_bundle.py to a still-current marker string."
        )
