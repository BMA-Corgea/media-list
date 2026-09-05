---
name: hardening-checklist
description: The project's hardening checklist
type: reference
---

# hardening-checklist

The checks this project applies before shipping risky change classes. Grow it from review
findings and incidents.

## Before touching anything that stubs or replaces a shared helper (T-13)

- [ ] Grep every place the helper is imported, and check *how*: `import module` (attribute
      lookups stay live, patch the module) vs. `from module import name` (a frozen binding —
      patch it everywhere it landed, not just at its definition). See `kb/wiki/lessons.md`'s
      entry on this; `backend/sources/base.py::client` is the concrete example.
- [ ] If the helper is meant to guard against a real external effect (network, disk, a paid
      API), prove the guard positively — call the real code path with the guard installed and
      assert the attempt was actually intercepted, not merely that the test never happened to
      trigger it. Absence of a failure is not evidence of a working guard.

## Before adding or changing anything that runs at IMPORT time (module scope, not inside a function)

- [ ] Does it read `config`, open a database connection, register a route, or otherwise
      decide something based on the filesystem/environment as it exists at that moment?
- [ ] If so: every test, fixture, or script that needs a different reality (a different DB
      path, a built frontend, a different credential) MUST arrange it before that module's
      first import in the process — not "before the test runs" if the module was already
      imported by something else first (a conftest.py, another fixture, an earlier test).
      `backend/config.py` (`config = load_config()`) and `backend/main.py`
      (`app = create_app()` → `bootstrap()` + the SPA route's `dist.is_dir()` check) are both
      exactly this shape.

## Before trusting a plan, spec, or evidence document's prose description of behaviour (T-13)

- [ ] When freezing existing behaviour into a test, read the actual code path, not a summary
      of it — even a summary written specifically for the ticket at hand. Use the
      plan/evidence to learn *what deserves a test*, confirm *what the test should assert*
      against the code itself.

## Before writing a test that needs the built frontend (`frontend/dist`)

- [ ] Remember `backend/main.py::create_app()` only mounts the SPA catch-all
      `if dist.is_dir()`, decided once at `backend.main`'s first import. Building `dist`
      inside an individual test file is too late if anything already imported `backend.main`
      (which `tests/conftest.py` does, for every test in the run). The build has to happen
      before that import — see conftest's top-of-file ordering.
- [ ] Skip (with a clear reason), don't fail, when the toolchain the test needs (npm, a real
      credential, a browser) is unavailable — a missing tool is not a defect in the app.
