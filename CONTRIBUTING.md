# Contributing

Issues and pull requests are welcome.

## Development

```sh
git clone https://github.com/mmmusavi/dutch-waterways && cd dutch-waterways
uv sync --all-extras
uv run pytest              # offline tests (the browser-router tests need node)
uv run pytest -m online    # end-to-end against live FIS and Nominatim
```

The web map runs from `web/` after `uv run dutch-waterways export-web`; serve
it with `python3 -m http.server -d web 8000`. Its router (`web/router.js`)
mirrors `src/dutch_waterways/network.py`: change both together, and
`tests/test_web.py` checks they agree.

How the FIS data is read is in [docs/data-notes.md](docs/data-notes.md).

## Releasing

1. Bump `version` in `pyproject.toml` and `CITATION.cff` (and
   `date-released`).
2. Commit, push, and create a GitHub release: `gh release create vX.Y.Z`.

The release workflow runs the tests and publishes to PyPI with Trusted
Publishing; Zenodo archives the release and gives it a DOI. The web map is
rebuilt from live FIS on every push to `main` and on the 1st of each month.
