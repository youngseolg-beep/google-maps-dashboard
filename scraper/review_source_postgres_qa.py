"""Run fixture in a fresh local Docker PostgreSQL 16 container only.

No network, host mounts, ports, production credentials or external DSN.
Requires an already installed local postgres:16 image. No image pull.
Not part of ordinary offline QA (requires Docker and separate subprocesses).
"""
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

SQL = Path(__file__).with_name("review_source_postgres_fixture.sql")
IMAGE = "postgres:16"
STORE = "10000000-0000-0000-0000-000000000001"


def run_fixture_checks(psql):
    """Shared serial/permission/rollback/concurrency tests on an isolated fixture."""
    if not __debug__:
        raise RuntimeError("ASSERTIONS_REQUIRED")
    version = psql("SHOW server_version_num;").strip()
    if not 160000 <= int(version) < 170000:
        raise RuntimeError("FIXTURE_POSTGRES_VERSION_UNEXPECTED")
    assert "POSTGRES_FIXTURE_SERIAL_PASS" in psql(SQL.read_text(encoding="utf-8"))
    def concurrent(n):
        return psql("SET ROLE fixture_writer; BEGIN; SELECT fixture_private.append_fixture("
                    f"'{STORE}',repeat('f',64),'00000000-0000-0000-0000-00000000001{n}',"
                    f"'parallel-{n}','synthetic'); SELECT pg_sleep(1); COMMIT;")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(concurrent,(1,2)))
    combined = "\n".join(outputs).splitlines()
    assert combined.count("APPENDED") == 1 and combined.count("LINKED_NO_INSERT") == 1
    assert psql("SELECT count(*) FROM fixture_private.reviews;").strip() == "3"
    assert psql("SELECT count(*) FROM fixture_private.source_links;").strip() == "2"
    assert psql("SELECT count(*) FROM fixture_private.reviews WHERE review_key LIKE 'parallel-%';").strip() == "1"
    print("POSTGRES_FIXTURE_CONCURRENT_PASS")


def main():
    if len(sys.argv) != 1:
        raise SystemExit("No external DB arguments accepted")
    env = {k:v for k,v in os.environ.items() if k.upper() in {
        "PATH","SYSTEMROOT","WINDIR","COMSPEC","PATHEXT","HOME","USERPROFILE",
        "APPDATA","LOCALAPPDATA","TEMP","TMP","TMPDIR","SYSTEMDRIVE"}}
    def docker(args, data=None, timeout=30):
        return subprocess.run(["docker", *args], input=data, text=True,
                              capture_output=True, env=env, timeout=timeout, check=True)
    # Explicitly reject remote contexts and TCP/SSH Docker daemons.
    endpoint = docker(["context","inspect","--format","{{.Endpoints.docker.Host}}"]).stdout.strip()
    if not endpoint.startswith(("unix://","npipe://")):
        raise RuntimeError("LOCAL_DOCKER_REQUIRED")
    name = "sv-review-fixture-" + uuid.uuid4().hex
    created = False
    try:
        docker(["run","--detach","--pull=never","--network","none","--name",name,
                "-e","POSTGRES_HOST_AUTH_METHOD=trust",IMAGE])
        created = True
        def psql(sql, timeout=30):
            return docker(["exec","-i",name,"psql","-X","-qAt","-v","ON_ERROR_STOP=1",
                           "-h","127.0.0.1","-U","postgres","-d","postgres"],sql,timeout).stdout
        for _ in range(60):
            try:
                if psql("SELECT 1;").strip() == "1":
                    break
            except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
                time.sleep(1)
        else:
            raise RuntimeError("FIXTURE_POSTGRES_NOT_READY")
        run_fixture_checks(psql)
    finally:
        if created:
            docker(["rm","-fv",name])
    print("POSTGRES_FIXTURE_ALL_PASS: synthetic only; production_writes=false")


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Assertions required")
    main()
