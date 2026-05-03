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
- Google Chrome already logged into Pinterest
- Chrome running with CDP on port `9222`
- `npm install`

## Install

```bash
cd /Users/johnz/code/Pinterest-autopin
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
python3 tools/pinterest_publish_pin.py --input examples/request.json --mode test
```

or:

```bash
npm run pin:test -- --input examples/request.json
```

Publish for real:

```bash
python3 tools/pinterest_publish_pin.py --input examples/request.json --mode final
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
- `publish_playwright.js` now supports:
  - `--input <json-file>`
  - `--data <inline-json-or-file>`
  - `--result-json <json-file>`

## Example request

See `examples/request.json`.

## Hermes Skill

The project-level Skill lives at:

```text
.agents/skills/pinterest-autopin/SKILL.md
```

Invoke it as `$pinterest-autopin` in a Hermes-compatible agent. The Skill intentionally wraps `tools/pinterest_publish_pin.py` instead of duplicating browser automation logic.
