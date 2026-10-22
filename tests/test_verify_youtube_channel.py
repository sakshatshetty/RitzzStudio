from scripts import verify_youtube_channel


def test_verifier_checks_and_reports_the_selected_channel(monkeypatch, capsys):
    monkeypatch.setenv("RITZZ_YOUTUBE_CHANNEL_TITLE", "Ritzz History")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", "client.json")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", "history-token.json")
    observed = {}

    class FakeProvider:
        def __init__(self, credentials_file, token_file):
            observed["credentials_file"] = credentials_file
            observed["token_file"] = token_file

        def verify_authenticated_channel(self, expected_title):
            observed["expected_title"] = expected_title
            return {
                "channel_id": "UCritzzhistory",
                "channel_title": expected_title,
            }

    monkeypatch.setattr(
        verify_youtube_channel,
        "YouTubeProvider",
        FakeProvider,
    )

    assert verify_youtube_channel.main() == 0
    assert observed["expected_title"] == "Ritzz History"
    assert capsys.readouterr().out == (
        "Selected YouTube channel verified: Ritzz History (UCritzzhistory).\n"
    )


def test_verifier_gives_channel_specific_reauthorization_steps(
    monkeypatch,
    capsys,
):
    from google.auth.exceptions import RefreshError

    monkeypatch.setenv("RITZZ_YOUTUBE_CHANNEL", "RitzzHistory")
    monkeypatch.setenv("RITZZ_YOUTUBE_CHANNEL_TITLE", "Ritzz History")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", "client.json")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", "history-token.json")

    class ExpiredTokenProvider:
        def __init__(self, credentials_file, token_file):
            pass

        def verify_authenticated_channel(self, expected_title):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(
        verify_youtube_channel,
        "YouTubeProvider",
        ExpiredTokenProvider,
    )

    assert verify_youtube_channel.main() == 1
    captured = capsys.readouterr()
    assert "invalid_grant" in captured.err
    assert "scripts/authorize_youtube.py" in captured.err
    assert "GOOGLE_TOKEN_RITZZ_HISTORY_B64" in captured.err
    assert "Selected YouTube channel verified" not in captured.out


def test_verifier_requires_expected_channel_title(monkeypatch):
    monkeypatch.delenv("RITZZ_YOUTUBE_CHANNEL_TITLE", raising=False)

    import pytest

    with pytest.raises(ValueError, match="RITZZ_YOUTUBE_CHANNEL_TITLE"):
        verify_youtube_channel.main()
