# AGENTS.md

## Communication

- Always communicate in Chinese unless the user explicitly asks for another language.

## Skill

- The project Skill lives at `.agents/skills/pinterest-autopin`.
- Use `$pinterest-autopin` for Pinterest Pin validation, dry-run form filling, and final publishing.
- Do not publish for real unless the user explicitly asks for final publish mode.

## Local Requirements

- Run `npm install` before using test or final mode.
- Chrome must already be logged into Pinterest and running with CDP on port `9222`.
- Use `python3 tools/pinterest_publish_pin.py` as the stable CLI entrypoint.
