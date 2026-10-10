"""extract_local_files removes only the bare path it delivers, not other text that contains it."""

import pytest

from gateway.platforms.base import BasePlatformAdapter


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_text("x")
    return str(path)


def test_same_path_in_code_survives_when_bare_copy_is_delivered(report):
    text = f"Saved to {report}\n\nRebuild with:\n```bash\npandoc in.md -o {report}\n```\nor `open {report}`."
    paths, cleaned = BasePlatformAdapter.extract_local_files(text)
    assert paths == [report]
    assert cleaned == f"Saved to \n\nRebuild with:\n```bash\npandoc in.md -o {report}\n```\nor `open {report}`."


def test_url_containing_the_path_is_untouched(report):
    text = f"Saved to {report} (mirror https://example.com{report})"
    paths, cleaned = BasePlatformAdapter.extract_local_files(text)
    assert paths == [report]
    assert cleaned == f"Saved to  (mirror https://example.com{report})"


def test_repeated_bare_path_is_removed_everywhere_and_listed_once(report):
    paths, cleaned = BasePlatformAdapter.extract_local_files(f"See {report} and again {report} done")
    assert paths == [report]
    assert cleaned == "See  and again  done"
