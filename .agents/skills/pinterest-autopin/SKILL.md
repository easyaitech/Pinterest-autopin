---
name: pinterest-autopin
version: 1.3.0
description: Use this skill when the user wants to validate, test, or publish a single Pinterest Pin through the Pinterest AutoPin Playwright automation from the easyaitech/Pinterest-autopin GitHub repository, including preparing the request JSON, using a dedicated Chrome profile, running dry-run form fill, and doing a real publish only when explicitly requested.
---

# Pinterest AutoPin

Use this skill to create one Pinterest Pin with the automation in the `easyaitech/Pinterest-autopin` repo.

This is the Agent Skill interface. The CLI interface lives in `tools/pinterest_publish_pin.py`, and both interfaces share the same Playwright publisher in `publish_playwright.js`.

For Hermes Feishu workflow setup, run the guided onboarding command before `prepare` or `publish`:

```bash
python3 tools/feishu_pinterest_worker.py onboard --config .gstack/feishu-worker-config.json
```

Treat `readyForPrepare: true` as permission to run content generation. Treat `readyForPublish: true` as permission to schedule final publishing. If `nextActions` is not empty, guide the user through those actions first.
Use `--target prepare` before generation jobs and `--target publish` before final publish jobs. If official `lark-cli` is used, pass the same `--prepare-singleton-confirmed` or `--publish-singleton-confirmed` flag to the real Hermes worker command, unless the local config already sets the matching `*_lock_mode` to `hermes_singleton`.
If onboarding returns `skill_update`, ask the user whether to upgrade before running mutable workflow commands. Only run the returned upgrade command after explicit approval.

## Ground rules

- Never ask for or store Pinterest credentials. Use a dedicated Chrome profile and let the user sign in directly inside Chrome if needed.
- Never write Pinterest account names, real board names, cookies, Chrome profile contents, or real request JSON into this repository. Keep those in local ignored files or temp files only.
- Do not publish for real unless the user explicitly asks to publish, post, send, or run final mode.
- If the user asks to preview, test, verify, or prepare, use `test` mode.
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
  "altText": "Accessible image description"
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
- `chromeProfile`, only needed to override the default dedicated profile

`link`, when present, must be an absolute `http` or `https` URL.
`chromeProfile`, when present, must be an absolute path to a dedicated Chrome user data directory. If it is omitted, the CLI resolves a stable profile automatically.

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

If the profile has not been created yet, initialize and remember it:

```bash
python3 tools/pinterest_publish_pin.py --init-chrome-profile
```

5. For a preview that fills the Pinterest form but does not publish:

```bash
python3 tools/pinterest_publish_pin.py \
  --input /path/to/request.json \
  --mode test
```

6. For a real publish only after explicit user intent:

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
- `未能确认 Board 已选中`: the board name did not match Pinterest's UI; ask for the exact visible board name, or use a `Full Board Name|Short Alias` value.
- Upload or Publish button failures usually mean Pinterest changed its UI or the account session needs manual attention.

## Output to the user

Keep the response short:

- For validation: say whether the request is ready, plus blockers.
- For test mode: say the form was filled but not published.
- For final mode: say it was published and include the Pinterest URL when available.
