# Working on Stats Collector

- Branches: feature work goes to `develop` (test channel) through pull requests; `main` is production. Production releases only with the owner's approval.
- Releases: push a tag `vX.Y.Z-rc.N` on `develop` for a test build (prerelease) or `vX.Y.Z` on `main` for a production release; the **Release** workflow builds, publishes and deploys the manual. Notes come from the `Unreleased` / `[X.Y.Z]` section of `CHANGELOG.md`.
- Every change must update, in the same pull request:
  - `CHANGELOG.md` (`Unreleased` section, headings Added/Changed/Fixed/Removed, every entry followed by an indented `NL:` line with the Dutch translation);
  - the manual in `docs/manual/en` and `docs/manual/nl` for anything a user or administrator sees, with fresh screenshots in `docs/manual/images` (`en-*.png`, `nl-*.png`) when a screen changed;
  - both translations in `frontend/src/locales/en.json` and `nl.json` (`npm test` checks they match).
- The UI is English by default with a full Dutch translation; admin menus live in the left sidebar; colours come from the brand (`branding/default/theme.json`).
- Checks: `cd backend && ruff check . && pytest -q`; `cd frontend && npm test && npm run build`; `shellcheck -S warning install.sh scripts/*.sh`.
