# Pinterest AutoPin

Single-pin Pinterest publishing repo with two official interfaces:

1. CLI mode for humans, scripts, cron jobs, and generic automation.
2. Agent Skill mode for Hermes-compatible agents.

## What is here

- `publish_playwright.js`
  The shared Playwright publisher that talks to an already logged-in Chrome session.
- `tools/pinterest_publish_pin.py`
  The CLI interface. It validates input, runs the publisher, and emits JSON.
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
- A dedicated Chrome profile directory for Pinterest AutoPin
- `npm install`

## Chrome Profile

Pinterest AutoPin no longer requires Chrome to be pre-launched with CDP on port `9222`.
Create a dedicated Chrome profile directory and pass it to the CLI or agent:

```bash
mkdir -p "$HOME/.pinterest-autopin/chrome-profile"
```

First run `test` mode with that profile, sign in to Pinterest if Chrome asks, then re-run the command:

```bash
npm run pin:test -- \
  --input examples/request.json \
  --chrome-profile "$HOME/.pinterest-autopin/chrome-profile"
```

For JSON-based agent calls, include:

```json
{
  "chromeProfile": "/absolute/path/to/chrome-profile"
}
```

An already running Chrome CDP session on port `9222` is still supported as a legacy fallback, but it is no longer the recommended setup.

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
  --mode test \
  --chrome-profile "$HOME/.pinterest-autopin/chrome-profile"
```

or:

```bash
npm run pin:test -- --input examples/request.json --chrome-profile "$HOME/.pinterest-autopin/chrome-profile"
```

Publish for real:

```bash
python3 tools/pinterest_publish_pin.py \
  --input examples/request.json \
  --mode final \
  --chrome-profile "$HOME/.pinterest-autopin/chrome-profile"
```

or:

```bash
npm run pin:publish -- --input examples/request.json --chrome-profile "$HOME/.pinterest-autopin/chrome-profile"
```

## Input shape

```json
{
  "image": "/absolute/path/to/image.jpg",
  "title": "Your pin title",
  "board": "Board Name",
  "link": "https://example.com",
  "description": "Pin description",
  "altText": "Accessible image description",
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
- `chromeProfile` is recommended for `test` and `final` mode. If it does not exist, it will be created.
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
