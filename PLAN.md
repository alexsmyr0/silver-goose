# Silver Goose: agreed scope

Status: implemented locally, 30 September 2026. Supersedes the initial analysis/proposal.

## Included

- Separate sibling repository cloned from `alexsmyr0/silver-goose`.
- Local Mac application, source folder and double-click Terminal launcher.
- Builder and Assets tabs, compact build settings, output previews and folder access.
- OpenArt content selector: MCP, Chat and Director.
- Eight builders: Line, then card; Card only; Tick and cross; Content farm;
  MCP content farm; Hook Story; Bottle spin; AI LARP.
- Shared asset library, tutorial eligibility, speaking and AI clip pairs,
  font/logos/music, wording, automatic captions, media normalization and reuse limits.
  (Per-tutorial logo/wording pairing was included here; superseded 15 November 2026 —
  see the change below.)
- Shared output folders by campaign and format. No account folders.
- Explicit batches, availability, progress/logs, successful output counts, recoverable errors.
- Copy local production settings and available assets; fresh independent build history.
- First-run installation of missing dependencies, with unavoidable Mac approvals in Terminal.
- Private folder/ZIP handoff for each friend (the first was John), excluding the owner's
  provider keys and history.

## Excluded by agreement

Earnings, Instagram metrics, providers/MediaMaxxing/Buffer, account connections,
posting/submission, schedules/queues, reposting, other campaigns, login, cloud hosting,
managed installer and background services. The earlier General/Earnings proposals are
superseded by the agreed Builder + Assets scope. No new Cutter or AI footage generator.

## Change, 15 November 2026: silent formats match Golden Goose's builder

Asked by the owner: Line, then card, Card only and Tick and cross now use Golden Goose's
current builder (commit `3aec2164`). That brings the four micro changes, the exact
visible-cover plan and history-aware tutorial/logo spreading. It supersedes per-tutorial
pairing and the 25-use limit on opening lines and comparison wording, as Golden Goose did
in October. Golden Goose's tutorial caption system was deliberately not imported: tutorials
are assumed to have captions burned in. Accounts, footage locks and campaigns stay excluded.

## Practical limits

Each recipient needs macOS 26 or newer for Apple's caption engine. Clean-Mac system installation
requires Apple/Homebrew interaction; it cannot be entirely silent. Missing footage is
reported in Assets/Builder rather than fabricated. The copied library lacks short Card
scenes, Hook Story pools and AI LARP source pairs/tutorials. Each recipient uploads these.

[User guide](README.md) · [Architecture](docs/architecture.md) · [Verification](docs/verification.md)
