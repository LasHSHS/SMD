"""Single-instance lock so only one SMD window can run at a time."""
from __future__ import annotations

import atexit
import os
import tempfile
from pathlib import Path

import psutil

# Repo root (parent of gui/). Used to identify our own GUI script in process lists.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SMD_GUI_SCRIPT = (_REPO_ROOT / "desktop_gui_pyqt.py").resolve()


def _cmdline_runs_smd_gui(cmdline: list) -> bool:
    """True only when cmdline is actually executing desktop_gui_pyqt.py (not -c one-liners)."""
    if len(cmdline) < 2:
        return False
    if cmdline[1] in ('-c', '-m'):
        return False
    script_name = _SMD_GUI_SCRIPT.name
    for arg in cmdline[1:]:
        if arg.startswith('-'):
            continue
        try:
            if Path(arg).resolve() == _SMD_GUI_SCRIPT:
                return True
        except (OSError, ValueError):
            pass
        normalized = str(arg).replace('\\', '/')
        if normalized.endswith('/' + script_name) or normalized == script_name:
            return True
    return False


def _process_runs_smd_gui(proc: psutil.Process, my_pid=None) -> bool:
    if my_pid is not None and proc.pid == my_pid:
        return False
    try:
        name = (proc.name() or '').lower()
        if 'python' not in name:
            return False
        return _cmdline_runs_smd_gui(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


class SingleInstance:
    """Ensures only one instance of the application can run at a time"""
    def __init__(self, port=58923):  # Changed to different port
        self.port = port
        self.socket = None
        self.lock_file = None
        self.lock_path = Path(tempfile.gettempdir()) / 'snapchat_memories_gui.lock'
        self.signal_file = Path(tempfile.gettempdir()) / 'snapchat_memories_show.signal'
        
    def force_takeover(self) -> None:
        """Terminate a stuck prior instance and clear the lock so we can start fresh."""
        pid = None
        try:
            if self.lock_path.exists():
                pid_str = self.lock_path.read_text(encoding='utf-8').strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
        except OSError:
            pass
        if pid is not None and pid != os.getpid():
            try:
                proc = psutil.Process(pid)
                if proc.is_running() and _process_runs_smd_gui(proc):
                    print(f"DEBUG: Terminating unresponsive instance PID {pid}")
                    proc.terminate()
                    proc.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied):
                try:
                    if pid is not None:
                        psutil.Process(pid).kill()
                except Exception:
                    pass
            except Exception as exc:
                print(f"DEBUG: force_takeover: {exc}")
        try:
            if self.lock_path.exists():
                self.lock_path.unlink()
        except OSError:
            pass
        try:
            if self.signal_file.exists():
                self.signal_file.unlink()
        except OSError:
            pass

    def _read_lock_pid(self) -> int | None:
        try:
            pid_str = self.lock_path.read_text().strip()
            return int(pid_str) if pid_str.isdigit() else None
        except (OSError, ValueError):
            return None

    def _lock_owner_is_alive(self, pid: int) -> bool:
        if not psutil.pid_exists(pid):
            return False
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name().lower()
            print(f"DEBUG: Found process {pid} with name: {proc_name}")
            if 'python' not in proc_name:
                return False
            cmdline = proc.cmdline()
            print(f"DEBUG: Process command line: {cmdline}")
            return _cmdline_runs_smd_gui(cmdline)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            # Can't confirm cmdline, but the PID is alive - assume it's ours
            # rather than risk two full instances running at once.
            return True

    def is_already_running(self):
        """Claim the single-instance lock, or detect that another instance
        already holds it.

        Uses an atomic exclusive-create ('x' mode) instead of a separate
        exists()-check-then-write() - the old two-step version had a real
        TOCTOU race: two processes launched close together (e.g. a
        double-click registering twice) could each see "no lock file yet"
        and both proceed to build a full window, doubling startup cost and
        leaving two independent windows fighting over the same account
        data. 'x' mode makes the OS itself the single arbiter of who wins.
        """
        # Up to 2 attempts: first with whatever's on disk, second after
        # clearing a confirmed-stale lock left by a dead process.
        for attempt in range(2):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner_pid = self._read_lock_pid()
                if owner_pid is not None and self._lock_owner_is_alive(owner_pid):
                    print(f"DEBUG: Confirmed running instance with PID {owner_pid}")
                    return True
                print("DEBUG: Removing stale lock file")
                try:
                    self.lock_path.unlink()
                except OSError:
                    pass
                continue
            except OSError as e:
                print(f"DEBUG: Error in is_already_running: {e}")
                return False
            else:
                with os.fdopen(fd, 'w') as f:
                    f.write(str(os.getpid()))
                print(f"DEBUG: Created lock file with PID {os.getpid()}")
                atexit.register(self.cleanup)
                return False
        # Lost the race twice in a row (very unlikely) - fail safe by
        # deferring rather than risking a duplicate window.
        return True
    
    def cleanup(self):
        """Clean up resources"""
        try:
            if self.lock_file:
                self.lock_file.close()
            if self.lock_path and self.lock_path.exists():
                self.lock_path.unlink()
            if self.signal_file and self.signal_file.exists():
                self.signal_file.unlink()
        except Exception:
            pass
