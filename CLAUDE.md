# Working on Stats Collector

- Branches: feature work goes to `develop` (test channel) through pull requests; `main` is production. Production releases only with the owner's approval.
- Releases: run the **Release** workflow on `develop` for a test build (`vX.Y.Z-rc.N`, prerelease) or on `main` for a production release. Notes come from the `Unreleased` / `[X.Y.Z]` section of `CHANGELOG.md` and `CHANGELOG.nl.md`.
- Every change must update, in the same pull request:
  - `CHANGELOG.md` and `CHANGELOG.nl.md` (`Unreleased` section, headings Added/Changed/Removed/Fixed and Toegevoegd/Gewijzigd/Verwijderd/Opgelost);
  - the manual in `docs/manual/en` and `docs/manual/nl` for anything a user or administrator sees, with fresh screenshots in `docs/manual/images` (`en-*.png`, `nl-*.png`) when a screen changed;
  - both translations in `frontend/src/locales/en.json` and `nl.json` (`npm test` checks they match).
- The UI is English by default with a full Dutch translation; admin menus live in the left sidebar; colours come from the brand (`branding/default/theme.json`).
- Checks: `cd backend && ruff check . && pytest -q`; `cd frontend && npm test && npm run build`; `shellcheck -S warning install.sh scripts/*.sh`.
