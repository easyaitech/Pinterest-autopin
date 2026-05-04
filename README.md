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

## Public Repo Safety

This repository is public. Never commit Pinterest or Feishu account-specific data.

Keep these local only:

- Pinterest login email, account name, cookies, session state, Chrome profile contents, real board names, and real Pin request JSON.
- Feishu tenant/app/base/table/field identifiers, app tokens, access tokens, CLI auth state, attachment tokens, exports, and screenshots from logged-in Feishu pages.
- Any Hermes secret values or local environment files used to connect the worker to live services.

Recommended local-only locations:

- `~/.pinterest-autopin/config.json` and `~/.pinterest-autopin/chrome-profile` for the Pinterest browser profile.
- `.gstack/feishu-worker-config.json`, `.secrets/feishu-worker-config.json`, or `worker-config.local.json` for real Feishu worker config.
- `.env` or the Hermes secret store for Feishu access tokens and other credentials.

The committed files under `examples/` are shape examples only. Replace placeholders in a local ignored file before running against real Pinterest or Feishu.

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
That flag disables saved/default profile lookup; explicit CLI, JSON, or environment profile values still win.

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

Check the Pinterest login state without uploading an image or changing a Pin:

```bash
python3 tools/pinterest_publish_pin.py --mode check-login
```

or:

```bash
npm run pin:check-login
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
- `--mode check-login` opens the Pin builder only to confirm the profile is logged in. It does not upload, fill, or publish.
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

## Feishu Workflow Worker

The multi-step Feishu workflow uses a separate worker CLI:

```bash
python3 tools/feishu_pinterest_worker.py onboard --config .gstack/feishu-worker-config.json
python3 tools/feishu_pinterest_worker.py doctor --config .gstack/feishu-worker-config.json
python3 tools/feishu_pinterest_worker.py prepare --config .gstack/feishu-worker-config.json --limit 10
python3 tools/feishu_pinterest_worker.py publish --config .gstack/feishu-worker-config.json --limit 1
```

Run `onboard` first in Hermes. It returns a structured checklist that tells the agent and user exactly which setup step is still missing: dependency install, Hermes run identity, Feishu CLI auth, local Feishu config, Feishu table doctor, Pinterest Chrome profile, Pinterest login, and publish singleton protection.
It also checks the public Pinterest AutoPin Skill version. If a newer version is available, onboarding returns a non-blocking `skill_update` action so the agent can ask the user whether to upgrade before continuing.

Use it as a gate before each phase:

```bash
python3 tools/feishu_pinterest_worker.py onboard \
  --config .gstack/feishu-worker-config.json \
  --target prepare

python3 tools/feishu_pinterest_worker.py onboard \
  --config .gstack/feishu-worker-config.json \
  --target publish
```

For fully offline setup checks, skip the public version lookup:

```bash
python3 tools/feishu_pinterest_worker.py onboard \
  --config .gstack/feishu-worker-config.json \
  --skip-skill-update-check
```

For local setup checks:

```bash
python3 tools/feishu_pinterest_worker.py onboard --config .gstack/feishu-worker-config.json --local-dev
```

If official `lark-cli` is used for Feishu, prepare and final publish need Hermes to enforce one run at a time because `lark-cli` does not expose an atomic compare-update operation. After configuring the Hermes jobs with max concurrency 1, either set the local config modes:

```json
{
  "prepare_lock_mode": "hermes_singleton",
  "publish_lock_mode": "hermes_singleton"
}
```

or pass the singleton confirmation flags on both onboarding and the real worker commands:

```bash
python3 tools/feishu_pinterest_worker.py onboard \
  --config .gstack/feishu-worker-config.json \
  --prepare-singleton-confirmed \
  --publish-singleton-confirmed

python3 tools/feishu_pinterest_worker.py prepare \
  --config .gstack/feishu-worker-config.json \
  --prepare-singleton-confirmed

python3 tools/feishu_pinterest_worker.py publish \
  --config .gstack/feishu-worker-config.json \
  --publish-singleton-confirmed
```

Create the real config by copying `examples/worker-config.example.json` into an ignored local path such as `.gstack/feishu-worker-config.json`. Do not edit the committed example with real Feishu values.

Hermes runs should provide run identity through environment variables such as:

```text
HERMES_RUN_ID
HERMES_AGENT_ID
HERMES_JOB_ID
```

Local development must opt in explicitly:

```bash
python3 tools/feishu_pinterest_worker.py doctor --config .gstack/feishu-worker-config.json --local-dev
```

Feishu access is through a CLI boundary only. The worker expects a configurable Feishu CLI binary and JSON output; tests mock this boundary and never call live Feishu, live AI, or live Pinterest. Do not deploy an OpenAI API key for this worker. Model calls belong to the Hermes agent runtime, not the Feishu/Pinterest worker process.

Official `lark-cli` is supported with:

```json
{
  "feishu_cli": "lark-cli",
  "feishu_cli_flavor": "lark",
  "prepare_lock_mode": "hermes_singleton",
  "publish_lock_mode": "hermes_singleton"
}
```

Legacy wrappers can still use `feishu_cli_flavor: "bitable"` if they expose the old command shape:

- paginated `bitable records list` with `has_more` and `page_token` JSON fields
- atomic `bitable records compare-update` for runtime locks
- `bitable attachments download` and `bitable attachments upload`

Official `lark-cli` uses:

- `base +record-list`
- `base +record-upsert`
- `base +record-upload-attachment`
- `api GET /open-apis/drive/v1/medias/{file_token}/download`

`prepare` and `publish` require either an atomic Feishu compare-update lock or explicit `hermes_singleton` lock modes. If the CLI does not expose atomic compare-update and singleton mode is not configured, the worker refuses to mutate rows instead of using a non-atomic fallback.
For official `lark-cli`, use `hermes_singleton` only after the Hermes schedules are configured with max concurrency 1.

`prepare` claims ready rows, downloads `source_image`, writes draft fields, uploads `processed_image`, and moves rows to human review. `publish` only uses the approved `final_image` attachment when it is present, then downloads it into the run temp directory before calling the Pinterest publisher.

Publish safety order:

```text
Hermes run identity
  -> atomic Feishu runtime_locks[pinterest_profile_publish]
  -> Pinterest check-login
  -> scan approved due Pins across pages
  -> claim one Pin and increment publish_attempts
  -> download final_image attachment
  -> final publish
  -> Feishu writeback
```
