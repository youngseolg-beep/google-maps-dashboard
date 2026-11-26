"""Windows-only PostgreSQL 16 synthetic fixture using a NEW temporary cluster.

Accepts only a trusted local binary directory, not a DSN, database name,
existing data directory, or account. No download, service registration,
production credentials, or production database access.
"""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile

from review_source_postgres_qa import run_fixture_checks
from review_postgres_native_guard import ROLE, sanitized_env, version_is_16, handshake_matches

BIN_NAMES=("initdb","pg_ctl","postgres","psql")
def local_port():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir",type=Path,required=True,
                        help="Trusted installed/extracted PostgreSQL 16 bin directory only.")
    args=parser.parse_args()
    if os.name!="nt":
        raise SystemExit("WINDOWS_ONLY")
    if not __debug__:
        raise SystemExit("ASSERTIONS_REQUIRED")
    directory=args.bin_dir.resolve(strict=True)
    if not directory.is_dir() or str(directory).startswith("\\\\"):
        raise SystemExit("LOCAL_BINARY_DIRECTORY_REQUIRED")
    binaries={n:directory/(n+".exe") for n in BIN_NAMES}
    if not all(p.is_file() for p in binaries.values()):
        raise SystemExit("POSTGRES_16_BINARIES_NOT_FOUND")
    env=sanitized_env(os.environ)
    env["PATH"]=str(directory)+os.pathsep+env.get("PATH","")
    def run(name,arguments,*,data=None,timeout=60,check=True,extra_env=None):
        return subprocess.run([str(binaries[name]),*map(str,arguments)],
                              input=data,text=True,encoding="utf-8",errors="replace",
                              capture_output=True,env=dict(env,**(extra_env or {})),
                              timeout=timeout,check=check)
    for name in BIN_NAMES:
        if not version_is_16(run(name,["--version"]).stdout):
            raise SystemExit("POSTGRES_16_REQUIRED")
    root=Path(tempfile.mkdtemp(prefix="sv-review-pg-fixture-")).resolve()
    cluster=root/"data"
    pwfile=root/"init-password.txt"
    password=secrets.token_hex(32)
    port=local_port()
    start_attempted=False
    failure=None
    stage="INIT"
    try:
        pwfile.write_text(password+"\n",encoding="ascii")
        run("initdb",["-D",cluster,"-U",ROLE,"--auth=scram-sha-256",
                      "--pwfile",pwfile,"--encoding=UTF8","--no-locale"],timeout=120)
        pwfile.unlink()
        stage="START"
        # Use fresh configuration and loopback only; no existing PGDATA.
        start_attempted=True
        run("pg_ctl",["-D",cluster,"-l",root/"server.log","-w","-t","60",
                      "-o",f"-h 127.0.0.1 -p {port} -c ssl=off -c fsync=on",
                      "start"],timeout=75)
        stage="VERIFY_CLUSTER"
        pg_env={"PGPASSWORD":password,"PGCONNECT_TIMEOUT":"5",
                "PGCLIENTENCODING":"UTF8","PGSSLMODE":"disable",
                "PGPASSFILE":str(root/"nonexistent.pgpass")}
        def query(sql,timeout=30):
            return run("psql",["-X","-qAt","-w","-v","ON_ERROR_STOP=1",
                               "-h","127.0.0.1","-p",port,"-U",ROLE,
                               "-d","postgres"],data=sql,timeout=timeout,
                       extra_env=pg_env).stdout
        # Read-only handshake must match the randomly created cluster.
        # Authenticate with a fresh secret; do not run fixture SQL until
        # the actual data directory, endpoint, version and identity match.
        handshake=query("SELECT current_setting('data_directory'),"
                        "current_setting('server_version_num'),"
                        "inet_server_addr()::text,inet_server_port(),current_user;")
        if not handshake_matches(handshake,cluster,port):
            raise RuntimeError("FIXTURE_CLUSTER_IDENTITY_UNVERIFIED")
        # Each SQL invocation uses only the verified local endpoint and
        # ephemeral login, never environment-supplied connection settings.
        stage="FIXTURE"
        run_fixture_checks(query)
    except Exception as exc:
        failure=(stage,type(exc).__name__)
    finally:
        try:
            if pwfile.exists():
                pwfile.unlink()
            # After any attempted start, stop ONLY our new cluster.
            # If state cannot be verified, preserve the directory and fail.
            if start_attempted:
                status=run("pg_ctl",["-D",cluster,"status"],check=False,timeout=15)
                if status.returncode==0:
                    run("pg_ctl",["-D",cluster,"-w","-t","60","-m","fast","stop"],timeout=75)
                    status=run("pg_ctl",["-D",cluster,"status"],check=False,timeout=15)
                if status.returncode!=3 or (cluster/"postmaster.pid").exists():
                    raise RuntimeError("FIXTURE_STOP_UNVERIFIED")
            shutil.rmtree(root)
        except Exception as exc:
            failure=("CLEANUP",type(exc).__name__)
            print("POSTGRES_FIXTURE_CLEANUP_HELD: temporary directory retained")
    if failure:
        print("POSTGRES_NATIVE_FIXTURE_FAILED: "+":".join(failure))
        return 2
    print("POSTGRES_NATIVE_FIXTURE_ALL_PASS: synthetic only; production_writes=false")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
