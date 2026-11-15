# Silver Goose

A local Mac video builder for OpenArt. **Builder** and **Assets** only.
Choose **MCP**, **Chat** or **Director**, enter quantities, and build. Post the finished
videos yourself. No social accounts, API keys, posting service or earnings screen.

## First launch

You need a Mac with **macOS 26 or newer** (tested on Apple Silicon), an internet
connection, and the password of an **administrator** account on that Mac. The first launch
installs free tools and can take a while; later launches skip all of it.

1. Double-click **Silver Goose.zip**. Put the **Silver Goose** folder somewhere you can
   find it, such as your Desktop.
2. Double-click **Start Silver Goose.command** in that folder. A Terminal window opens.
   **Leave it open** the whole time you use Silver Goose.
3. If macOS says it cannot verify the file: click **Done**, open **System Settings →
   Privacy & Security**, scroll down to **Security**, click **Open Anyway** beside
   *Start Silver Goose.command*, and confirm with your password or Touch ID.
4. If Apple asks to install the **command line developer tools**, click **Install** and
   agree. Silver Goose waits in the Terminal window and carries on when they are installed.
5. When asked to install Python and FFmpeg, press **Return**. When asked for your Mac
   password, type it and press **Return** (nothing appears while you type).
6. Wait while it finishes setting up. The panel opens in your web browser when it is ready.

Then add your own footage in **Assets** (see below) and build. Nothing is paid for and no
account is needed.

### Your library, and updating

Your footage, settings and finished videos are kept in **Movies → Silver Goose Library**
in your home folder, not inside the Silver Goose folder. Back that folder up to keep
your work.

To update Silver Goose, unzip the new version, double-click its **Start Silver
Goose.command**, and then delete the old Silver Goose folder. Your library stays where it
is. An older version that kept its library inside its own folder has it moved to Movies
automatically the first time the new version starts (close the old Terminal window first).

### If something goes wrong

- Close the Terminal window and double-click the launcher again: it picks up where it
  stopped. A copied or broken Python setup is backed up under `.venv-old-*` and rebuilt.
  Do not include `.venv` when copying Silver Goose to another Mac; share the ZIP instead.
- To choose a port, run `./"Start Silver Goose.command" --port 8080` in Terminal.
  If the panel is already running, another launch just reopens it.
- For a Desktop shortcut, right-click the launcher, choose **Make Alias**, and move the
  alias to the Desktop. A copied launcher asks you to select the Silver Goose folder.

## Build

Select a content type in Builder. The available formats are:

| Content | Formats |
| --- | --- |
| MCP | Line, then card; Card only; Tick and cross; Content farm; MCP content farm; Hook Story |
| Chat | Content farm; Hook Story |
| Director | Content farm; Hook Story; Bottle spin; AI LARP |

Availability is an upper bound: the renderer also checks valid source media and distinct
combinations. The build log reports errors and the actual number completed. One batch
runs at a time. Asset edits wait until it finishes. Closing a browser tab is fine;
closing the panel does not cancel an active batch. Relaunch to see its results.

Finished videos are previewed in Builder, with **Save video**, **Copy caption** when
available, and **Open folder**. Every content type shares the same format folders:

```text
Silver Goose Library/videos/openart/line/
Silver Goose Library/videos/openart/card/
Silver Goose Library/videos/openart/compare/
Silver Goose Library/videos/openart/farm/
Silver Goose Library/videos/openart/mcp_farm/
Silver Goose Library/videos/openart/reaction/
Silver Goose Library/videos/openart/tutorial_story/
Silver Goose Library/videos/openart/ai_larp/
```

Moving or deleting a video removes its card automatically within a few seconds.
Its build history and reuse counts are preserved. Moving it back restores its card.

## Assets

Add prepared clips in Assets; preview or remove files, edit wording and music settings,
assign tutorials to a content type, and choose tutorial folders. Build settings control
reuse quantities. Assets → Common holds font, logos, base music, emoji, post captions,
and caption vocabulary/corrections.

- Line, then card / Card only / Tick and cross: tutorials are used exactly as uploaded, so
  burn their captions in first. A tutorial that is not 9:16 is fitted with bars, never
  cropped. Every tutorial can appear with every logo pair and wording. Opening lines and
  tick-and-cross wording have no use limit; untick one to stop using it. Each video also
  gets a slight zoom and shift, small speed changes, a gentle tint and a later song start.
- Speaking pairs: upload both `take-1-a.mp4` and `take-1-b.mp4` together.
- AI LARP: `larp-1.mp4` is the original; `larp-1-ai-1.mp4` is its AI version.
  Supply the AI footage yourself. Silver Goose assembles it; it does not generate it.
- Logo pairs: `openart-1.png` and `shorts-1.png`.
- Hook Story: use per-clip Settings for categories, joins, trims, backgrounds and framing.
- Removed assets go to `Silver Goose Library/trash`, accessible from Assets. Removing an output or
  asset never resets the successful-build history.

Silver Goose starts with **no footage, tutorials, speaking clips or finished videos**,
and fresh history. It includes music and its settings, wording for all formats, captions,
Content farm titles, comparison wording, money cards, logo pairs, the font and emoji
settings. Before building, add your own footage in Assets; each format says what it needs:

- Line, then card / Tick and cross: opening scenes (4.2 seconds or longer) and tutorials.
  Card only: short scenes (about 2 seconds) and tutorials.
- Content farm / MCP content farm: starting scenes, speaking A/B pairs and tutorials.
- Hook Story: hooks, tutorials and reactions.
- Bottle spin: starting scenes, tutorials and final talking clips.
- AI LARP: an original clip, its AI version and a tutorial.

Assign each tutorial to MCP, Chat or Director when you add it; the upload window offers
the content type selected in Builder.

## Development

Source ownership and safety: [docs/architecture.md](docs/architecture.md).
Validation evidence and repeatable checks: [docs/verification.md](docs/verification.md).
The private handoff excludes Git, test media, build history, caches and virtual environments.
`python3 scripts/package.py` builds `dist/Silver Goose.zip` with the starter library as
`starter-library/`. A Git checkout keeps its library in `library/` beside `source/`;
delivered copies use `~/Movies/Silver Goose Library` (`source/library_location.py`).
