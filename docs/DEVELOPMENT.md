# Development

## Design goal

Elite Journal Helper is a live companion application. Changes should prioritize:

1. correctness of journal-derived state;
2. quick startup and responsive UI updates;
3. readable layouts beside Elite Dangerous at non-maximized widths;
4. recovery controls when journal data is incomplete;
5. keeping normal-user workflows simpler than developer/debug workflows.

## Source layout

`ed_journal_probe.py` is intentionally the only Python file at the repository root. It is a small compatibility launcher so existing user shortcuts keep working.

Runtime code lives in `src/elite_journal_helper/`:

| File | Responsibility |
| --- | --- |
| `app.py` | CLI, splash screen, startup wiring |
| `journal.py` | journal discovery, indexing, live events, Cargo/Market data |
| `state.py` | commander/system/body state models |
| `ui.py` | main dashboard and Mini Mode |
| `construction_ui.py` | Construction Mode workflow and views |
| `construction_rules.py` | facility catalog, prerequisites, construction-point rules |
| `rules.py` | exploration/high-value/special-target rules |
| `search_targets.py` | mining/search definitions |
| `ships.py` | ship names and icon paths |
| `bio_icons.py` | biological icon rendering helpers |
| `paths.py` | repository/install resource paths |
| `version.py` | application version metadata |

The compatibility launcher prepends `src/` to `sys.path` and delegates to `elite_journal_helper.app.main()`.

## Tests

Install development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run:

```bash
python -m pytest -q
```

`pytest.ini` adds `src/` to the test import path.

## Startup profiling

Normal launches are quiet:

```bash
./ed_journal_probe.py
```

Enable detailed startup timings only when diagnosing performance:

```bash
./ed_journal_probe.py --profile-startup
```

## Generated/local files

Do not commit caches, local runtime databases, `PreviousVersion-*` backups, `.bak` files, patches, Elite journal logs, credentials, or local environment files. Git history and release tags should be used for version recovery.
