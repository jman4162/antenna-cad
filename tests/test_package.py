"""Package-level smoke tests."""

import antenna_cad


def test_version_is_set():
    assert isinstance(antenna_cad.__version__, str)
    assert antenna_cad.__version__


def test_import_is_lightweight():
    """Importing antenna_cad must not drag heavy backends in."""
    import subprocess
    import sys

    code = (
        "import sys; import antenna_cad; "
        "heavy = [m for m in ('matplotlib', 'skrf', 'CSXCAD', 'openEMS') if m in sys.modules]; "
        "sys.exit(1 if heavy else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
