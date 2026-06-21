"""Daemon lifecycle management (start, stop, status, logs)."""

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .service import PersonalAssistantDaemon

logger = logging.getLogger(__name__)


# Use ASCII-safe output for cross-platform compatibility
class Output:
    """Output helper for cross-platform Unicode/ASCII."""

    @staticmethod
    def ok(msg: str) -> None:
        logger.info(msg)
        print(f"[OK] {msg}")

    @staticmethod
    def error(msg: str) -> None:
        logger.error(msg)
        print(f"[ERROR] {msg}")

    @staticmethod
    def info(msg: str) -> None:
        logger.info(msg)
        print(f"[INFO] {msg}")

    @staticmethod
    def warning(msg: str) -> None:
        logger.warning(msg)
        print(f"[WARN] {msg}")


class DaemonManager:
    """Manage daemon lifecycle: start, stop, status, logs."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.daemon = PersonalAssistantDaemon(config)

    async def start(self, foreground: bool = False) -> None:
        """
        Start the daemon.

        Args:
            foreground: If True, run in foreground (for debugging). Otherwise, daemonize.
        """
        if self.daemon.read_pid() is not None:
            Output.error("Daemon is already running")
            return

        if foreground:
            # Run in foreground for debugging
            Output.info("Starting daemon in foreground mode...")
            await self.daemon.initialize()
            self.daemon.write_pid()
            try:
                await self.daemon.run()
            except KeyboardInterrupt:
                Output.info("\nDaemon stopped by user")
            finally:
                self.daemon.remove_pid()
        else:
            # Daemonize on Unix-like systems
            if sys.platform == "win32":
                # On Windows, use subprocess
                await self._start_windows()
            else:
                # On Unix, use proper daemonization
                await self._start_unix()

    async def _start_windows(self) -> None:
        """Start daemon on Windows using subprocess."""
        Output.info("Starting daemon in background...")

        # Create a Python subprocess that runs the daemon
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.daemon.service", "run"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )

        # Give it a moment to start and write PID
        await asyncio.sleep(1)

        if self.daemon.read_pid() is not None:
            Output.ok(f"Daemon started (PID: {proc.pid})")
        else:
            Output.error("Failed to start daemon")

    async def _start_unix(self) -> None:
        """Start daemon on Unix using proper daemonization."""
        Output.info("Starting daemon in background...")

        # Fork and start daemon
        try:
            pid = os.fork()
            if pid > 0:
                # Parent process - wait for child to be ready
                await asyncio.sleep(1)
                child_pid = self.daemon.read_pid()
                if child_pid:
                    Output.ok(f"Daemon started (PID: {child_pid})")
                else:
                    Output.error("Failed to start daemon")
                return

            # Child process - daemonize
            os.chdir("/")
            os.setsid()
            os.umask(0)

            # Fork again to prevent daemon from acquiring a controlling terminal
            pid = os.fork()
            if pid > 0:
                os._exit(0)

            # Redirect file descriptors
            sys.stdout.flush()
            sys.stderr.flush()
            si = open("/dev/null", "r")
            so = open("/dev/null", "a+")
            se = open("/dev/null", "a+")
            os.dup2(si.fileno(), sys.stdin.fileno())
            os.dup2(so.fileno(), sys.stdout.fileno())
            os.dup2(se.fileno(), sys.stderr.fileno())

            # Now run the daemon
            await self.daemon.initialize()
            self.daemon.write_pid()
            await self.daemon.run()

        except Exception as e:
            Output.error(f"Failed to start daemon: {e}")
            sys._exit(1)

    async def stop(self, force: bool = False) -> None:
        """
        Stop the running daemon.

        Args:
            force: If True, use SIGKILL instead of SIGTERM
        """
        pid = self.daemon.read_pid()
        if pid is None:
            Output.error("Daemon is not running")
            return

        sig = signal.SIGKILL if force else signal.SIGTERM
        sig_name = "SIGKILL" if force else "SIGTERM"

        try:
            Output.info(f"Stopping daemon (PID: {pid}) with {sig_name}...")
            os.kill(pid, sig)

            # Wait for daemon to stop
            for _ in range(30):  # 30 seconds timeout
                try:
                    os.kill(pid, 0)  # Check if process exists
                except OSError:
                    # Process is gone
                    self.daemon.remove_pid()
                    Output.ok("Daemon stopped")
                    return
                await asyncio.sleep(1)

            Output.warning("Daemon did not stop gracefully, forcing termination...")
            os.kill(pid, signal.SIGKILL)
            self.daemon.remove_pid()
            Output.ok("Daemon force-stopped")

        except OSError:
            self.daemon.remove_pid()
            Output.ok("Daemon was not running")
        except Exception as e:
            Output.error(f"Error stopping daemon: {e}")

    def status(self) -> None:
        """Get daemon status."""
        pid = self.daemon.read_pid()

        if pid is None:
            Output.error("Daemon is not running")
            return

        # Check if process actually exists
        try:
            os.kill(pid, 0)
            Output.ok(f"Daemon is running (PID: {pid})")
            logger.debug(f"Log file: {self.daemon.config.log_file}")
        except OSError:
            Output.warning("Daemon PID file exists but process is not running")
            self.daemon.remove_pid()

    def logs(self, follow: bool = False, lines: int = 50) -> None:
        """
        Show daemon logs.

        Args:
            follow: If True, tail the logs (like 'tail -f')
            lines: Number of lines to show
        """
        log_file = self.daemon.config.log_file

        if not log_file.exists():
            Output.warning(f"No log file yet: {log_file}")
            return

        if follow:
            Output.info(f"Tailing logs from {log_file} (Ctrl+C to stop)...")
            try:
                if sys.platform == "win32":
                    # Windows: use PowerShell Get-Content -Wait
                    subprocess.run(
                        ["powershell", "-Command", f"Get-Content -Wait -Tail {lines} '{log_file}'"],
                        check=False,
                    )
                else:
                    # Unix: use tail -f
                    subprocess.run(
                        ["tail", "-f", str(log_file)],
                        check=False,
                    )
            except KeyboardInterrupt:
                print("\nLog tail stopped")
        else:
            Output.info(f"Last {lines} lines of {log_file}:")
            try:
                with open(log_file, "r") as f:
                    all_lines = f.readlines()
                    for line in all_lines[-lines:]:
                        print(line.rstrip())
            except Exception as e:
                Output.error(f"Error reading logs: {e}")

    def reset_logs(self) -> None:
        """Clear the log file."""
        log_file = self.daemon.config.log_file

        if log_file.exists():
            log_file.unlink()
            Output.ok(f"Log file cleared: {log_file}")
        else:
            Output.warning("No log file to clear")
