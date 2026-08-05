# Overview

## Architecture

Use an **onion architecture**. Dependencies point inward only — an inner layer
must never import from an outer one.

```text
        UI / drivers (wxPython frame, panels, PollerThread)
      ┌───────────────────────────────────────────────────┐
      │   Infrastructure / adapters                       │
      │  ┌─────────────────────────────────────────────┐  │
      │  │   Application (use cases)                   │  │
      │  │  ┌───────────────────────────────────────┐  │  │
      │  │  │   Domain (entities + pure logic)      │  │  │
      │  │  └───────────────────────────────────────┘  │  │
      │  └─────────────────────────────────────────────┘  │
      └───────────────────────────────────────────────────┘
```

- **Domain** — entities and pure business rules: `Snapshot`, usage/quota value
  objects, model-ID normalization, cost computation, rolling-window math. No
  I/O, no `wx`, no filesystem, no third-party SDKs. Standard library only.
- **Application** — use cases that orchestrate the domain: aggregation, refresh
  cycles, staleness rules. Depends on the domain and on **ports** (abstract
  interfaces it declares itself, e.g. `TranscriptSource`, `QuotaSource`,
  `PricingSource`). Never depends on a concrete reader.
- **Infrastructure** — adapters that implement those ports: JSONL transcript
  tailing, `~/.claude.json` reads, pricing tables, config, clock. This is the
  only layer allowed to touch the filesystem or parse external formats.
- **UI / drivers** — wxPython frame and panels, `PollerThread`, entrypoint
  wiring. Composes concrete adapters and injects them into the application
  layer at startup (composition root). Widgets render a `Snapshot`; they do not
  compute one.

Rules:

- Inward-only imports. If an inner layer needs an outer capability, define a
  port and inject the implementation.
- Cross layers with immutable, plain data (frozen dataclasses), not with live
  file handles or `wx` objects.
- The domain and application layers must be unit-testable with no filesystem,
  no GUI, and no sleeping — use fakes for ports rather than temp dirs or real
  transcripts where practical.
- Keep the layer boundaries visible in the package layout (e.g. `domain/`,
  `application/`, `infrastructure/`, `ui/`) so a violating import is obvious in
  review.

## Open Source

This should only implement MIT license packages. Prompt if you attempt to use any others

### Approved exceptions

- **wxPython** — approved 2026-08-05. Licensed under the wxWindows Library
  Licence (LGPL v2 plus an exception permitting binary object code versions of
  derived works to be distributed under your own terms). OSI-approved and
  GPL-compatible. This project's own source may stay MIT; the copyleft reaches
  only wxWidgets/wxPython source files. Installing via `pip` redistributes
  nothing, so no obligations trigger. If a frozen binary is ever shipped
  (PyInstaller/py2app), include the wxWindows licence text as attribution. The
  one real obligation: modifications to wxWidgets/wxPython source itself, if
  distributed, must ship their source. Do not prompt again for wxPython.
