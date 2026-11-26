"""Launch a process without captured pipes inherited by persistent children."""
import subprocess
from pathlib import Path


def launch_with_file_output(command, log, *, env, timeout):
    with Path(log).open("wb") as output:
        return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                              stderr=subprocess.STDOUT, env=env,
                              timeout=timeout, check=True)


def self_test():
    from tempfile import TemporaryDirectory
    from unittest.mock import patch
    with TemporaryDirectory() as tmp:
        log = Path(tmp) / "launcher.log"
        command = ["synthetic-command", "start"]
        env = {"PATH": "synthetic"}
        def fake_run(args, **kwargs):
            assert args == command
            assert kwargs["stdin"] == subprocess.DEVNULL
            assert kwargs["stderr"] == subprocess.STDOUT
            assert kwargs["stdout"].name == str(log)
            assert not kwargs["stdout"].closed
            assert kwargs["env"] == env and kwargs["timeout"] == 75
            assert kwargs["check"] is True
            assert "capture_output" not in kwargs and "input" not in kwargs
            kwargs["stdout"].write(b"fixture output")
            return subprocess.CompletedProcess(args, 0)
        with patch.object(subprocess, "run", side_effect=fake_run):
            assert launch_with_file_output(command, log, env=env, timeout=75).returncode == 0
        assert log.read_bytes() == b"fixture output"
        for exc in (subprocess.TimeoutExpired(command, 75),
                    subprocess.CalledProcessError(1, command)):
            with patch.object(subprocess, "run", side_effect=exc):
                try:
                    launch_with_file_output(command, log, env=env, timeout=75)
                except type(exc):
                    pass
                else:
                    raise AssertionError("launcher swallowed failure")
            # Closed even on errors (Windows permits unlink only if no
            # process has an open handle that disallows deletion).
            log.unlink()
    print("POSTGRES_LAUNCHER_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
