# Changelog

## v1.15.0 — Backend modularization

- Split the original `app.py` backend into domain-focused Python modules.
- Retained the `python app.py` and Windows launcher entry points.
- Preserved existing HTTP endpoints, frontend, and SQLite storage layout.
- Removed unused historical update notes and obsolete cast lookup helpers.
- Added smoke tests for movie management, Top 3, sagas, actors, and exports.
- Updated GitHub Actions to validate the package and run smoke tests.

## v1.14.0 — Interface updates

- Context-sensitive actions for franchise discovery and manual folders.
- Simplified controls for rating categories and artist ranking.

Earlier versions introduced the Top 3 podium, franchise collections, cast verification, series support, and OMDb/TMDb integrations.
