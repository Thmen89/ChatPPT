"""``chatppt``: backup, restore, reset-password and doctor for one ChatPPT data folder.

In the container::

    docker exec chatppt chatppt doctor
    docker exec chatppt chatppt backup                 # -> /data/backups/chatppt-<time>.tar.gz
    docker exec chatppt chatppt backup -o - > deck-backup.tar.gz
    docker exec -it chatppt chatppt reset-password
    docker run --rm -v ./chatppt:/data ghcr.io/thmen89/chatppt chatppt restore /data/backups/<file>

The data folder is ``server.data_dir`` (``/data`` in the container). Every command works
on that folder only and never talks to the network.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Iterator, MutableMapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Literal

from chatppt.settings import Settings, apply_to_environ, load_settings

MANIFEST = "chatppt-backup.json"
BACKUP_DIR = "backups"
USER_CONFIG = "userConfig.json"
DEFAULT_DB = "fastapi.db"
# Never archived or replaced: the backups themselves, restore scratch space, fs metadata.
SKIP_TOP_LEVEL = frozenset({BACKUP_DIR, "lost+found"})
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")


class CLIError(Exception):
    """A problem the user can fix; printed without a traceback, exit code 1."""


# --------------------------------------------------------------------------- environment


def _settings(environ: MutableMapping[str, str] | None = None) -> Settings:
    """Load settings and export them the way the server does, so upstream helpers
    (database URL, auth, user config) resolve the same paths here."""
    env: MutableMapping[str, str] = os.environ if environ is None else environ
    settings = load_settings(environ=env)
    env.setdefault("APP_DATA_DIRECTORY", str(settings.data_dir))
    env.setdefault("USER_CONFIG_PATH", str(settings.data_dir / USER_CONFIG))
    apply_to_environ(settings, env)
    return settings


def _database_url(settings: Settings) -> str:
    return settings.server.database_url or f"sqlite:///{settings.data_dir / DEFAULT_DB}"


def sqlite_path(database_url: str) -> Path | None:
    """The file behind a SQLite URL (any driver suffix), or None for other databases."""
    scheme, sep, rest = database_url.partition(":///")
    if not sep or not scheme.split("+")[0] == "sqlite":
        return None
    return Path("/" + rest.lstrip("/")) if rest.startswith("/") else Path(rest)


# --------------------------------------------------------------------------- backup


def _snapshot_sqlite(source: Path, target: Path) -> None:
    """Consistent copy of a live SQLite database (the online backup API, safe while the
    server writes to it)."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _relative(path: Path, root: Path) -> str | None:
    """``path`` relative to ``root`` (both resolved), or None when it lies outside."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _open_archive(target: Path | None) -> tarfile.TarFile:
    if target is None:
        return tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz")
    return tarfile.open(target, mode="w:gz")


def backup(settings: Settings, output: str | None, out: IO[str] = sys.stderr) -> Path | None:
    """Write ``<data>/backups/chatppt-<time>.tar.gz`` (or ``output``; ``-`` is stdout).

    Returns the archive path, or None when written to stdout.
    """
    data_dir = settings.data_dir
    if not data_dir.is_dir():
        raise CLIError(f"data folder {data_dir} does not exist; nothing to back up")

    db_file = sqlite_path(_database_url(settings))
    db_name = _relative(db_file, data_dir) if db_file is not None else None
    if db_file is None:
        print(
            "note: the database is not SQLite (server.database_url); back it up with its own tools "
            "(e.g. pg_dump). Files are backed up below.",
            file=out,
        )
    elif db_name is None:
        print(f"note: the database {db_file} is outside {data_dir}; back it up separately.", file=out)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = None if output == "-" else Path(output) if output else data_dir / BACKUP_DIR / f"chatppt-{stamp}.tar.gz"
    skip: set[str] = set()
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if (name := _relative(target, data_dir)) is not None:
            skip.add(name)

    with tempfile.TemporaryDirectory(prefix="chatppt-backup-") as tmp:
        manifest: dict[str, Any] = {"format": 1, "created": stamp, "database": None}
        snapshot = None
        if db_file is not None and db_name is not None and db_file.is_file():
            snapshot = Path(tmp) / db_file.name
            _snapshot_sqlite(db_file, snapshot)
            manifest["database"] = db_name
            # The live file and its journal are replaced by the consistent snapshot.
            skip.update(db_name + suffix for suffix in ("", *SQLITE_SIDECARS))
        manifest_file = Path(tmp) / MANIFEST
        manifest_file.write_text(json.dumps(manifest, indent=2))

        def exclude(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
            return None if info.name in skip else info

        with _open_archive(target) as tar:
            tar.add(manifest_file, arcname=MANIFEST)
            if snapshot is not None:
                tar.add(snapshot, arcname=db_name)
            for entry in sorted(data_dir.iterdir()):
                if entry.name in SKIP_TOP_LEVEL or entry.name.startswith(".restore-"):
                    continue
                tar.add(entry, arcname=entry.name, filter=exclude)
    if target is not None:
        print(f"backup written to {target}", file=out)
    return target


# --------------------------------------------------------------------------- restore


def restore(settings: Settings, archive: Path, force: bool, out: IO[str] = sys.stderr) -> list[str]:
    """Unpack a backup into the data folder. Returns the restored top-level names.

    With ``force``, whatever is in the way is moved to ``<data>/pre-restore-<time>/``
    first (nothing is deleted). Stop the server before restoring.
    """
    data_dir = settings.data_dir
    if not archive.is_file():
        raise CLIError(f"{archive} does not exist")
    data_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive, "r:*") as tar:
        names = tar.getnames()
        if MANIFEST not in names:
            raise CLIError(f"{archive} is not a ChatPPT backup (no {MANIFEST} inside)")
        top_level = sorted({name.split("/", 1)[0] for name in names} - {MANIFEST})
        existing = [name for name in top_level if (data_dir / name).exists()]
        # A leftover WAL/journal next to a restored database would be replayed into it.
        stale = [n + s for n in top_level for s in SQLITE_SIDECARS if (data_dir / (n + s)).exists()]
        if existing and not force:
            raise CLIError(
                f"{data_dir} already has {', '.join(existing)}. Stop ChatPPT, then rerun with --force; "
                "the current files are moved aside, not deleted."
            )
        stamp = time.strftime("%Y%m%d-%H%M%S")
        staging = data_dir / f".restore-{stamp}"
        tar.extractall(staging, filter="data")

    if existing or stale:
        aside = data_dir / f"pre-restore-{stamp}"
        aside.mkdir()
        for name in existing + stale:
            shutil.move(str(data_dir / name), str(aside / name))
        print(f"moved current {', '.join(existing + stale)} to {aside}", file=out)
    for name in top_level:
        shutil.move(str(staging / name), str(data_dir / name))
    shutil.rmtree(staging)
    print(f"restored {len(top_level)} item(s) into {data_dir}", file=out)
    return top_level


# --------------------------------------------------------------------------- reset-password


def _read_new_password(from_stdin: bool, stdin: IO[str]) -> str:
    if from_stdin:
        return stdin.readline().rstrip("\r\n")
    if not stdin.isatty():
        raise CLIError("no terminal to prompt on; pipe the password in with --password-stdin")
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat it: "):
        raise CLIError("the passwords do not match")
    return first


def _reset_target(username: str | None) -> tuple[str, bool]:
    """Which user to reset: the one named, else the only admin (or ``admin`` on an install
    without users). Returns (username, whether that user exists)."""
    from chatppt.auth import store

    if username:
        return store.normalize_username(username), store.get_user_by_username(username) is not None
    admins = [u for u in store.list_users() if u.is_admin]
    if len(admins) == 1:
        return admins[0].username, True
    if not admins and store.count_users() == 0:
        return "admin", False
    names = ", ".join(u.username for u in admins) or "none"
    raise CLIError(f"say which user with --username (admins: {names})")


def reset_password(
    settings: Settings,
    username: str | None,
    password_stdin: bool,
    stdin: IO[str] = sys.stdin,
    out: IO[str] = sys.stderr,
) -> str:
    """Set a new password for ``username`` (default: the only admin). A user that does not
    exist yet is created as an admin, which is the way back in when nobody can sign in.

    Signs that user out everywhere and re-enables them. Returns the username.
    """
    from chatppt.auth import store

    user, exists = _reset_target(username)
    password = _read_new_password(password_stdin, stdin)
    try:
        if exists:
            found = store.get_user_by_username(user)
            assert found is not None
            store.update_user(found.id, password=password, is_active=True)
        else:
            store.create_user(user, password, is_admin=True, validate=False)
    except ValueError as exc:
        raise CLIError(str(exc)) from None
    action = "reset" if exists else "set for the new admin"
    print(f"password for '{user}' {action}; that user's sessions are signed out.", file=out)
    if settings.auth.disabled:
        print("note: login is disabled (auth.disabled), so the password is not asked for.", file=out)
    return user


# --------------------------------------------------------------------------- doctor


@dataclass(frozen=True)
class Check:
    status: Literal["ok", "warn", "fail"]
    what: str
    detail: str


def _check_config(settings: Settings) -> Check:
    source = settings.source_path or "no chatppt.toml (environment variables and defaults only)"
    return Check("ok", "config", source)


def _check_data_dir(settings: Settings) -> Check:
    data_dir = settings.data_dir
    if not data_dir.is_dir():
        return Check("fail", "data folder", f"{data_dir} does not exist; mount a volume there (-v ./chatppt:/data)")
    try:
        with tempfile.NamedTemporaryFile(dir=data_dir, prefix=".doctor-"):
            pass
    except OSError as exc:
        return Check("fail", "data folder", f"{data_dir} is not writable ({exc.strerror}); fix its owner or mode")
    return Check("ok", "data folder", f"{data_dir} is writable")


def _check_database(settings: Settings) -> Check:
    url = _database_url(settings)
    db_file = sqlite_path(url)
    if db_file is None:
        scheme = url.split(":", 1)[0]
        return Check("ok", "database", f"{scheme} (server.database_url); not checked from here")
    if not db_file.exists():
        return Check("ok", "database", f"SQLite at {db_file} (created on first start)")
    try:
        con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            result = con.execute("PRAGMA quick_check").fetchone()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return Check("fail", "database", f"SQLite at {db_file} cannot be read: {exc}")
    if not result or result[0] != "ok":
        return Check("fail", "database", f"SQLite at {db_file} is damaged ({result}); restore a backup")
    return Check("ok", "database", f"SQLite at {db_file}")


def _ui_configured_settings(settings: Settings, environ: dict[str, str]) -> Settings:
    """Settings as the server sees them, including keys saved from the settings screen
    (``userConfig.json`` uses the legacy variable names)."""
    path = Path(environ.get("USER_CONFIG_PATH") or settings.data_dir / USER_CONFIG)
    try:
        saved = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict) or not saved:
        return settings
    merged = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in saved.items() if v not in (None, "")}
    merged.update(environ)
    return load_settings(environ=merged)


def _check_llm(settings: Settings) -> Check:
    from chatppt.providers.registry import get_llm_provider

    provider = settings.llm.provider
    if not provider:
        return Check(
            "warn",
            "LLM provider",
            "none configured; pick one in the settings screen or set CHATPPT_LLM__PROVIDER "
            "and its key (see docs/config-reference.md)",
        )
    try:
        spec = get_llm_provider(provider)
    except KeyError as exc:
        return Check("fail", "LLM provider", str(exc).strip("'\""))
    creds = settings.llm.providers.get(provider)
    missing = [need for need in spec.needs if not (creds and getattr(creds, need, None))]
    if missing:
        keys = ", ".join(f"llm.providers.{provider}.{need}" for need in missing)
        return Check("fail", "LLM provider", f"{spec.label} is selected but {keys} is not set")
    model = settings.llm.model or (creds.model if creds else None) or spec.default_model or "?"
    return Check("ok", "LLM provider", f"{spec.label}, model {model}")


def _check_images(settings: Settings) -> Check:
    if not settings.features.images or not settings.images.provider:
        return Check("ok", "images", "no image provider; slides use placeholder images")
    return Check("ok", "images", f"provider {settings.images.provider}")


def _check_export(environ: dict[str, str]) -> Check:
    chromium = environ.get("CHATPPT_CHROMIUM_PATH") or environ.get("PUPPETEER_EXECUTABLE_PATH") or ""
    if (environ.get("CHATPPT_EXPORT_ENGINE") or "").strip().lower() != "bundle":
        if not chromium or not os.access(chromium, os.X_OK):
            return Check(
                "fail", "export (PPTX/PDF)", f"no Chromium at PUPPETEER_EXECUTABLE_PATH ({chromium or 'unset'})"
            )
        return Check("ok", "export (PPTX/PDF)", f"built-in exporter, Chromium {chromium}")
    try:
        from services.export_task_service import ExportTaskService

        service = ExportTaskService()
        entrypoint = Path(service.entrypoint_path)
        converter = Path(service.converter_path)
    except Exception as exc:  # the export path is being rebuilt; report, don't crash
        return Check("warn", "export (PPTX/PDF)", f"could not locate the export runtime: {exc}")
    if not entrypoint.is_file():
        return Check("fail", "export (PPTX/PDF)", f"runtime missing at {entrypoint}; this image cannot export")
    if not os.access(converter, os.X_OK):
        return Check("fail", "export (PPTX/PDF)", f"converter missing or not executable at {converter}")
    if not chromium or not os.access(chromium, os.X_OK):
        return Check("fail", "export (PPTX/PDF)", f"no Chromium at PUPPETEER_EXECUTABLE_PATH ({chromium or 'unset'})")
    return Check("ok", "export (PPTX/PDF)", f"runtime {entrypoint.parent}, Chromium {chromium}")


def _check_optional(settings: Settings) -> list[Check]:
    checks = []
    if shutil.which("soffice") or shutil.which("libreoffice"):
        checks.append(Check("ok", "LibreOffice", "PPTX/DOCX import available"))
    else:
        checks.append(
            Check(
                "warn",
                "LibreOffice",
                "not installed (slim image): importing PPTX templates and DOCX/PPTX documents needs the full image",
            )
        )
    if settings.features.ocr and not shutil.which("tesseract"):
        checks.append(Check("warn", "OCR", "features.ocr is on but Tesseract is not installed (full image only)"))
    if settings.features.memory:
        try:
            import spacy  # type: ignore[import-not-found, unused-ignore]  # noqa: F401
        except ImportError:
            checks.append(
                Check("warn", "memory", "features.memory is on but mem0/spaCy are not installed (full image only)")
            )
        else:
            checks.append(Check("ok", "memory", "mem0 available"))
    return checks


def _check_auth(settings: Settings) -> Check:
    if settings.auth.disabled:
        return Check("warn", "login", "disabled (auth.disabled): anyone who can reach the port can use ChatPPT")
    from chatppt.auth import store

    try:
        users = store.list_users()
    except Exception as exc:  # database missing or unreadable: the database check says why
        return Check("warn", "login", f"could not read users: {exc}")
    if users:
        admins = [u.username for u in users if u.is_admin and u.is_active]
        return Check(
            "ok",
            "login",
            f"{len(users)} user(s), admin(s): {', '.join(admins) or 'none'} (forgot a password? chatppt reset-password)",
        )
    return Check("ok", "login", "not set up yet; the first visit asks for a username and password")


def doctor(settings: Settings, environ: dict[str, str] | None = None) -> list[Check]:
    env = dict(os.environ if environ is None else environ)
    effective = _ui_configured_settings(settings, env)
    checks = [_check_config(settings), _check_data_dir(settings), _check_database(settings)]
    checks += [_check_llm(effective), _check_images(effective), _check_export(env)]
    checks += _check_optional(effective)
    checks.append(_check_auth(effective))
    return checks


def print_checks(checks: Sequence[Check], out: IO[str] = sys.stdout) -> int:
    width = max(len(c.what) for c in checks)
    for check in checks:
        print(f"{check.status.upper():<4}  {check.what:<{width}}  {check.detail}", file=out)
    failed = [c for c in checks if c.status == "fail"]
    print(f"\n{len(failed)} problem(s) found." if failed else "\nAll good.", file=out)
    return 1 if failed else 0


# --------------------------------------------------------------------------- entry point


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except CLIError as exc:
        print(f"chatppt: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chatppt", description="Maintain a ChatPPT data folder.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backup", help="archive the data folder (database included, consistent while running)")
    p.add_argument(
        "-o", "--output", help="archive path, or - for stdout (default <data>/backups/chatppt-<time>.tar.gz)"
    )

    p = sub.add_parser("restore", help="unpack a backup into the data folder (stop ChatPPT first)")
    p.add_argument("archive", type=Path)
    p.add_argument("--force", action="store_true", help="move current files aside and restore over them")

    p = sub.add_parser("reset-password", help="set a user's password (signs that user out)")
    p.add_argument("--username", help="login name (default: the only admin; a new name is created as an admin)")
    p.add_argument("--password-stdin", action="store_true", help="read the password from stdin instead of prompting")

    sub.add_parser("doctor", help="check the configuration and say what is wrong in plain words")
    return parser


APP_USER = "chatppt"


def drop_root(user: str = APP_USER) -> bool:
    """In the container, ``docker exec`` runs as root; work as the app user instead so files
    written to the data folder (backups, restored data) stay owned by the server.
    Returns True when privileges were dropped."""
    if os.name != "posix" or os.geteuid() != 0 or os.environ.get("CHATPPT_RUN_AS_ROOT") == "true":
        return False
    import pwd

    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        return False  # not the image: leave the user alone
    os.initgroups(user, entry.pw_gid)
    os.setgid(entry.pw_gid)
    os.setuid(entry.pw_uid)
    os.environ["HOME"] = entry.pw_dir
    return True


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    drop_root()
    settings = _settings()
    commands: dict[str, Callable[[], object]] = {
        "backup": lambda: backup(settings, args.output),
        "restore": lambda: restore(settings, args.archive, args.force),
        "reset-password": lambda: reset_password(settings, args.username, args.password_stdin),
    }
    if args.command == "doctor":
        return print_checks(doctor(settings))
    with _errors():
        commands[args.command]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
