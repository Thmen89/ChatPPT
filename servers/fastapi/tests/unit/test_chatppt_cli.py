"""``chatppt backup | restore | reset-password | doctor`` on a throwaway data folder."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest

from chatppt import cli
from chatppt.settings import Settings, load_settings


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    for name in list(os.environ):
        if name.startswith("CHATPPT_") or name in {"DATABASE_URL", "LLM", "DISABLE_AUTH", "USER_CONFIG_PATH"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(data))
    monkeypatch.setenv("USER_CONFIG_PATH", str(data / "userConfig.json"))
    return data


def _settings(data: Path, **server: str) -> Settings:
    return Settings.model_validate({"server": {"data_dir": str(data), **server}})


def _make_db(path: Path, rows: int) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS decks (id INTEGER PRIMARY KEY, title TEXT)")
    con.executemany("INSERT INTO decks (title) VALUES (?)", [(f"deck {i}",) for i in range(rows)])
    con.commit()
    con.close()


def _count(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return int(con.execute("SELECT count(*) FROM decks").fetchone()[0])
    finally:
        con.close()


def test_sqlite_path_parses_driver_urls() -> None:
    assert cli.sqlite_path("sqlite:////data/fastapi.db") == Path("/data/fastapi.db")
    assert cli.sqlite_path("sqlite+aiosqlite:////data/x.db") == Path("/data/x.db")
    assert cli.sqlite_path("postgresql://u:p@db/chatppt") is None


def test_backup_snapshots_live_sqlite_and_skips_backups(data_dir: Path) -> None:
    _make_db(data_dir / "fastapi.db", 3)
    (data_dir / "images").mkdir()
    (data_dir / "images" / "a.png").write_bytes(b"png")
    (data_dir / "backups").mkdir()
    (data_dir / "backups" / "old.tar.gz").write_bytes(b"old")
    # A writer holds the database open in WAL mode while the backup runs.
    holder = sqlite3.connect(data_dir / "fastapi.db")
    holder.execute("INSERT INTO decks (title) VALUES ('uncommitted-safe')")
    holder.commit()

    archive = cli.backup(_settings(data_dir), None, out=io.StringIO())
    holder.close()

    assert archive is not None and archive.parent == data_dir / "backups"
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        manifest = json.load(tar.extractfile(cli.MANIFEST))  # type: ignore[arg-type]
    assert manifest["database"] == "fastapi.db"
    assert {"fastapi.db", "images/a.png", cli.MANIFEST} <= names
    assert not any(n.startswith("backups") or n.endswith(("-wal", "-shm")) for n in names)


def test_backup_then_restore_round_trip(data_dir: Path, tmp_path: Path) -> None:
    _make_db(data_dir / "fastapi.db", 5)
    (data_dir / "chatppt.toml").write_text('[defaults]\ntemplate = "general"\n')
    out = tmp_path / "b.tar.gz"
    cli.backup(_settings(data_dir), str(out), out=io.StringIO())

    fresh = tmp_path / "fresh"
    restored = cli.restore(_settings(fresh), out, force=False, out=io.StringIO())

    assert set(restored) == {"chatppt.toml", "fastapi.db"}
    assert _count(fresh / "fastapi.db") == 5
    assert not (fresh / cli.MANIFEST).exists()
    assert not any(p.name.startswith(".restore-") for p in fresh.iterdir())


def test_restore_refuses_to_overwrite_without_force_then_moves_aside(data_dir: Path, tmp_path: Path) -> None:
    _make_db(data_dir / "fastapi.db", 2)
    out = tmp_path / "b.tar.gz"
    cli.backup(_settings(data_dir), str(out), out=io.StringIO())
    _make_db(data_dir / "fastapi.db", 10)  # newer state, 12 rows
    (data_dir / "fastapi.db-wal").write_bytes(b"stale wal")

    with pytest.raises(cli.CLIError, match="--force"):
        cli.restore(_settings(data_dir), out, force=False, out=io.StringIO())

    cli.restore(_settings(data_dir), out, force=True, out=io.StringIO())
    aside = next(data_dir.glob("pre-restore-*"))
    # Checked before opening either database (SQLite tidies its WAL on close).
    assert (aside / "fastapi.db-wal").exists() and not (data_dir / "fastapi.db-wal").exists()
    assert _count(data_dir / "fastapi.db") == 2
    assert _count(aside / "fastapi.db") == 12


def test_restore_rejects_foreign_archive(data_dir: Path, tmp_path: Path) -> None:
    junk = tmp_path / "junk.tar.gz"
    with tarfile.open(junk, "w:gz") as tar:
        f = tmp_path / "x.txt"
        f.write_text("x")
        tar.add(f, arcname="x.txt")
    with pytest.raises(cli.CLIError, match="not a ChatPPT backup"):
        cli.restore(_settings(data_dir), junk, force=True, out=io.StringIO())


def test_reset_password_from_stdin(data_dir: Path) -> None:
    from utils import simple_auth

    simple_auth.setup_initial_credentials("alice", "old-secret")
    user = cli.reset_password(
        _settings(data_dir), None, password_stdin=True, stdin=io.StringIO("new-secret\n"), out=io.StringIO()
    )
    assert user == "alice"
    assert simple_auth.verify_credentials("alice", "new-secret")
    assert not simple_auth.verify_credentials("alice", "old-secret")


def test_reset_password_rejects_short_password(data_dir: Path) -> None:
    with pytest.raises(cli.CLIError, match="at least 6"):
        cli.reset_password(_settings(data_dir), "bob", password_stdin=True, stdin=io.StringIO("123\n"))


def test_reset_password_needs_a_terminal_or_stdin_flag(data_dir: Path) -> None:
    with pytest.raises(cli.CLIError, match="--password-stdin"):
        cli.reset_password(_settings(data_dir), "bob", password_stdin=False, stdin=io.StringIO(""))


def _by_what(checks: list[cli.Check]) -> dict[str, cli.Check]:
    return {c.what: c for c in checks}


def test_doctor_reports_missing_provider_and_export(data_dir: Path) -> None:
    checks = _by_what(cli.doctor(_settings(data_dir), environ={"USER_CONFIG_PATH": str(data_dir / "userConfig.json")}))
    assert checks["data folder"].status == "ok"
    assert checks["LLM provider"].status == "warn"
    assert checks["export (PPTX/PDF)"].status == "fail"
    assert (
        "PUPPETEER_EXECUTABLE_PATH" in checks["export (PPTX/PDF)"].detail
        or "runtime" in checks["export (PPTX/PDF)"].detail
    )
    out = io.StringIO()
    assert cli.print_checks(list(checks.values()), out=out) == 1
    assert "problem(s) found" in out.getvalue()


def test_doctor_names_the_missing_key_for_a_selected_provider(data_dir: Path) -> None:
    env = {"USER_CONFIG_PATH": str(data_dir / "userConfig.json"), "CHATPPT_LLM__PROVIDER": "openai"}
    settings = load_settings(environ={**env, "APP_DATA_DIRECTORY": str(data_dir)})
    check = _by_what(cli.doctor(settings, environ=env))["LLM provider"]
    assert check.status == "fail"
    assert "llm.providers.openai.api_key" in check.detail


def test_doctor_reads_provider_saved_from_the_settings_screen(data_dir: Path) -> None:
    (data_dir / "userConfig.json").write_text(json.dumps({"LLM": "anthropic", "ANTHROPIC_API_KEY": "sk-ant-x"}))
    env = {"USER_CONFIG_PATH": str(data_dir / "userConfig.json")}
    check = _by_what(cli.doctor(_settings(data_dir), environ=env))["LLM provider"]
    assert check.status == "ok"
    assert "Anthropic" in check.detail


def test_doctor_flags_unwritable_and_damaged(data_dir: Path) -> None:
    missing = data_dir / "nope"
    assert _by_what(cli.doctor(_settings(missing), environ={}))["data folder"].status == "fail"
    (data_dir / "fastapi.db").write_bytes(b"not a database at all" * 100)
    assert _by_what(cli.doctor(_settings(data_dir), environ={}))["database"].status == "fail"


def test_main_dispatches_and_exits_nonzero_on_user_error(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["backup", "-o", str(data_dir.parent / "x.tar.gz")]) == 0
    with pytest.raises(SystemExit) as exc:
        cli.main(["restore", str(data_dir.parent / "missing.tar.gz")])
    assert exc.value.code == 1
    assert "does not exist" in capsys.readouterr().err


def test_drop_root_is_a_no_op_outside_the_image(monkeypatch: pytest.MonkeyPatch) -> None:
    assert cli.drop_root(user="no-such-user-chatppt-test") is False
    monkeypatch.setenv("CHATPPT_RUN_AS_ROOT", "true")
    assert cli.drop_root() is False
