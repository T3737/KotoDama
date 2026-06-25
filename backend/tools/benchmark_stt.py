"""Benchmark pre-installed local faster-whisper models without network access."""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from time import perf_counter


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.speech.stt_service import (  # noqa: E402
    STTError,
    STTUnavailableError,
    create_stt_service,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark local English STT models using pre-installed files only."
    )
    model_group = parser.add_mutually_exclusive_group()
    model_group.add_argument("--model", help="One model, for example tiny.en")
    model_group.add_argument(
        "--models", nargs="+", help="Models to compare, for example tiny.en base.en"
    )
    parser.add_argument(
        "--manifest", type=Path, help="Optional JSON manifest containing samples"
    )
    parser.add_argument("files", nargs="*", help="WAV paths or glob patterns")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    file_patterns = list(args.files)
    if args.models:
        models = []
        for value in args.models:
            if models and _looks_like_audio_pattern(value):
                file_patterns.append(value)
            else:
                models.append(value)
    else:
        models = [args.model or "tiny.en"]
    samples = load_samples(file_patterns, args.manifest)
    if not samples:
        print("No WAV samples were supplied.", file=sys.stderr)
        return 2

    failures = 0
    for model_name in models:
        print(f"\nModel: {model_name}")
        service = create_stt_service("local", model_name)
        load_started = perf_counter()
        try:
            service.prepare()
        except STTUnavailableError as exc:
            print(f"  unavailable: {exc}")
            failures += 1
            continue
        load_elapsed_ms = (perf_counter() - load_started) * 1000
        readiness = service.readiness()
        print(
            "  model_load_ms: "
            f"{readiness.get('load_ms') if readiness.get('load_ms') is not None else load_elapsed_ms:.1f}"
        )

        for audio_path, expected in samples:
            try:
                result = service.transcribe_detailed(audio_path)
            except STTError as exc:
                print(f"  {audio_path}: error [{exc.code}] {exc}")
                failures += 1
                continue
            audio_seconds = (result.audio_duration_ms or 0) / 1000
            transcription_seconds = result.transcription_ms / 1000
            real_time_factor = (
                transcription_seconds / audio_seconds if audio_seconds > 0 else None
            )
            print(f"  file: {audio_path}")
            print(f"    audio_duration_ms: {result.audio_duration_ms}")
            print(f"    transcription_ms: {result.transcription_ms}")
            print(
                "    real_time_factor: "
                + (f"{real_time_factor:.3f}" if real_time_factor is not None else "unknown")
            )
            print(f"    transcript: {result.transcript}")
            if expected is not None:
                comparison = compare_text(expected, result.transcript)
                print(f"    expected: {expected}")
                print(f"    exact_match: {comparison['exact_match']}")
                print(f"    word_differences: {comparison['word_differences']}")
                print(f"    word_error_rate: {comparison['word_error_rate']:.3f}")
    return 1 if failures else 0


def load_samples(
    patterns: list[str], manifest_path: Path | None
) -> list[tuple[Path, str | None]]:
    samples: dict[Path, str | None] = {}
    if manifest_path is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get("samples", []):
            path = (manifest_path.parent / item["file"]).resolve()
            samples[path] = item.get("expected")
    for pattern in patterns:
        matches = glob.glob(pattern)
        if not matches and Path(pattern).is_file():
            matches = [pattern]
        for match in matches:
            samples.setdefault(Path(match).resolve(), None)
    return sorted(samples.items(), key=lambda item: str(item[0]))


def compare_text(expected: str, actual: str) -> dict[str, bool | int | float]:
    expected_words = normalize(expected).split()
    actual_words = normalize(actual).split()
    differences = edit_distance(expected_words, actual_words)
    return {
        "exact_match": expected_words == actual_words,
        "word_differences": differences,
        "word_error_rate": differences / max(1, len(expected_words)),
    }


def normalize(text: str) -> str:
    return " ".join(
        "".join(character for character in word.lower() if character.isalnum())
        for word in text.split()
    ).strip()


def _looks_like_audio_pattern(value: str) -> bool:
    lowered = value.lower()
    return lowered.endswith(".wav") or "*" in value or "?" in value or Path(value).exists()


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_word in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_word in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_word != right_word),
                )
            )
        previous = current
    return previous[-1]


if __name__ == "__main__":
    raise SystemExit(main())
