"""Explicit, non-persistent GUI session handoff. Never removes a socket guard."""
import subprocess
import sys
from pathlib import Path

FLAG = '--udp-test-session'
GRANT = b'CONFIRMED_UDP_TEST_SESSION\n'


def startup_mode(argv=None, stream=None):
    argv = sys.argv if argv is None else argv
    if FLAG not in argv:
        return 'dry_run'
    stream = sys.stdin if stream is None else stream
    # Standard launchers (including a manual restart) have no one-shot grant.
    if stream is None or stream.isatty():
        return 'dry_run'
    return 'normal' if stream.buffer.readline(128) == GRANT else 'dry_run'


def launch_session(mode):
    if mode not in ('dry_run', 'normal'):
        raise ValueError('Unknown output mode')
    launcher = Path(__file__).with_name('START_GUI.pyw')
    args = [sys.executable, '-B', str(launcher)]
    if mode == 'normal':
        args.append(FLAG)
    child = subprocess.Popen(args, stdin=subprocess.PIPE,
                             cwd=str(launcher.parent))
    try:
        if mode == 'normal':
            child.stdin.write(GRANT)
            child.stdin.flush()
    finally:
        child.stdin.close()
    return child
