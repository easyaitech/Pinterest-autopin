---
name: pinterest-autopin
version: 1.3.6
description: Use this skill when the user wants to validate Pinterest login, set up the Feishu/Hermes Pinterest workflow, or validate, test, or publish a single Pinterest Pin through the Pinterest AutoPin Playwright automation from the easyaitech/Pinterest-autopin GitHub repository.
---

# Pinterest AutoPin

Use this skill to operate the Pinterest AutoPin automation in the `easyaitech/Pinterest-autopin` repo, including Feishu/Hermes onboarding and one-off Pin validation or publishing.

This is the Agent Skill interface. The CLI interface lives in `tools/pinterest_publish_pin.py`, and both interfaces share the same Playwright publisher in `publish_playwright.js`.

For Hermes Feishu workflow setup, run the guided onboarding command before `prepare` or `publish`:

```bash
python3 tools/feishu_pinterest_worker.py onboard --config .gstack/feishu-worker-config.json
```

When the user provides a Feishu Base/wiki shared URL for setup, run schema setup immediately instead of asking them to create fields manually:

```bash
python3 tools/feishu_pinterest_worker.py setup-base \
  --config .gstack/feishu-worker-config.json \
  --base-url "<Feishu Base or Wiki shared URL>"
```

After `setup-base`, summarize the printed `usage` steps for the user.

Treat `readyForPrepare: true` as permission to run content generation. Treat `readyForPublish: true` as permission to schedule final publishing. If `nextActions` is not empty, guide the user through those actions first.
Use `--target prepare` before generation jobs and `--target publish` before final publish jobs. If official `lark-cli` is used, pass the same `--prepare-singleton-confirmed` or `--publish-singleton-confirmed` flag to the real Hermes worker command, unless the local config already sets the matching `*_lock_mode` to `hermes_singleton`.
If onboarding returns `skill_update`, ask the user whether to upgrade before running mutable workflow commands. Only run the returned upgrade command after explicit approval.

## Ground rules

- Never ask for or store Pinterest credentials. Use a dedicated Chrome profile and let the user sign in directly inside Chrome if needed.
- Never write Pinterest account names, real board names, cookies, Chrome profile contents, or real request JSON into this repository. Keep those in local ignored files or temp files only.
- Do not publish for real unless the user explicitly asks to publish, post, send, or run final mode.
- If the user asks to preview, test, or verify one explicit Pin, use `test` mode.
- If the user asks for Feishu/Hermes `prepare` or workflow setup, run onboarding first and follow its `nextActions`; do not collect direct Pin fields unless they explicitly request one-off Pin test/final mode.
- If the user gives a Feishu Base/wiki shared URL, run `setup-base` to create/complete all required tables and fields, then explain how to use the table.
- If required fields are missing for `test` or `final`, ask for the missing values instead of inventing them.
- Always use the CLI wrapper and its JSON output; do not call the Playwright script directly unless debugging the wrapper.

## Locate the tool

Use the current repo root if it contains `tools/pinterest_publish_pin.py`.

```bash
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
test -f "$REPO_ROOT/tools/pinterest_publish_pin.py" && cd "$REPO_ROOT"
```

If the tool is not present, clone the public repository first:

```bash
git clone https://github.com/easyaitech/Pinterest-autopin.git
cd Pinterest-autopin
npm install
```

The stable entrypoint is:

```bash
python3 tools/pinterest_publish_pin.py
```

## Input

Prepare a JSON object with this shape:

```json
{
  "image": "/absolute/path/to/image.jpg",
  "title": "Pin title",
  "board": "Pinterest board name",
  "link": "https://example.com",
  "description": "Pin description",
  "altText": "Accessible image description",
  "creationUrl": "https://jp.pinterest.com/pin-creation-tool/"
}
```

Required:

- `image`: absolute path to an existing image file.
- `title`: Pin title.
- `board`: required for `test` and `final`; `validate` allows it to be empty but should warn.

Optional:

- `link`
- `description`
- `altText`
- `creationUrl`, only needed to target a localized creation surface such as `https://jp.pinterest.com/pin-creation-tool/`
- `chromeProfile`, only needed to override the default dedicated profile

`link`, when present, must be an absolute `http` or `https` URL.
`creationUrl`, when present, must be an absolute Pinterest creation URL.
`chromeProfile`, when present, must be an absolute path to a dedicated Chrome user data directory. If it is omitted, the CLI resolves a stable profile automatically.

The dedicated Chrome profile display name is `Pinterest AutoPin` after initialization, so the user can tell it apart from personal Chrome profiles.

Default profile resolution order:

1. CLI `--chrome-profile`
2. JSON `chromeProfile`, `chrome_profile`, or `chrome-profile`
3. `PINTEREST_AUTOPIN_CHROME_PROFILE`
4. `~/.pinterest-autopin/config.json`
5. `~/.pinterest-autopin/chrome-profile`

## Workflow

1. Ensure dependencies are present:

```bash
npm install
```

2. Write or reuse a request JSON file. `examples/request.json` is only a shape example; replace it with real values in an ignored local file or use a temp file.

3. Validate without opening Chrome:

```bash
python3 tools/pinterest_publish_pin.py --input /path/to/request.json --mode validate
```

4. If validation reports missing dependencies, fix them if safe. To see which dedicated Chrome profile will be used:

```bash
python3 tools/pinterest_publish_pin.py --print-chrome-profile
```

If the profile has not been created yet, initialize it, apply the `Pinterest AutoPin` display name, and remember it:

```bash
python3 tools/pinterest_publish_pin.py --init-chrome-profile
```

For an existing dedicated profile, rerun the init command with that Chrome window closed to refresh the display name without changing the profile directory.

5. Before using `test` or `final`, confirm the account session with:

```bash
python3 tools/pinterest_publish_pin.py --mode check-login
```

For the localized storyboard creation UI, pass the creation URL in JSON or on the CLI:

```bash
python3 tools/pinterest_publish_pin.py \
  --mode check-login \
  --creation-url https://jp.pinterest.com/pin-creation-tool/
```

If the dedicated Chrome profile is already open, do not launch the same profile again. First verify that the open Chrome was started with local CDP on `127.0.0.1:9222`, then run check-login through the existing browser session:

```bash
python3 tools/pinterest_publish_pin.py \
  --mode check-login \
  --no-default-chrome-profile
```

Use the same CDP strategy for later Feishu publish work by passing `--use-chrome-cdp` to `tools/feishu_pinterest_worker.py onboard` and `publish`. If CDP is not reachable, ask the user to either close the dedicated Chrome window before running profile mode, or reopen it with `--remote-debugging-port=9222`.

6. If `check-login` returns `ok: true` and the user is setting up the Feishu/Hermes workflow, do not ask for single-Pin image/title/board fields. If they gave a Feishu Base/wiki shared URL, run `setup-base`; otherwise move to Feishu onboarding:

```bash
python3 tools/feishu_pinterest_worker.py onboard \
  --config .gstack/feishu-worker-config.json \
  --target publish
```

If the Pinterest dedicated Chrome is already open and CDP was confirmed on `127.0.0.1:9222`, include the CDP flag in both onboarding and final publishing:

```bash
python3 tools/feishu_pinterest_worker.py onboard \
  --config .gstack/feishu-worker-config.json \
  --target publish \
  --use-chrome-cdp

python3 tools/feishu_pinterest_worker.py publish \
  --config .gstack/feishu-worker-config.json \
  --use-chrome-cdp
```

If onboarding reports `feishu_cli`, guide the user to install `lark-cli`, ensure it is on `PATH`, and authenticate with the required scopes:

```bash
lark-cli auth login --scope "base:app:read base:table:read base:field:read base:record:read base:record:create base:record:update docs:document.media:upload drive:file:download wiki:node:read"
```

The local Feishu config should stay in an ignored file such as `.gstack/feishu-worker-config.json` and use the official CLI shape:

```json
{
  "feishu_cli": "lark-cli",
  "feishu_cli_flavor": "lark",
  "prepare_lock_mode": "hermes_singleton",
  "publish_lock_mode": "hermes_singleton"
}
```

Only continue to `test` or `final` with direct Pin fields when the user explicitly asks for one-off Pin validation, dry-run filling, or final publishing.

Worker-side `prepare` now uses a deterministic quality engine before writing draft fields. It reads existing product fields, extracts lightweight image signals from the downloaded image path, chooses a Pinterest search intent, writes Etsy-conversion copy, and runs a quality gate. It does not add new Feishu fields. Hermes may still perform model-based image understanding or copywriting outside the worker; when it does, product fields are the source of truth and image observations should only add visible details.

7. For a preview that fills one explicit Pinterest form but does not publish:

```bash
python3 tools/pinterest_publish_pin.py \
  --input /path/to/request.json \
  --mode test
```

8. For a real one-off publish only after explicit user intent:

```bash
python3 tools/pinterest_publish_pin.py \
  --input /path/to/request.json \
  --mode final
```

## Interpret results

The wrapper prints JSON. Treat `ok: true` as success.

Important fields:

- `errors`: blocker list to report and resolve.
- `warnings`: non-blocking concerns.
- `checks.chromeCdp.reachable`: optional legacy fallback status.
- `pinUrl`: final Pinterest URL after `final` mode.
- `stdoutTail` and `stderrTail`: use only for debugging; prefer structured fields.

For `final` mode, report the `pinUrl` if present. If `ok` is true but `pinUrl` is empty, say the publish completed but the URL was not captured, then use the browser state or Pinterest account activity if the user wants confirmation.

## Common failures

- `image does not exist`: ask for or locate the correct absolute image path.
- `board is required`: ask for the exact Pinterest board name.
- `playwright dependency is not installed`: run `npm install` in the repo.
- `chromeProfile is required`: run `--print-chrome-profile` or `--init-chrome-profile`; this should only happen when defaults were explicitly disabled.
- `SingletonLock` or `ProcessSingleton`: the dedicated Chrome profile is already open. Do not start a second profile session. Use CDP mode with `--no-default-chrome-profile` if `127.0.0.1:9222` is reachable, otherwise close or relaunch the dedicated Chrome window with CDP enabled.
- `chromeCdp.reachable` is false: CDP mode cannot attach to the open browser yet; check that Chrome was launched with `--remote-debugging-port=9222`.
- `Pinterest login required at https://www.pinterest.com/`: the dedicated profile is not logged in. Let the user sign in directly inside the dedicated Chrome window, then re-run `check-login`.
- `未能确认 Board 已选中`: the board name did not match Pinterest's UI; ask for the exact visible board name, or use a `Full Board Name|Short Alias` value.
- Upload or Publish button failures usually mean Pinterest changed its UI or the account session needs manual attention.

## Output to the user

Keep the response short:

- For `check-login` success: say Pinterest is logged in, name whether profile or CDP was used, and guide the user to Feishu/Hermes onboarding with `tools/feishu_pinterest_worker.py onboard`. Do not ask for image path, Pin title, Board, link, description, or alt text unless the user explicitly requested one-off Pin test/final mode.
- For Feishu onboarding: summarize `nextActions`; when `feishu_cli` or `feishu_auth` is pending, provide the `lark-cli` install/auth direction, required scopes, and local config path.
- For validation: say whether the request is ready, plus blockers.
- For test mode: say the form was filled but not published.
- For final mode: say it was published and include the Pinterest URL when available.
