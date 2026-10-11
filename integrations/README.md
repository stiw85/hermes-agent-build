# integrations/

Third-party products that run on or with Hermes, vendored as source. Nothing under `integrations/`
is imported by the Hermes core, and the core's lint and code-health gates skip this tree
(`scripts/check_no_tmp_literals.py` `SKIP_REL_DIRS`, `scripts/code_health/config.py` `PY_EXCLUDE`).

## herald-os/

Herald OS, an agent-native desktop built on Hermes Agent. Its Hermes part is the `herald-os-bridge`
plugin in `herald-os/plugins/herald-os-bridge/`, which gives Hermes permission-tiered system tools
through public plugin APIs only.

- **Source:** `stiw85/herald-os-hermes` (a fork of `iamlukethedev/Herald-OS`), commit
  `7babe0c52076c95c722f603631a9421448b2fbbc`, copied with `git archive` (no `.git` directory).
- **Licence:** MIT, Copyright (c) 2026 Luke The Dev. Its `LICENSE` and `NOTICE` are kept in
  `herald-os/`.
- **Local changes in this copy:**
  - `plugins/herald-os-bridge/bridge/permissions.py`: the policy file is read with `ruamel.yaml`, which
    this fork installs, instead of PyYAML, which it does not. Before the change, every policy file
    was silently ignored and the default tiers applied.
  - `linux/tests/test_firstboot.py`: an explicit `encoding="utf-8"` on `write_text`, for the fork's ruff rule.
  - `apps/desktop/shared/office/xlsx/comments/checks.ts`: the default test interpreter path is built from
    `tmpdir()` instead of a literal `/tmp` path.

## Running the bridge's tests

```bash
cd integrations/herald-os/plugins/herald-os-bridge
PYTHONPATH=../../../.. python -m pytest tests -q -p no:cacheprovider
```

## Updating

Replace the copy from a newer commit of the fork, then re-apply the local changes above and re-run
the bridge's tests and `scripts/check`.
