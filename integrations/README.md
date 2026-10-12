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

## One-command setup (Hermes + Herald OS desktop)

`scripts/setup-herald.sh` is the complete package: it installs Hermes from this repository
(`scripts/install.sh`), runs Herald's own bootstrap (npm workspaces, the Electron binary, the
bridge link and `hermes plugins enable herald-os-bridge`), and installs a `herald` launcher plus
an application-menu entry. It needs git, curl and Node 22.12+, and is safe to re-run.

```bash
bash scripts/setup-herald.sh        # from a checkout; or standalone:
curl -fsSL https://raw.githubusercontent.com/stiw85/hermes-agent-build/claude/native-memory/scripts/setup-herald.sh | bash
```

Afterwards, `herald` (or "Herald OS" in the application menu) starts the desktop.
`tests/scripts/test_setup_herald.py` covers the script's plan in dry-run mode.

## Turning the bridge on by hand

`setup-herald.sh` above does this for you. The bridge is otherwise off until you enable it. It is
a plugin, so nothing is copied into your Hermes home:

```bash
ln -sfn "$PWD/integrations/herald-os/plugins/herald-os-bridge" "${HERMES_HOME:-$HOME/.hermes}/plugins/herald-os-bridge"
hermes plugins enable herald-os-bridge
hermes gateway restart    # if the gateway is running
```

Once enabled, its tools are offered only inside Herald OS's own sessions (`bridge/scope.py`). Ordinary
Hermes sessions never see them.

`tests/integrations/test_herald_os_bridge.py` checks both states (off by default, then enabled) against
a temporary home. It takes about a minute because it starts Hermes twice.

## Running the bridge's tests

```bash
cd integrations/herald-os/plugins/herald-os-bridge
PYTHONPATH=../../../.. python -m pytest tests -q -p no:cacheprovider
```

## Updating

Replace the copy from a newer commit of the fork, then re-apply the local changes above and re-run
the bridge's tests and `scripts/check`.
