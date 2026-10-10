"""``format_bytes`` just below a unit boundary.

A value that rounds up to 1024.0 of a unit belongs to the next unit: ``1024.0 KB`` is the same
defect as the ``1024.0 GB`` the TB tier was added to remove.
"""

import pytest

from hermes_cli.sizefmt import format_bytes


@pytest.mark.parametrize("n,expected", [
    (1024**2 - 1, "1.0 MB"),
    (1024**3 - 1, "1.0 GB"),
    (1024**4 - 1, "1.0 TB"),
    (1024**2 - 60, "1023.9 KB"),   # still rounds to a value below the boundary
    (1023, "1023 B"),
    (1023.9, "1023 B"),
])
def test_values_rounding_to_the_boundary_move_up_a_unit(n, expected):
    assert format_bytes(n) == expected
