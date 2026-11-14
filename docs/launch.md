# Launch kit

Drafts and a checklist for announcing game-ui-proof. Links used throughout:

- Repo: https://github.com/thomas-ratz/game-ui-proof
- Live demo: https://thomas-ratz.github.io/game-ui-proof/
- Install: `/plugin marketplace add thomas-ratz/game-ui-proof` then `/plugin install game-ui-proof@game-ui-proof`
- Video: `docs/demo/demo.mp4` (38 s, 1600×900), `docs/demo/demo.gif`
- Social preview: `docs/demo/social.png` (1280×640); upload it in Settings > General > Social preview.

Rules change; re-read each venue's rules on the day you post. Notes here are as of 2026-11-14.

## Before any of it

- [x] Repo public, `main` pushed, description and topics set (`claude-code`, `claude-code-plugin`, `agent-skills`, `game-ui`, `godot`, `unity`, `unreal`, `gamedev`).
- [x] Settings > Pages > Source: GitHub Actions; the Pages workflow has run and the demo URL loads.
- [x] CI green on `main` (both Python versions); download the `example-sheets` artifact once and look at it.
- [x] Tag and release `v1.0.0` matching `.claude-plugin/plugin.json`; move the CHANGELOG entry out of "unreleased".
- [ ] Install from GitHub on a clean machine (or a fresh user profile) with the two commands above, and run one preview.
- [ ] The README's open TODO: a clip of a game running with applied values (optional, but it's the strongest proof).
- [x] Social preview image (Settings > General): upload `docs/demo/social.png`.

## awesome-claude-code

Submit through the repo's "Recommend a new resource" issue form, in the GitHub web UI. They don't take PRs for this, and they've said not to use the `gh` CLI. A bot validates the submission.

| Field | Draft |
|---|---|
| Name | game-ui-proof |
| Category | Agent Skills |
| Link | https://github.com/thomas-ratz/game-ui-proof |
| Author | Thomas Ratzicha, https://github.com/thomas-ratz |
| License | MIT |
| Description | Builds a tunable HTML preview of a game's UI over a screenshot at the game's resolution, saves the tuned values as a `values.json` spec, and writes it into Godot themes and scripts or Unity USS. |

If the form asks how to validate it: install with the two commands above, run `/game-ui-proof:ui-preview health bar` in any game project, or open the live demo.

## Show HN

HN's guidelines say not to post generated or AI-edited comments. The title is short enough to use as is. The comment below is a list of points: write it in your own words. Moderators have also complained about Show HNs that are only a generated repo with a generated README, so lead with what you built it for and what you checked yourself.

**Link:** the live demo (people can try it without installing anything). The repo goes in the comment.

**Title** (under 80 characters):

> Show HN: Game-ui-proof – tune game UI over a screenshot before your agent builds it

**Points for the first comment:**

- Why: agents are bad at visual tweaks ("2 px left", "less orange"), one round trip each, and game UI adds states, transitions, pixel fonts and engine theme files.
- What it is: a Claude Code skill. The agent writes an HTML page that draws the HUD/menu/effect over a real screenshot at the game's resolution, with sliders for every value. You tune, press Save, and get `values.json`.
- What happens to the spec: scripts write it into a Godot theme `.tres` and C#/GDScript export defaults, or Unity USS (dry run first). Unreal DataTables are read only.
- The demo: four previews of a made-up platformer. No server on Pages, so Save copies JSON there.
- Where it came from: your own game, and what changed in your workflow.
- Honest limits: Claude Code only (needs a shell and a browser), no Unreal writer, the preview approximates the engine's text rendering.
- Security, if asked: the local server binds to 127.0.0.1, checks Host and Origin, and only writes `values.json` / `values.draft.json` in preview folders. `test_serve.py` checks these rules.
- How it was built: say plainly how much Claude wrote.

Post on a weekday, US morning, and stay around for a few hours to answer. Don't ask anyone for upvotes.

## Reddit: r/ClaudeAI and r/aigamedev

Check each sidebar for flair and self-promotion rules first. r/ClaudeAI has used a "Built with Claude" flair. Attach the GIF or the MP4; video posts do better than links.

**Title:** I made a Claude Code plugin that lets you tune your game's UI with sliders before Claude builds it

**Body:**

> Up front: I built this with Claude Code, and it's a plugin for Claude Code. Most of the code was written by Claude; I designed the workflow, tested it on my own Godot game, and reviewed the security-sensitive parts. *(Adjust to how it was actually made.)*
>
> The problem: asking an agent for "a bit smaller, a bit less orange" is one round trip per tweak, and game UI has states, animations and engine theme files on top.
>
> What it does: Claude draws the HUD, menu or effect as an HTML page over a real screenshot of your game, at the game's resolution, with a panel of sliders and colour pickers. You tune it and press Save. The `values.json` it writes is the spec. Scripts apply it to a Godot theme and export defaults, or to Unity USS. It reads Unreal DataTables.
>
> Try it in the browser (no install): https://thomas-ratz.github.io/game-ui-proof/
> Repo (MIT): https://github.com/thomas-ratz/game-ui-proof
>
> Feedback welcome, especially from Unity and Unreal users. I've used it most on Godot.

For r/aigamedev, start with the game angle instead: drop "a Claude Code plugin" from the title ("Tune your game's HUD with sliders before your AI agent builds it") and keep the disclosure line first.

## Checklist by venue

| Venue | License | Repo age / stars | Demo link | Video | Other |
|---|---|---|---|---|---|
| awesome-claude-code | Must be detectable by GitHub (MIT `LICENSE` at root ✓) | The audit noted ≥ 14 days old or 100★; one recent report says ≥ 1 week. Check the form | Optional; repo link required | No | Web UI issue form only, no PR, no `gh` CLI |
| Show HN | Not required; open source helps | None | **Yes**: something people can try without signing up | Optional (link from the comment) | No AI-written or AI-edited comments; be there to answer |
| r/ClaudeAI | Not required | None | Yes | GIF/MP4 in the post | Flair; AI disclosure first; read the self-promotion rule |
| r/aigamedev | Not required | None | Yes | GIF/MP4 in the post | Game angle first; disclosure |
| awesome-gamedev-agent-skills | Yes | Check their rubric | Helps | Helps | PR against their rubric |
| X / Bluesky | — | — | Yes | The 38 s MP4 (fits both) | Alt text on the video |

Skip r/godot and r/gamedev for the launch. The audit found those communities openly hostile to AI tools. If someone else posts it there, answer questions; don't push.
