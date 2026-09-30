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


def test_competitor_discovery_settings_accept_environment_overrides(tmp_path):
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHON_DOTENV_DISABLED"] = "true"
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    environment.update({
        "RITZZ_COMPETITORS_FILE": str(tmp_path / "competitors.json"),
        "RITZZ_COMPETITOR_LOOKBACK_DAYS": "30",
        "RITZZ_COMPETITOR_VIDEO_LIMIT": "12",
        "RITZZ_OUTLIER_MIN_SCORE": "4.5",
        "RITZZ_RITZZ_FIT_THRESHOLD": "72",
    })

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; import config.settings as settings; "
                "assert str(settings.RITZZ_COMPETITORS_FILE) == os.environ['RITZZ_COMPETITORS_FILE']; "
                "assert settings.RITZZ_COMPETITOR_LOOKBACK_DAYS == 30; "
                "assert settings.RITZZ_COMPETITOR_VIDEO_LIMIT == 12; "
                "assert settings.RITZZ_OUTLIER_MIN_SCORE == 4.5; "
                "assert settings.RITZZ_FIT_PASS_THRESHOLD == 72"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
