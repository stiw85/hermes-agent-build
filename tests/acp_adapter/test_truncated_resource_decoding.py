"""An attached text file cut at the inline cap stays in its own encoding."""

from __future__ import annotations

import base64

import pytest
from acp.schema import BlobResourceContents, EmbeddedResourceContentBlock, ResourceContentBlock

from acp_adapter import content


@pytest.fixture
def big_utf8(tmp_path):
    """UTF-8 text over the cap whose cap offset falls inside a multibyte character."""
    path = tmp_path / "notes.md"
    path.write_text("a" + "héllo wörld — ünïcode\n" * 30000, encoding="utf-8")
    raw = path.read_bytes()
    assert len(raw) > content._MAX_ACP_RESOURCE_BYTES
    assert raw[content._MAX_ACP_RESOURCE_BYTES] & 0xC0 == 0x80
    return path, raw


def _body(parts):
    return parts[0]["text"].split("\n\n", 1)[1]


def test_truncated_resource_link_keeps_utf8(big_utf8):
    path, _raw = big_utf8
    parts = content._resource_link_to_parts(
        ResourceContentBlock(type="resource_link", uri=path.as_uri(), name="notes.md"))

    body = _body(parts)
    assert body.startswith("ahéllo wörld — ünïcode\n")
    assert "Ã" not in body and "�" not in body
    assert "truncated to" in parts[0]["text"].split("\n", 1)[0]


def test_truncated_embedded_blob_keeps_utf8(big_utf8):
    path, raw = big_utf8
    blob = BlobResourceContents(uri=path.as_uri(), blob=base64.b64encode(raw).decode(), mime_type="text/markdown")

    body = _body(content._embedded_resource_to_parts(EmbeddedResourceContentBlock(type="resource", resource=blob)))

    assert body.startswith("ahéllo wörld — ünïcode\n")
    assert "Ã" not in body and "�" not in body.split("\n\n[Truncated")[0]


def test_legacy_encoded_file_still_reads_as_latin1(tmp_path):
    path = tmp_path / "legacy.txt"
    path.write_bytes("café crème\n".encode("latin-1"))

    parts = content._resource_link_to_parts(ResourceContentBlock(type="resource_link", uri=path.as_uri(), name="legacy.txt"))

    assert _body(parts) == "café crème\n"
