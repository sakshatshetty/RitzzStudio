"""Generate a local Chatterbox-Nano voice-cloning sample for evaluation."""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from safetensors import safe_open
import chatterbox.tts_turbo as chatterbox_turbo


DEFAULT_TEXT = (
    "By sunset, the ship had vanished from view. But the crew had left "
    "behind one clue: a small piece of painted wood. To understand why it "
    "mattered, we have to look closer at the voyage."
)


def load_file_pread(
    filename: str | Path,
    device: str = "cpu",
) -> dict[str, torch.Tensor]:
    with safe_open(
        filename,
        framework="pt",
        device=device,
        backend="pread",
    ) as tensors:
        return {key: tensors.get_tensor(key) for key in tensors.keys()}


def install_local_cpu_compatibility() -> None:
    chatterbox_turbo.load_file = load_file_pread
    original_resample = chatterbox_turbo.librosa.resample

    def resample_float32(*args: Any, **kwargs: Any) -> np.ndarray:
        return original_resample(*args, **kwargs).astype(np.float32, copy=False)

    chatterbox_turbo.librosa.resample = resample_float32


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-threads", type=int, default=8)
    args = parser.parse_args()

    reference = args.reference.resolve()
    output = args.output.resolve()
    if not reference.is_file():
        raise FileNotFoundError(f"Voice reference audio not found: {reference}")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing audio: {output}")
    if args.cpu_threads < 1:
        raise ValueError("--cpu-threads must be at least 1.")

    output.parent.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.cpu_threads)
    install_local_cpu_compatibility()

    load_started = time.perf_counter()
    model = chatterbox_turbo.ChatterboxTurboTTS.from_pretrained(
        device="cpu",
        nano=True,
    )
    model_load_seconds = time.perf_counter() - load_started

    generation_started = time.perf_counter()
    waveform = model.generate(DEFAULT_TEXT, audio_prompt_path=str(reference))
    generation_seconds = time.perf_counter() - generation_started

    if waveform.ndim != 2 or waveform.shape[0] != 1 or waveform.shape[-1] == 0:
        raise ValueError("Chatterbox returned an empty or unexpected audio shape.")

    sf.write(str(output), waveform.squeeze(0).numpy(), model.sr)
    audio_seconds = waveform.shape[-1] / model.sr
    print(
        json.dumps(
            {
                "model": "Chatterbox-Nano",
                "device": "cpu",
                "cpu_threads": args.cpu_threads,
                "voice_reference": str(reference),
                "sample_audio": str(output),
                "model_load_seconds": round(model_load_seconds, 2),
                "generation_seconds": round(generation_seconds, 2),
                "generated_audio_seconds": round(audio_seconds, 2),
                "generation_realtime_factor": round(
                    generation_seconds / audio_seconds, 3
                ),
                "character_alignment": "not returned by the model",
                "local_compatibility_workarounds": [
                    "SafeTensors pread backend for Windows",
                    "float32 audio resampling for the model tokenizer",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
