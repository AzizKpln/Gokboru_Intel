from __future__ import annotations

import builtins
import getpass
import signal
from contextlib import redirect_stdout, contextmanager
import sys


@contextmanager
def hidden_web_browsers(enabled):
    if not enabled:
        yield
        return
    from playwright.sync_api import BrowserType
    launch = BrowserType.launch
    persistent = BrowserType.launch_persistent_context
    def hidden_launch(self, *args, **kwargs):
        kwargs["headless"] = True
        return launch(self, *args, **kwargs)
    def hidden_persistent(self, *args, **kwargs):
        kwargs["headless"] = True
        return persistent(self, *args, **kwargs)
    BrowserType.launch = hidden_launch
    BrowserType.launch_persistent_context = hidden_persistent
    try:
        yield
    finally:
        BrowserType.launch = launch
        BrowserType.launch_persistent_context = persistent


def run_unattended(runner, timeout_seconds, *, headless=False):
    def reject_input(*args, **kwargs):
        raise EOFError("Interactive sign-in is required. Complete this source's login in the console, then retry the web scan.")

    def expired(*args):
        raise TimeoutError("Source exceeded its web scan time limit.")

    previous_input, previous_password = builtins.input, getpass.getpass
    timed = hasattr(signal, "SIGALRM")
    previous_handler = None
    try:
        builtins.input = reject_input
        getpass.getpass = reject_input
        if timed:
            previous_handler = signal.signal(signal.SIGALRM, expired)
            signal.setitimer(signal.ITIMER_REAL, max(1.0, float(timeout_seconds)))
        with redirect_stdout(sys.stderr), hidden_web_browsers(headless):
            return runner()
    except EOFError as exc:
        return {"status": "manual_action_required", "note": str(exc)}
    except TimeoutError:
        return {"status": "timeout", "note": "Source exceeded its web scan time limit; remaining sources will continue."}
    finally:
        if timed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
        builtins.input, getpass.getpass = previous_input, previous_password
