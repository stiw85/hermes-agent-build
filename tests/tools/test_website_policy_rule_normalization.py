"""A blocklist rule names a HOST however it is written: a pasted URL with a port, a
``host:port`` pair or a URL with userinfo all block that host."""

import pytest

from tools.website_policy import check_website_access


@pytest.fixture()
def policy(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "security:\n  website_blocklist:\n    enabled: true\n    domains:\n"
        "      - 'https://intranet.example.org:8443/login'\n"
        "      - 'grafana.example.net:3000'\n"
        "      - 'https://ops:pw@wiki.example.io/'\n"
        "      - '*.corp.example:8080'\n"
        "      - 'plain.example'\n", encoding="utf-8")
    return config


@pytest.mark.parametrize("url", [
    "https://intranet.example.org:8443/x",
    "https://intranet.example.org/",
    "http://grafana.example.net:3000/d/abc",
    "https://wiki.example.io/Home",
    "https://build.corp.example:8080/job",
    "https://sub.plain.example/",
])
def test_rule_blocks_its_host(policy, url):
    blocked = check_website_access(url, policy)
    assert blocked is not None, f"{url} should be blocked"
    assert ":" not in blocked["rule"] and "@" not in blocked["rule"]


@pytest.mark.parametrize("url", [
    "https://example.org/", "https://notplain.example/", "https://corp.example/", "https://ops.example/"])
def test_unlisted_hosts_stay_allowed(policy, url):
    assert check_website_access(url, policy) is None
