"""AC4 — the bundle check is a test.

T-6's own history: "A green `vite build` once passed with a module never imported." A
successful build proves the toolchain ran; it does not prove any particular module's code
made it into the artifact actually served. One distinctive string per view module, grepped
out of the real built output, is the tripwire for that — cheap, and it already caught
something real once (T-7's evidence records applying exactly this check to `queue.js`).

Uses the `frontend_dist` fixture: conftest.py builds `frontend/dist` once per session
(before `backend.main` is ever imported — see conftest's top) if it is not already there,
skipping with a clear reason if npm is unavailable rather than failing outright.
"""

from __future__ import annotations

from pathlib import Path

import pytest

#: One string that can only be in the bundle if the module owning it was actually included.
#: Picked from real UI text / class names, not from code comments (which esbuild strips).
STRINGS_BY_MODULE = {
    "views/home.js": "Up next",
    "views/queue.js": "drag to reorder",
    "views/add.js": "no art",
    "views/seen.js": "Nothing here yet",
    "views/title.js": "How was it? (required)",
    "views/wheel.js": "btn--spin",
    "views/transfer.js": "Export everything as CSV",
}


@pytest.fixture(scope="module")
def bundle_text(frontend_dist: Path) -> str:
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
