import subprocess
import sys

import pytest

import cinemate
from cinemate.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"cinemate {cinemate.__version__}"


def test_no_args_succeeds():
    assert main([]) == 0


def test_module_entrypoint():
    result = subprocess.run(
        [sys.executable, "-m", "cinemate", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert cinemate.__version__ in result.stdout
