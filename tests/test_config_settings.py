import os
import subprocess
import sys

from config.settings import PROJECT_ROOT


def test_settings_import_does_not_require_openai_key_for_offline_tools(tmp_path):
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHON_DOTENV_DISABLED"] = "true"
    environment["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import config.settings as settings; "
             "assert settings.OPENAI_API_KEY is None"),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
