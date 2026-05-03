# Pinterest AutoPin

Single-pin Pinterest publishing repo with two official interfaces:

1. CLI mode for humans, scripts, cron jobs, and generic automation.
2. Agent Skill mode for Hermes-compatible agents.

## What is here

- `publish_playwright.js`
  The shared Playwright publisher that opens a dedicated Chrome profile or connects to a legacy CDP session.
- `tools/pinterest_publish_pin.py`
  The CLI interface. It validates input, locates the Chrome profile, runs the publisher, and emits JSON.
- `.agents/skills/pinterest-autopin/SKILL.md`
  The Hermes agent Skill interface. It tells an agent how to validate, test, and publish one Pin through the CLI interface.

```text
publish_playwright.js
  -> tools/pinterest_publish_pin.py
     -> CLI users
     -> .agents/skills/pinterest-autopin
        -> Hermes agent
```

## Prerequisites

- macOS
- Node.js
- Google Chrome
- A dedicated Chrome profile directory for Pinterest AutoPin. The CLI can create and remember one for you.
- `npm install`

## Chrome Profile

Pinterest AutoPin no longer requires Chrome to be pre-launched with CDP on port `9222`.
By default, the CLI uses this stable dedicated profile:

```bash
~/.pinterest-autopin/chrome-profile
```

To see the exact path on the current machine:

```bash
npm run pin:profile
```

To create the profile directory and save it in `~/.pinterest-autopin/config.json`:

```bash
npm run pin:init-profile
```

For a custom dedicated profile, initialize it once:

```bash
python3 tools/pinterest_publish_pin.py \
  --chrome-profile "/absolute/path/to/chrome-profile" \
  --init-chrome-profile
```

After that, normal `test` and `final` commands can omit `--chrome-profile`.

Profile resolution order:

1. `--chrome-profile`
2. JSON field `chromeProfile`, `chrome_profile`, or `chrome-profile`
3. Environment variable `PINTEREST_AUTOPIN_CHROME_PROFILE`
4. `~/.pinterest-autopin/config.json`
5. Default `~/.pinterest-autopin/chrome-profile`

First run `test` mode, sign in to Pinterest if Chrome asks, then re-run the command:

```bash
npm run pin:test -- --input examples/request.json
```

For JSON-based agent calls, `chromeProfile` is optional. Include it only when you want to override the default:

```json
{
  "chromeProfile": "/absolute/path/to/chrome-profile"
}
```

An already running Chrome CDP session on port `9222` is still supported as a legacy fallback with `--no-default-chrome-profile`, but it is no longer the recommended setup.

## Install From GitHub

For Hermes, OpenClaw, or any agent that can install project skills from a GitHub repository, use the public repo:

```bash
git clone https://github.com/easyaitech/Pinterest-autopin.git
cd Pinterest-autopin
npm install
```

The Skill is stored at:

```text
.agents/skills/pinterest-autopin
```

Use it from an agent as:

```text
$pinterest-autopin
```

If your agent supports installing a Skill by repository URL, point it at:

```text
https://github.com/easyaitech/Pinterest-autopin
```

If your agent expects a Skill subdirectory, point it at:

```text
.agents/skills/pinterest-autopin
```

The Skill depends on the repository CLI, so keep the cloned repo available on the machine that will publish Pins.

## Local Install

```bash
git clone https://github.com/easyaitech/Pinterest-autopin.git
cd Pinterest-autopin
npm install
```

## Agent-facing command

Validate only:

```bash
python3 tools/pinterest_publish_pin.py --input examples/request.json --mode validate
```

or:

```bash
npm run pin:validate -- --input examples/request.json
```

Fill the form without clicking Publish:

```bash
python3 tools/pinterest_publish_pin.py \
  --input examples/request.json \
  --mode test
```

or:

```bash
npm run pin:test -- --input examples/request.json
```

Publish for real:

```bash
python3 tools/pinterest_publish_pin.py \
  --input examples/request.json \
  --mode final
```

or:

```bash
npm run pin:publish -- --input examples/request.json
```

## Input shape

```json
{
  "image": "/absolute/path/to/image.jpg",
  "title": "Your pin title",
  "board": "Board Name",
  "link": "https://example.com",
  "description": "Pin description",
  "altText": "Accessible image description"
}
```

Optional custom profile override:

```json
{
  "chromeProfile": "/absolute/path/to/chrome-profile"
}
```

## Output shape

The Python tool prints JSON to stdout. On success, it includes:

- `ok`
- `mode`
- `pinUrl`
- `result`
- `stdoutTail`
- `stderrTail`

## Notes

- `--mode validate` never opens Chrome or touches Pinterest.
- `--mode test` opens the pin builder and fills the form, but does not publish.
- `board` is required in `test` and `final` mode. There is no silent default board.
- `image` must be an absolute path. `link`, when present, must be an absolute `http` or `https` URL.
- `chromeProfile` is optional. If omitted, the CLI resolves a stable profile automatically.
- If the resolved profile directory does not exist, it will be created.
- `publish_playwright.js` now supports:
  - `--input <json-file>`
  - `--data <inline-json-or-file>`
  - `--result-json <json-file>`
  - `--chrome-profile <profile-dir>`

## Example request

See `examples/request.json`.

## Hermes Skill

The project-level Skill lives at:

```text
.agents/skills/pinterest-autopin/SKILL.md
```

Invoke it as `$pinterest-autopin` in a Hermes-compatible agent. The Skill intentionally wraps `tools/pinterest_publish_pin.py` instead of duplicating browser automation logic.
