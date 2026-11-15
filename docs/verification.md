# Verification — 30 September 2026

## 15 November 2026: silent formats re-synced with Golden Goose's builder

- **6 silent-builder tests passed** (`tests/test_silent_builder.py`, disposable library).
  They cover:
  - the Builder tab's count of unused covers;
  - opening lines and tick-and-cross wording having no use limit while the enabled switch
    still applies;
  - saving wording without a use limit;
  - the real render command: tutorial fitted, not cropped, plus hook and tutorial speed,
    tint, zoom/shift and the later song start;
  - a whole run: four micro changes on every video, no repeated cover, outputs in
    per-format folders, and a refusal once covers run out.
  Each test was checked to fail when the code it covers was broken.
- 22 core tests (the pairing test was removed with pairing) and 4 launcher tests passed.
  Compilation, JavaScript and shell syntax checks passed.
- **Real renders:** two Line, then card, two Card only and two Tick and cross videos were
  built with Silver Goose's own font, logos, songs and wording, plus generated stand-in clips.
  The library holds no scenes or tutorials yet. The stand-ins were 60fps scenes and a 4:5
  tutorial with white bands burned in near its top and bottom edges.
  - All six fully decoded: H.264 1080×1920, square pixels, 30fps, AAC.
  - Each length equals the cut plus the tutorial at its drawn speed, and the song's drop
    lands on the cut.
  - Frame checks showed each format's overlays at the right moments and the tutorial fitted
    with bars, its bands uncut by the 2–3% zoom.
  - Not tested: real footage and a panel-triggered build in the browser.

## Results, 30 September 2026

- **4 launcher recovery tests passed** with real offline virtual-environment creation in
  temporary folders containing spaces. Covers broken interpreter links (reproducing John's
  exact error), missing pip, a dangling environment directory link, and reuse on a second
  launch. Broken environments are preserved and library contents remain unchanged.
- **23 core tests passed** in a disposable library. The original 22 also passed using the fresh launcher's
  isolated Python environment. Covers cross-process IDs and locks, request-local content
  selection, traversal/symlink refusal, corrupt-data handling, atomic uploads, text edits,
  shared tutorial settings, successful-only usage, recovery files and local HTTP guards.
  The added gallery check covers moved, restored and empty files, preserved history,
  and missing records not consuming the visible list limit.
- **All eight formats rendered successfully.** Nine MP4s: one per format, plus a second
  AI LARP output to cover both plain and captioned variants. Every output was fully
  decoded with FFmpeg and checked for H.264 picture, AAC audio, square pixels and the
  original format dimensions (720×1280 for AI LARP; 1080×1920 for the others).
- Line, comparison, both farms and Bottle spin used copies of actual local ingredients.
  Card, Hook Story and AI LARP used temporary fixture clips because those input pools
  were missing. Fixtures were prepared from existing media solely in the test library.
  No fixture footage or generated test video goes into John's handoff.
- Bottle spin and AI LARP automatic captions ran through the compiled Apple speech helper.
  An additional Hook Story render passed with native person-background removal enabled.
- Browser checks covered all asset groups, settings dialogs, wording saves, Hook Story
  settings saves, a UI-triggered build, video playback and desktop/mobile layouts.
  No JavaScript errors or horizontal mobile overflow were found. Screenshots were reviewed.
- A second app launch reopened the existing instance. A two-video batch continued after
  the panel was stopped and completed after the panel was restarted.
- A separate folder with spaces in its name successfully ran the launcher: new virtual
  environment, package installation, Swift compilation, Apple speech preparation and server.
- Python compilation, JavaScript parsing, shell syntax and the focused Python undefined-name/
  unused-import checks passed. These checks remain advisory, without Git hooks.
- Golden Goose's Git working tree remained clean. No Golden Goose application was imported,
  no live panel was restarted, and its original assets/settings/history were not edited.

## Findings resolved during verification

The extracted speech module needed its caption grouping constants. Text saves needed to
retain generated usage columns. Corrupt formula values had been hidden by a default-value
fallback. Those were corrected and covered by tests. Preview checks also exposed an inherited
fractional pixel aspect ratio; final encoding now records an exact 9:16 display canvas.
The first dimension assertion incorrectly assumed AI LARP was 1080p; it was corrected to
its existing 720p format, without changing the renderer's layout.

Playwright's bundled Chromium lacks H.264/AAC support in this environment. Playback was
therefore tested successfully in installed Google Chrome. This was a test-browser limitation;
the local HTTP endpoint correctly served MP4 byte ranges.

## Not tested / practical limits

- A completely clean Mac with no Homebrew, Python, FFmpeg or Apple Command Line Tools was
  not available. The first-run installation branches follow the official tool workflows;
  the fresh Python environment and native compile path were executed locally.
- Apple's English speech model was already installed. The missing-model download branch
  compiles against the local SDK but was not forced by removing system assets.
- Intel Macs and older macOS versions were not tested. macOS 26+ is required; the tested Mac
  uses Apple Silicon. A missing/unsupported Apple speech engine reports an error.
- The starter library includes music but no video ingredients. Each recipient uploads
  their own footage and tutorials before building. The successful render checks above used
  the earlier populated library or temporary fixtures.
- No test can guarantee a remote platform will accept a manually posted video; Silver Goose
  makes local videos and has no posting integration.

## Repeatable checks

From this repository, with the required Python packages installed:

```sh
python3 tests/test_core.py
python3 tests/test_silent_builder.py
python3 tests/test_launcher.py
python3 -m compileall -q source
node --check source/static/app.js
bash -n 'Start Silver Goose.command'
python3 tests/render_smoke.py --library library
```

The core suite sets its own temporary `SG_LIBRARY` before importing the app. The render
smoke suite copies the supplied library's ingredients/settings to a temporary directory,
excludes history and prints the resulting `report.json` path. It requires the imported
OpenArt assets, macOS, FFmpeg and Swift. It never writes to its supplied library.
Private screenshots, render reports and delivery files stay outside Git (`evidence/`,
`dist/` or the printed temporary directory). Rebuild the handoff with
`python3 scripts/package.py`; move an existing `dist/Silver Goose` aside first.
