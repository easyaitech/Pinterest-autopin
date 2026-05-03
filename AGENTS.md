# AGENTS.md

## Communication

- Always communicate in Chinese unless the user explicitly asks for another language.

## Skill

- The project Skill lives at `.agents/skills/pinterest-autopin`.
- Use `$pinterest-autopin` for Pinterest Pin validation, dry-run form filling, and final publishing.
- Do not publish for real unless the user explicitly asks for final publish mode.

## Local Requirements

- Run `npm install` before using test or final mode.
- Use the resolved dedicated Chrome profile for test or final mode. Check it with `python3 tools/pinterest_publish_pin.py --print-chrome-profile`.
- Initialize the profile with `python3 tools/pinterest_publish_pin.py --init-chrome-profile` if it does not exist yet.
- If the profile is not logged into Pinterest yet, let the user sign in directly inside Chrome.
- Use `python3 tools/pinterest_publish_pin.py` as the stable CLI entrypoint.
