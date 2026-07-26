# tests/test_ims_cli.py
#
# Unit-level coverage for scripts/ims.py — the parts that don't require a
# real docker compose stack (subprocess/urllib are mocked). End-to-end
# behavior (setup/start/stop/status/backup/restore against the real
# stack) was verified manually, same convention as scripts/backup.sh /
# scripts/restore.sh (test_scripts/test_sc.sh-style scripts aren't
# CI-gated in this repo either).

import urllib.error
from unittest.mock import MagicMock, patch

from scripts import ims


def test_main_dispatches_backup_to_cmd_backup(monkeypatch):
    """Exercises main()'s real argparse wiring, not a reimplementation."""
    monkeypatch.setattr(ims.sys, "argv", ["ims", "backup", "some-destination"])

    with patch.object(ims, "cmd_backup", return_value=0) as mock_cmd:
        try:
            ims.main()
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("main() should always raise SystemExit")

    called_args = mock_cmd.call_args[0][0]
    assert called_args.command == "backup"
    assert called_args.destination == "some-destination"


def test_main_requires_a_subcommand(monkeypatch):
    monkeypatch.setattr(ims.sys, "argv", ["ims"])

    try:
        ims.main()
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("main() should exit non-zero with no subcommand")


def test_cmd_backup_returns_1_when_script_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ims, "PROJECT_ROOT", tmp_path)
    args = MagicMock(destination=str(tmp_path / "dest"))

    result = ims.cmd_backup(args)

    assert result == 1


def test_cmd_restore_returns_1_when_script_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ims, "PROJECT_ROOT", tmp_path)
    args = MagicMock(archive=str(tmp_path / "some.tar.gz"))

    result = ims.cmd_restore(args)

    assert result == 1


def test_cmd_backup_invokes_script_with_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(ims, "PROJECT_ROOT", tmp_path)
    script = tmp_path / "scripts" / "backup.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n")

    with patch.object(ims.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        args = MagicMock(destination="/backups")
        result = ims.cmd_backup(args)

    assert result == 0
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd == [str(script), "/backups"]


def test_cmd_restore_invokes_script_with_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(ims, "PROJECT_ROOT", tmp_path)
    script = tmp_path / "scripts" / "restore.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n")

    with patch.object(ims.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        args = MagicMock(archive="/backups/x.tar.gz")
        result = ims.cmd_restore(args)

    assert result == 0
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd == [str(script), "/backups/x.tar.gz"]


def test_wait_for_health_true_when_reachable():
    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.__enter__.return_value = fake_response

    with patch.object(ims.urllib.request, "urlopen", return_value=fake_response):
        assert ims._wait_for_health(timeout=5) is True


def test_wait_for_health_false_on_timeout():
    with patch.object(
        ims.urllib.request, "urlopen", side_effect=urllib.error.URLError("connection refused")
    ):
        assert ims._wait_for_health(timeout=1) is False
