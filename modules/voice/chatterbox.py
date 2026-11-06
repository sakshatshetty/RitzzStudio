"""Chatterbox Turbo narration with forced character alignment."""

from __future__ import annotations

import gc
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

from modules.script.sentences import split_sentences
from modules.voice.alignment import (
    align_chunk_characters,
    build_alignment,
)
from modules.voice.models import (
    VoiceAlignment,
    VoiceGenerationRequest,
    VoiceGenerationResult,
)

_MAX_CHUNK_CHARACTERS = 320
_PAUSE_SECONDS = 0.12
_FLOAT32_RESAMPLING_MODULES: set[ModuleType] = set()


class ChatterboxTurboProvider:
    """Generate narration with a reference-conditioned Chatterbox Turbo voice."""

    def __init__(
        self,
        reference_audio_path: str | Path | None = None,
        *,
        conditionals_path: str | Path | None = None,
        model: Any | None = None,
        alignment_python: str | None = None,
    ) -> None:
        if (reference_audio_path is None) == (conditionals_path is None):
            raise ValueError(
                "Provide exactly one Chatterbox voice reference or conditionals file."
            )
        self.reference_audio_path = (
            Path(reference_audio_path).resolve()
            if reference_audio_path is not None
            else None
        )
        self.conditionals_path = (
            Path(conditionals_path).resolve()
            if conditionals_path is not None
            else None
        )
        if self.reference_audio_path is not None and not self.reference_audio_path.is_file():
            raise FileNotFoundError(
                f"Chatterbox voice reference was not found: {self.reference_audio_path}"
            )
        if self.conditionals_path is not None and not self.conditionals_path.is_file():
            raise FileNotFoundError(
                "Chatterbox voice conditionals were not found: "
                f"{self.conditionals_path}"
            )
        self.model = model
        self._conditionals_loaded = False
        self.alignment_python = (
            alignment_python
            or os.environ.get("RITZZ_WHISPERX_PYTHON")
            or sys.executable
        )
        self.device: str | None = None

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        import numpy as np

        model = self._load_model()
        if self.conditionals_path is not None:
            self._load_voice_conditionals(model)
        sample_rate = int(model.sr)
        if sample_rate <= 0:
            raise ValueError("Chatterbox Turbo returned an invalid sample rate.")

        output_directory = Path(request.output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / request.output_filename
        chunks = self._text_chunks(request.text)
        audio_parts: list[np.ndarray] = []
        alignment_chunks: list[dict[str, Any]] = []
        audio_cursor = 0
        pause_frames = round(sample_rate * _PAUSE_SECONDS)

        with tempfile.TemporaryDirectory(
            prefix="chatterbox-",
            dir=output_directory,
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            for index, (start, end, text) in enumerate(chunks):
                if self.reference_audio_path is not None:
                    generated = model.generate(
                        text,
                        audio_prompt_path=str(self.reference_audio_path),
                    )
                else:
                    generated = model.generate(text)
                audio = self._to_mono_float_audio(generated)
                if audio.size == 0:
                    raise ValueError(
                        f"Chatterbox Turbo returned empty audio for chunk {index + 1}."
                    )

                chunk_audio_path = temporary_path / f"chunk-{index:04d}.wav"
                import soundfile

                soundfile.write(
                    chunk_audio_path,
                    audio,
                    sample_rate,
                    subtype="PCM_16",
                )
                alignment_chunks.append(
                    {
                        "audio_file": str(chunk_audio_path),
                        "audio_offset_seconds": audio_cursor / sample_rate,
                        "duration_seconds": audio.size / sample_rate,
                        "end_character": end,
                        "start_character": start,
                        "text": text,
                    }
                )
                audio_parts.append(audio)
                audio_cursor += audio.size

                if index + 1 < len(chunks):
                    audio_parts.append(np.zeros(pause_frames, dtype=np.float32))
                    audio_cursor += pause_frames

            alignment_manifest = temporary_path / "alignment-input.json"
            alignment_result = temporary_path / "alignment-output.json"
            alignment_manifest.write_text(
                json.dumps({"chunks": alignment_chunks}, ensure_ascii=False),
                encoding="utf-8",
            )
            aligner_script = (
                Path(__file__).resolve().parents[2]
                / "scripts"
                / "align_voice_chunks.py"
            )
            subprocess.run(
                [
                    self.alignment_python,
                    str(aligner_script),
                    "--input",
                    str(alignment_manifest),
                    "--output",
                    str(alignment_result),
                ],
                check=True,
            )
            aligned_chunks = json.loads(
                alignment_result.read_text(encoding="utf-8")
            )["chunks"]
            alignment = self._build_alignment(
                request.text,
                alignment_chunks,
                aligned_chunks,
                audio_cursor / sample_rate,
            )
            wav_path = temporary_path / "narration.wav"
            import soundfile

            soundfile.write(
                wav_path,
                np.concatenate(audio_parts),
                sample_rate,
                subtype="PCM_16",
            )
            temporary_output = temporary_path / "narration.mp3"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(temporary_output),
                ],
                check=True,
            )
            temporary_output.replace(output_path)

        duration = audio_cursor / sample_rate
        return VoiceGenerationResult(
            voice_id=request.voice_id,
            model_id="chatterbox_turbo",
            status="completed",
            file_path=str(output_path),
            duration_seconds=duration,
            character_count=len(request.text),
            alignment=alignment,
        )

    def _load_voice_conditionals(self, model: Any) -> None:
        if self.conditionals_path is None or self._conditionals_loaded:
            return

        import chatterbox.tts_turbo as chatterbox_turbo

        device = self.device or getattr(model, "device", "cpu")
        model.conds = chatterbox_turbo.Conditionals.load(
            self.conditionals_path,
            map_location=device,
        ).to(device)
        self._conditionals_loaded = True

    def _load_model(self) -> Any:
        if self.model is not None:
            return self.model

        import chatterbox.tts_turbo as chatterbox_turbo
        import torch

        self._install_float32_resampling(chatterbox_turbo)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        model_class = self._memory_efficient_turbo_class(chatterbox_turbo)
        self.model = model_class.from_pretrained(device=self.device)
        return self.model

    @staticmethod
    def _install_float32_resampling(chatterbox_turbo: Any) -> None:
        import numpy as np

        librosa = chatterbox_turbo.librosa
        resample = librosa.resample
        if librosa in _FLOAT32_RESAMPLING_MODULES:
            return

        def resample_float32(*args: Any, **kwargs: Any) -> np.ndarray:
            return np.asarray(resample(*args, **kwargs), dtype=np.float32)

        librosa.resample = resample_float32
        _FLOAT32_RESAMPLING_MODULES.add(librosa)

    @staticmethod
    def _construct_turbo_model(
        model_class: Any,
        t3: Any,
        s3gen: Any,
        ve: Any,
        tokenizer: Any,
        device: str,
        conditionals: Any,
        model_label: str,
    ) -> Any:
        model = model_class(
            t3,
            s3gen,
            ve,
            tokenizer,
            device,
            conds=conditionals,
        )
        model.model_label = model_label
        return model

    @staticmethod
    def _memory_efficient_turbo_class(chatterbox_turbo: Any) -> Any:
        # Release each checkpoint before loading the next to cap CPU memory use.
        class MemoryEfficientTurbo(chatterbox_turbo.ChatterboxTurboTTS):
            @classmethod
            def from_local(cls, ckpt_dir: str | Path, device: str, nano: bool = False):
                ckpt_dir = Path(ckpt_dir)
                map_location = (
                    chatterbox_turbo.torch.device("cpu")
                    if device in {"cpu", "mps"}
                    else None
                )

                ve = chatterbox_turbo.VoiceEncoder()
                ve_state = chatterbox_turbo.load_file(ckpt_dir / "ve.safetensors")
                ve.load_state_dict(ve_state)
                del ve_state
                gc.collect()
                ve.to(device).eval()

                config = chatterbox_turbo.T3Config(text_tokens_dict_size=50276)
                config.llama_config_name = "GPT2_small" if nano else "GPT2_medium"
                config.speech_tokens_dict_size = 6563
                config.input_pos_emb = None
                config.speech_cond_prompt_len = 375
                config.use_perceiver_resampler = False
                config.emotion_adv = False
                t3 = chatterbox_turbo.T3(config)
                t3_filename = (
                    "t3_nano_v1.safetensors"
                    if nano
                    else "t3_turbo_v1.safetensors"
                )
                t3_state = chatterbox_turbo.load_file(ckpt_dir / t3_filename)
                if "model" in t3_state:
                    t3.load_state_dict(t3_state["model"][0])
                else:
                    t3.load_state_dict(t3_state)
                del t3_state
                gc.collect()
                del t3.tfmr.wte
                t3.to(device).eval()

                s3gen = chatterbox_turbo.S3Gen(meanflow=True)
                s3gen_state = chatterbox_turbo.load_file(
                    ckpt_dir / "s3gen_meanflow.safetensors"
                )
                s3gen.load_state_dict(s3gen_state, strict=True)
                del s3gen_state
                gc.collect()
                s3gen.to(device).eval()

                tokenizer = chatterbox_turbo.AutoTokenizer.from_pretrained(ckpt_dir)
                if tokenizer.pad_token is None:
                    tokenizer.pad_token = tokenizer.eos_token
                if len(tokenizer) != 50276:
                    print(f"WARNING: Tokenizer len {len(tokenizer)} != 50276")

                conditionals = None
                builtin_voice = ckpt_dir / "conds.pt"
                if builtin_voice.exists():
                    conditionals = chatterbox_turbo.Conditionals.load(
                        builtin_voice,
                        map_location=map_location,
                    ).to(device)

                return ChatterboxTurboProvider._construct_turbo_model(
                    cls,
                    t3,
                    s3gen,
                    ve,
                    tokenizer,
                    device,
                    conditionals,
                    "Nano" if nano else "Turbo",
                )

        return MemoryEfficientTurbo

    @staticmethod
    def _to_mono_float_audio(audio: Any) -> np.ndarray:
        import numpy as np

        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        samples = np.asarray(audio, dtype=np.float32).squeeze()
        if samples.ndim != 1:
            raise ValueError(
                "Chatterbox Turbo must return a single-channel audio waveform."
            )
        if not np.isfinite(samples).all():
            raise ValueError("Chatterbox Turbo returned non-finite audio samples.")
        return samples

    @staticmethod
    def _text_chunks(text: str) -> list[tuple[int, int, str]]:
        sentences = split_sentences(text)
        spans: list[tuple[int, int, str]] = []
        cursor = 0
        for sentence in sentences:
            start = text.find(sentence, cursor)
            if start < 0:
                raise ValueError(
                    "Could not map a narration sentence to the supplied text."
                )
            end = start + len(sentence)
            cursor = end
            if spans and end - spans[-1][0] <= _MAX_CHUNK_CHARACTERS:
                previous_start = spans[-1][0]
                spans[-1] = (previous_start, end, text[previous_start:end])
            elif end - start <= _MAX_CHUNK_CHARACTERS:
                spans.append((start, end, sentence))
            else:
                spans.extend(ChatterboxTurboProvider._split_long_sentence(
                    text,
                    start,
                    end,
                ))

        if not spans:
            raise ValueError("Narration has no synthesizable sentence chunks.")
        return spans

    @staticmethod
    def _split_long_sentence(
        text: str,
        start: int,
        end: int,
    ) -> list[tuple[int, int, str]]:
        words = list(re.finditer(r"\S+", text[start:end]))
        chunks: list[tuple[int, int, str]] = []
        chunk_start: int | None = None
        chunk_end = start
        for word in words:
            word_start = start + word.start()
            word_end = start + word.end()
            if word_end - word_start > _MAX_CHUNK_CHARACTERS:
                raise ValueError(
                    "A narration token exceeds the Chatterbox chunk size limit."
                )
            if (
                chunk_start is not None
                and word_end - chunk_start > _MAX_CHUNK_CHARACTERS
            ):
                chunks.append(
                    (chunk_start, chunk_end, text[chunk_start:chunk_end])
                )
                chunk_start = None
            if chunk_start is None:
                chunk_start = word_start
            chunk_end = word_end
        if chunk_start is not None:
            chunks.append((chunk_start, chunk_end, text[chunk_start:chunk_end]))
        return chunks

    @staticmethod
    def _build_alignment(
        text: str,
        input_chunks: list[dict[str, Any]],
        aligned_chunks: list[dict[str, Any]],
        duration_seconds: float,
    ) -> VoiceAlignment:
        return build_alignment(
            text,
            input_chunks,
            aligned_chunks,
            duration_seconds,
        )

    @staticmethod
    def _align_chunk_characters(
        text: str,
        aligned_characters: list[dict[str, Any]],
        audio_offset_seconds: float,
        chunk_duration_seconds: float,
    ) -> tuple[list[float], list[float]]:
        return align_chunk_characters(
            text,
            aligned_characters,
            audio_offset_seconds,
            chunk_duration_seconds,
        )
