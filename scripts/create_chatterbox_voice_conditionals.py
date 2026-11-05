"""Create a reusable Chatterbox Turbo voice-conditioning profile."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_REFERENCE_SAMPLE_RATE = 24_000
_REFERENCE_DURATION_SECONDS = 15
_MIN_REFERENCE_DURATION_SECONDS = 5


def create_voice_conditionals(source: Path, output: Path) -> dict[str, object]:
    if not source.is_file():
        raise FileNotFoundError(f"Voice source audio was not found: {source}")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite voice profile: {output}")

    import librosa
    import soundfile

    waveform, sample_rate = librosa.load(
        source,
        sr=_REFERENCE_SAMPLE_RATE,
        mono=True,
        duration=_REFERENCE_DURATION_SECONDS,
    )
    sample_rate = int(sample_rate)
    duration_seconds = len(waveform) / sample_rate
    if duration_seconds <= _MIN_REFERENCE_DURATION_SECONDS:
        raise ValueError(
            "The voice source must contain more than five seconds of audio."
        )

    import chatterbox.tts_turbo as chatterbox_turbo

    from modules.voice.chatterbox import ChatterboxTurboProvider

    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix="ritzz-voice-reference-") as reference_dir,
        tempfile.TemporaryDirectory(
            prefix="ritzz-voice-conditionals-",
            dir=output.parent,
        ) as profile_dir,
    ):
        reference_path = Path(reference_dir) / "reference.wav"
        soundfile.write(
            reference_path,
            waveform,
            sample_rate,
            subtype="PCM_16",
        )
        provider = ChatterboxTurboProvider(reference_audio_path=reference_path)
        model = provider._load_model()
        model.prepare_conditionals(
            str(reference_path),
            exaggeration=0.0,
            norm_loudness=True,
        )
        if model.conds is None:
            raise RuntimeError("Chatterbox did not produce voice conditionals.")

        temporary_profile = Path(profile_dir) / output.name
        model.conds.save(temporary_profile)
        if not temporary_profile.is_file() or temporary_profile.stat().st_size == 0:
            raise RuntimeError("Chatterbox produced an empty voice profile.")
        temporary_profile.replace(output)

    return {
        "profile_file": str(output),
        "profile_bytes": output.stat().st_size,
        "reference_duration_seconds": round(duration_seconds, 3),
        "reference_sample_rate": sample_rate,
        "model": model.model_label,
        "device": provider.device,
        "conditionals_format": chatterbox_turbo.Conditionals.__name__,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    result = create_voice_conditionals(
        arguments.source.resolve(),
        arguments.output.resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
