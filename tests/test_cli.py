import pytest

from handshortcut import __version__, paths
from handshortcut.cli import build_parser, main


def test_paths_command(capsys, tmp_path):
    assert main(["--data-dir", str(tmp_path), "paths"]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path) in out and "journaux" in out
    assert (paths.examples_dir() / "actions.example.json").exists()


def test_version(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--version"])
    assert __version__ in capsys.readouterr().out


def test_stop_when_not_running(capsys):
    assert main(["--port", "59999", "stop"]) == 0
    assert "pas lance" in capsys.readouterr().out
