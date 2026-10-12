"""An app that advertises an IPv6 loopback endpoint must get a usable URL back."""

from __future__ import annotations

import json
import os
import socket
import sys
from urllib.parse import urlsplit

from hermes_platform.resolver import CheckState, Effort
from hermes_platform.resolver.app import AppDef, AppLocation, AppResolver


def _resolver(tmp_path, url):
    exe = tmp_path / "thing"
    exe.write_text("", encoding="utf-8")
    server_json = tmp_path / "server.json"
    server_json.write_text(json.dumps({"pid": os.getpid(), "http": url, "token": "t"}), encoding="utf-8")
    return AppResolver(AppDef(
        "thing", sys.platform, "executable", (AppLocation("path", str(exe)),),
        liveness_kind="server_json", liveness_path=str(server_json),
    ))


def test_ipv6_loopback_endpoint_is_a_parseable_url(tmp_path):
    endpoint = _resolver(tmp_path, "http://[::1]:8123/whatever").endpoint()

    assert endpoint is not None and endpoint.url == "http://[::1]:8123/mcp"
    parts = urlsplit(endpoint.url)
    assert (parts.hostname, parts.port, parts.path) == ("::1", 8123, "/mcp")


def test_ipv6_loopback_probe_dials_the_advertised_address(tmp_path, monkeypatch):
    dialled = []

    def refuse(address, *args, **kwargs):
        dialled.append(address)
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", refuse)
    resolver = _resolver(tmp_path, "http://[::1]:8123/whatever")

    probe = resolver.probe(resolver.locate(), effort=Effort.NETWORK)

    assert dialled == [("::1", 8123)]
    assert probe.endpoint.state is CheckState.PRESENT
    assert probe.answering.state is CheckState.ABSENT
