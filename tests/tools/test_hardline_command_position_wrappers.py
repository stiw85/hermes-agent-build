"""The hardline floor follows the command, not its spelling.

A path-qualified executable, a leading ``VAR=value`` assignment, ``sudo -u USER`` and the
``command`` builtin all run the same program as the bare name, so they must reach the same
unconditional block. Quoted prose and arguments that merely look like those paths must not.
"""

import pytest

from tools.approval_detection import detect_dangerous_command, detect_hardline_command

_SAME_PROGRAM_OTHER_SPELLING = [
    "/sbin/reboot",
    "sudo /sbin/shutdown -h now",
    "FOO=1 reboot",
    "A=1 B=2 shutdown -h now",
    "sudo -u root reboot",
    "sudo FOO=1 reboot",
    "command reboot",
    "env -i reboot",
    "/usr/bin/mkfs.ext4 /dev/sda1",
    "X=1 mkfs.ext4 /dev/sda1",
    "/bin/dd if=/dev/zero of=/dev/sda",
    "/bin/rm -rf /",
    "FOO=bar rm -rf /",
    "command rm -rf /",
    "echo ok; /sbin/poweroff",
    "true && FOO=1 halt",
]

_NOT_A_COMMAND = [
    "ls /sbin/reboot",
    "cat /usr/sbin/shutdown",
    "cd /usr/bin/rm -rf /",
    "file /sbin/mkfs.ext4",
    "echo FOO=1 reboot",
    'git commit -m "run /sbin/reboot after deploy"',
    "grep -r 'command reboot' docs/",
    "REBOOT=1 make test",
    "sudo -u root whoami",
]


@pytest.mark.parametrize("command", _SAME_PROGRAM_OTHER_SPELLING)
def test_other_spellings_of_a_hardline_command_are_blocked(command):
    is_hardline, description = detect_hardline_command(command)
    assert is_hardline, f"expected hardline to match {command!r}"
    assert description


@pytest.mark.parametrize("command", _NOT_A_COMMAND)
def test_paths_and_prose_naming_the_command_are_not_blocked(command):
    is_hardline, description = detect_hardline_command(command)
    assert not is_hardline, f"expected hardline NOT to match {command!r} (got: {description})"


@pytest.mark.parametrize("command", ["/usr/bin/mkfs.ext4 /dev/sdb1", "X=1 mkfs /dev/sdb", "/bin/dd if=a.img of=b.img"])
def test_other_spellings_still_reach_the_approval_prompt(command):
    assert detect_dangerous_command(command)[0], f"expected {command!r} to need approval"
