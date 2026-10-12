"""``flatten_single_dir`` hoists a wrapper's whole content or none of it.

A wrapper holding an entry with its own name (``tool/tool`` beside its docs and data) cannot
be hoisted; moving only the siblings would separate the binary from the files it ships with.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

from pm.store import extract, flatten_single_dir


def _tar(path: Path, members: dict[str, bytes]) -> Path:
    staging = path.parent / f".stage-{path.stem}"
    with tarfile.open(path, "w:gz") as tf:
        for rel, data in members.items():
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            tf.add(target, arcname=rel)
    return path


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_wrapper_with_a_same_named_child_and_siblings_is_left_intact(tmp_path):
    members = {"tool/LICENSE": b"mit", "tool/README.md": b"docs", "tool/tool": b"bin", "tool/share/data.bin": b"d"}
    dest = tmp_path / "dest"
    extract(_tar(tmp_path / "tool.tar.gz", members), dest)

    flatten_single_dir(dest)

    assert _files(dest) == sorted(members)
