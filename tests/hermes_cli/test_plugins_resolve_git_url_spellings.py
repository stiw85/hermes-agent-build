"""Install identifiers as people paste them resolve to a cloneable GitHub URL."""

import pytest

from hermes_cli.plugins_cmd import _repo_name_from_url, _resolve_git_url


@pytest.mark.parametrize("identifier", [
    "https://github.com/owner/repo?tab=readme-ov-file",
    "https://github.com/owner/repo/?tab=readme-ov-file",
    "owner/repo.git",
    "owner/repo.git/",
])
def test_resolves_to_the_plain_repo(identifier):
    url, subdir = _resolve_git_url(identifier)

    assert url.removesuffix(".git").rstrip("/") == "https://github.com/owner/repo"
    assert subdir is None
    assert _repo_name_from_url(url) == "repo"


def test_shorthand_git_suffix_keeps_its_subdirectory():
    assert _resolve_git_url("owner/repo.git/plugins/x") == ("https://github.com/owner/repo.git", "plugins/x")


def test_fragment_subdir_survives_a_query_string():
    assert _resolve_git_url("https://github.com/owner/repo?tab=readme#plugins/x") == (
        "https://github.com/owner/repo", "plugins/x")
