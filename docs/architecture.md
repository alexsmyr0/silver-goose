# Silver Goose architecture

## Scope

Local Mac application: OpenArt, explicit MCP/Chat/Director choice, eight existing video
formats, and two tabs. No social accounts, provider clients, automatic posting/submission,
reporting, earnings, scheduled builds, login, hosting, Cutter or AI footage generation.
The common controls live in Assets and Build settings; there is no second campaign.

The renderers were extracted from the local Golden Goose checkout at
`f9fb4be104539868493012b9941ceb9ed593fec7`. Its rendering geometry, timing, media
normalization, typography, recipe selection and successful-build allowances remain the
production owners. The local server, paths, history adapter, asset editing, launcher and
batch coordinator are Silver Goose code. No Golden Goose modules are imported at runtime.

## Ownership

| Area | Entry points |
| --- | --- |
| Local HTTP / request validation | `source/app.py` |
| Two-tab interface | `source/templates/index.html`, `source/static/app.js`, `source/static/app.css` |
| Content/format availability | `source/catalog.py`, `source/production.py` |
| Batches and cross-process edit gate | `source/jobs.py`, `source/worker.py` |
| Paths and explicit initialization | `source/paths.py` |
| Successful-build history / unique IDs | `source/manifest.py`, `source/ledger_lock.py` |
| Assets / text editing | `source/assets.py`, `source/csvfile.py` |
| Tutorials and compatibility | `source/tutorial_libraries.py`, `source/pairing.py` |
| Reuse quantities / wording budgets | `source/formula.py`, `source/wording_allowances.py` |
| Silent formats | `source/make_videos.py` |
| Farm variants | `source/make_farm.py`, `source/make_mcp_farm.py` |
| Hook Story | `source/reaction*.py`, `source/make_reaction.py` |
| Bottle spin | `source/tutorial_story*.py`, `source/make_tutorial_story.py` |
| AI LARP | `source/ai_larp*.py`, `source/make_ai_larp.py` |
| Native captions/HDR/segmentation | `source/*.swift`, `source/speech.py`, `source/captions.py` |
| Final encoding | `source/video_encode.py`, `source/encode.py` |
| First run / double click | `Start Silver Goose.command`, `source/bootstrap.py` |

## Library

`SG_LIBRARY` selects an isolated library before any imports. Normal launch sets it to
`library` beside `source`. Importing paths creates/migrates nothing. `paths.prepare()`
explicitly creates missing folders and starter tables, never replaces populated files.
There are no symlinks into Golden Goose and no account paths.

- `assets/openart/`: shared ingredients, with role folders used by the renderers.
  The MCP farm retains the renderer's physical `mcp content farm` asset folder name.
- `data/openart/`: build settings, tutorial tags, wording, durable history and ID sequence.
- `videos/openart/<format>/`: one output folder per format, shared across content types.
- `work/`: jobs/logs, native render intermediates, speech cache, previews and recovery files.
- `trash/`: user-removed ingredients. Nothing is deleted automatically to save space.

Only successful history rows spend allowances. Failures spend none. Output deletion does
not refund uses. IDs increase across every format and survive restarts and failed builds.
Tutorial eligibility is checked against file contents. Product selection is request-local
and passed explicitly to worker processes, not stored as a fake account.

## Build lifecycle

1. Validate product, whole quantities, available ingredients and reuse limits.
2. Acquire one nonblocking filesystem lock shared by builds and asset mutations.
3. Start a detached worker with that lock inherited. It runs each requested format with
   `sys.executable`, and passes the lock through to the rendering process.
4. Record outputs during rendering. The UI reads actual completed rows and tails the log.
5. A failed format does not discard successful outputs from the others. Report complete,
   partial, failed or interrupted honestly. Finished exports can be recovered if recording
   their history fails; broken exports stay out of the finished-video folders.

The server has its own instance lock. A second launch checks the existing panel's app and
library identity before reopening it. It uses a free loopback port and never kills another
process. All mutations require the page's local token and matching Origin; this is a
localhost request guard, not a user login. The server is not exposed to the LAN.

## Handoff and first run

`scripts/import_local_library.py` is an explicit one-time importer requiring an empty
new library. It reads the source files without importing Golden Goose, copies only the
shared asset roles and configured accounts' private footage, deduplicates compatible
sources, resets usage, excludes posting history/credentials and records checksums.
One missing tutorial tag was removed because its source file was absent.

`scripts/package_for_john.py` produces `dist/Silver Goose` and a ZIP. Only allowlisted
production settings and private ingredients accompany the code. No generated videos,
manifest, ID sequence, jobs, compiled native binaries or virtual environment is shipped.
Executable launcher permissions and every archive entry are verified.

The launcher detects missing dependencies; it asks before installing system tools.
Python packages are installed inside this folder, native helpers compiled on this Mac,
and missing Apple speech assets prepared through the official system API. First setup
needs internet. Runtime recognition and rendering run locally. No automatic upgrades,
service registration, application bundle or managed installer is included.

Dependency installation follows [Homebrew's installer](https://brew.sh/) and
[Apple's Command Line Tools workflow](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools/).
Speech model preparation uses [Apple AssetInventory](https://developer.apple.com/documentation/speech/assetinventory).

## Changes and verification

Use temporary libraries for tests. Never import Golden Goose's live application to test
Silver Goose. All private library files and delivery archives are ignored by Git.
See [verification](verification.md). Editing source is not permission to commit or push.
