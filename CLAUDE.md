# Project Context: Home Assistant - MySQL Query Custom Component

## Doel van dit project
De custom component `mysql_query` controleren, opschonen en moderniseren volgens de nieuwste Home Assistant (HA) developer richtlijnen en Python 3.12+ standaarden.

## HA Development & Code Conventies
- **Async First:** Vervang alle blocking I/O (zoals directe database query-calls) door async executie via `hass.async_add_executor_job` of een async database-driver (bijv. `aiomysql`).
- **Config Flow:** Als de integratie nog oude `configuration.yaml` opzet gebruikt, bereid de stap voor naar UI-gebaseerde Config Flow (`config_flow.py`).
- **Typing & Linting:** Voeg strikte Python Type Hints toe aan alle functies en methoden.
- **Manifest:** Zorg dat `manifest.json` voldoet aan de nieuwste eisen (inclusief `codeowners`, `config_flow: true`, `version`, en correcte `requirements`).
- **Relative Paths & File Handling:** Hardcode NOOIT absolute padnamen (zoals `/Users/username/...` of `C:\Users\...`) in de code, tests of documentatie. Gebruik uitsluitend relatieve paden of de dynamische `hass.config.path()` helper functies van Home Assistant om bestanden te lokaliseren.
- **Privacy & Anoniem:** Gebruik in testvoorbeelden en mocks alleen dummy credentials (host: `localhost`, user: `test_user`, db: `test_db`).

## Test Framework
- Gebruik `pytest` in combinatie met `pytest-homeassistant-custom-component`.
- Maak mocks voor databaseverbindingen (`unittest.mock` / `AsyncMock`) zodat tests draaien zonder dat er een echte MySQL/MariaDB server live hoeft te zijn.

## Environment Constraints
- Do NOT assume `gh` (GitHub CLI) is installed.
- Do NOT attempt to install global system packages.
- Use native `git` commands for version control.
- Use the GitHub REST API (via Python/curl) if interaction with GitHub releases is required.

## Git & Workflow

- **CRITICAL: Claude mag NOOIT commits maken onder de autornaam 'claude' of met een Claude e-mailadres. Gebruik ALTIJD de lokaal geconfigureerde Git-identiteit van de gebruiker (user.name / user.email).**
- **Dit geldt voor de VOLLEDIGE commit, niet alleen het auteursveld. Voeg NOOIT een `Co-Authored-By: Claude ...` trailer of enige andere verwijzing naar een Claude/Anthropic e-mailadres toe aan de commit message.**
- De identiteit staat vast in de repository zelf (`.git/config`): `user.name=Yes!` en `user.email=iasdoubleyou@hotmail.com`. Overschrijf deze niet en gebruik geen `--author`, `GIT_AUTHOR_*` of `GIT_COMMITTER_*` om ervan af te wijken.
- Controleer bij twijfel met `git log -1 --pretty="%an <%ae>%n%b"` dat zowel de auteur als de message vrij zijn van Claude-verwijzingen.

TAALAFSPRAKEN:
- Communiceer met de gebruiker (toelichting, commits, voortgang) altijd in het Nederlands.
- De README.md en code-comments blijven in het Engels (i.v.m. de internationale HACS-community).
- De Home Assistant UI gebruikt de al aanwezige vertaalbestanden (nl.json / en.json).