"""Pure validation for the native PostgreSQL fixture runner. No server I/O."""
from pathlib import Path
import re

ROLE = "fixture_admin"
ALLOWED_ENV = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
               "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMDRIVE",
               "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA"}


def sanitized_env(source):
    return {k: v for k, v in source.items() if k.upper() in ALLOWED_ENV}


def version_is_16(output):
    return isinstance(output, str) and bool(re.fullmatch(
        r"(?:initdb|pg_ctl|postgres|psql) \(PostgreSQL\) 16(?:\.\d+)?(?:\s+[^\r\n]+)?",
        output.strip()))


def handshake_matches(output, cluster, port):
    """Reject a malformed or different server identity before fixture SQL."""
    if not isinstance(output, str) or type(port) is not int or not 1 <= port <= 65535:
        return False
    fields = output.strip().split("|")
    if len(fields) != 5:
        return False
    directory, version, address, actual_port, role = fields
    if (not directory or not re.fullmatch(r"[0-9]{6}", version)
            or not re.fullmatch(r"[0-9]{1,5}", actual_port)
            or address not in {"127.0.0.1", "127.0.0.1/32"}
            or role != ROLE):
        return False
    try:
        return (Path(directory).resolve() == Path(cluster).resolve()
                and 160000 <= int(version) < 170000 and int(actual_port) == port)
    except (OSError, ValueError, RuntimeError):
        return False


def self_test():
    from tempfile import TemporaryDirectory
    env = sanitized_env({"PATH": "fixture", "SystemRoot": "fixture",
                         "PGHOST": "external", "PGPASSWORD": "secret",
                         "PGSERVICE": "external", "SUPABASE_URL": "external",
                         "SV_REVIEW_AUDIT_API_KEY": "secret"})
    assert env == {"PATH": "fixture", "SystemRoot": "fixture"}
    for name in ("initdb", "pg_ctl", "postgres", "psql"):
        assert version_is_16(f"{name} (PostgreSQL) 16.12\n")
    assert not version_is_16("postgres (PostgreSQL) 17.2")
    assert not version_is_16("not-postgres (PostgreSQL) 16.12")
    assert not version_is_16("psql (PostgreSQL) 160.1")
    with TemporaryDirectory() as tmp:
        cluster = Path(tmp) / "data"
        def sample(path=cluster, version="160012", addr="127.0.0.1/32", port="54321", role=ROLE):
            return f"{path}|{version}|{addr}|{port}|{role}\n"
        assert handshake_matches(sample(), cluster, 54321)
        assert handshake_matches(sample(addr="127.0.0.1"), cluster, 54321)
        for bad in (sample(path=cluster.parent / "other"), sample(version="170012"),
                    sample(version="invalid"), sample(addr="192.0.2.1"),
                    sample(port="54322"), sample(port="invalid"),
                    sample(role="postgres"), sample()+"extra", "", None):
            assert not handshake_matches(bad, cluster, 54321)
        assert not handshake_matches(sample(), cluster, True)
    print("POSTGRES_NATIVE_GUARD_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
