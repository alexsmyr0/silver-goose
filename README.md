# Silver Goose

A local Mac video builder for OpenArt. **Builder** and **Assets** only.
Choose **MCP**, **Chat** or **Director**, enter quantities, and build. Post the finished
videos yourself. No social accounts, API keys, posting service or earnings screen.

## Start

1. Keep the entire **Silver Goose** folder together on your Mac.
2. Double-click **Start Silver Goose.command**. Leave its Terminal window open.
3. On first launch, approve any missing Apple developer tools or Homebrew requirements.
   If Apple's installer opens, finish it and run the launcher again.

The launcher sets up a private Python environment, installs missing packages, compiles
the video helpers and prepares Apple's English speech model. First setup needs internet.
It may ask for your Mac password during system-tool installation. Later launches reuse
what is installed and open the local panel. No paid service is required.

**Requires macOS 26 or newer** for automatic captions. Tested on Apple Silicon.
If macOS blocks an internet-downloaded launcher, use Finder's **Open** command or allow
it in **System Settings → Privacy & Security**, then open it again.

For a Desktop shortcut, right-click the launcher in Finder, choose **Make Alias**, and
move the alias to the Desktop. If you copy the actual launcher instead, it asks you to
select the Silver Goose folder when it cannot locate it.

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
library/videos/openart/line/
library/videos/openart/card/
library/videos/openart/compare/
library/videos/openart/farm/
library/videos/openart/mcp_farm/
library/videos/openart/reaction/
library/videos/openart/tutorial_story/
library/videos/openart/ai_larp/
```

## Assets

Add prepared clips in Assets; preview or remove files, edit wording and music settings,
assign tutorials to a content type, and choose tutorial folders and logo/comparison
pairings. Build settings control reuse quantities. Assets → Common holds font, logos,
base music, emoji, post captions, and caption vocabulary/corrections.

- Speaking pairs: upload both `take-1-a.mp4` and `take-1-b.mp4` together.
- AI LARP: `larp-1.mp4` is the original; `larp-1-ai-1.mp4` is its AI version.
  Supply the AI footage yourself. Silver Goose assembles it; it does not generate it.
- Logo pairs: `openart-1.png` and `shorts-1.png`.
- Hook Story: use per-clip Settings for categories, joins, trims, backgrounds and framing.
- Removed assets go to `library/trash`, accessible from Assets. Removing an output or
  asset never resets the successful-build history.

This handoff includes the available local footage and settings with **fresh history**.
The source library had no Card-only short clips, Hook Story ingredients, or AI LARP
source pairs/tutorials. Those formats need uploads before use. Regular Content farm
has Chat and Director tutorials; MCP has its separate MCP content farm.

Keep `library` with `source`. Back up the whole folder to preserve assets, settings,
finished videos and reuse history. Never share only `source` if you want the included
footage and settings. The launcher will not download missing footage.

## Development

Source ownership and safety: [docs/architecture.md](docs/architecture.md).
Validation evidence and repeatable checks: [docs/verification.md](docs/verification.md).
The private handoff excludes Git, test media, build history, caches and virtual environments.
