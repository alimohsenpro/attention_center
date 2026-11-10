#!/usr/bin/env python3
"""Generate the Attention Center tone set.

Every tone is synthesised here from sine partials and envelopes, so the audio files in
`attention_center/public/sounds/` carry no third-party rights and can be regenerated bit for
bit. Requires numpy. Run from the repository root:

    python scripts/sounds/generate_tones.py

Design rules: short (< 2 s), non-melodic, energy between about 300 Hz and 4 kHz so the tones
are audible on laptop speakers without being harsh, smooth attacks and releases (no clicks),
and matched loudness. `urgent` and `immediate` are slightly louder and brighter on purpose.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

SR = 32000
OUT_DIR = Path(__file__).resolve().parents[2] / "attention_center" / "public" / "sounds"


def seconds(duration: float) -> np.ndarray:
	return np.arange(int(SR * duration)) / SR


def envelope(n: int, attack: float, tau: float, release: float = 0.015) -> np.ndarray:
	t = np.arange(n) / SR
	rise = 0.5 - 0.5 * np.cos(np.pi * np.minimum(1.0, t / attack))
	env = rise * np.exp(-t / tau)
	tail = min(n, int(SR * release))
	env[-tail:] *= np.linspace(1.0, 0.0, tail) ** 2
	return env


def voice(
	freq: float, duration: float, partials: list[tuple[float, float, float]], attack: float = 0.004
) -> np.ndarray:
	"""Sum of sine partials: (frequency ratio, amplitude, decay time constant)."""
	t = seconds(duration)
	out = np.zeros_like(t)
	for ratio, amp, tau in partials:
		out += amp * np.sin(2 * np.pi * freq * ratio * t) * envelope(len(t), attack, tau)
	return out


def glide(f_start: float, f_end: float, duration: float, tau: float) -> np.ndarray:
	t = seconds(duration)
	freq = f_end + (f_start - f_end) * np.exp(-t / (duration / 4))
	phase = 2 * np.pi * np.cumsum(freq) / SR
	return np.sin(phase) * envelope(len(t), 0.003, tau)


def mix(parts: list[tuple[float, np.ndarray]], total: float) -> np.ndarray:
	out = np.zeros(int(SR * total))
	for offset, part in parts:
		start = int(SR * offset)
		end = min(len(out), start + len(part))
		out[start:end] += part[: end - start]
	return out


def lowpass(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
	spectrum = np.fft.rfft(x)
	freqs = np.fft.rfftfreq(len(x), 1 / SR)
	return np.fft.irfft(spectrum / np.sqrt(1 + (freqs / cutoff) ** (2 * order)), len(x))


def room(x: np.ndarray, amount: float = 1.0) -> np.ndarray:
	"""A few quiet early reflections: gives body without an audible echo."""
	out = np.concatenate([x, np.zeros(int(SR * 0.12))])
	dry = out.copy()
	for delay, gain in ((0.023, 0.16), (0.037, 0.11), (0.053, 0.07), (0.079, 0.04)):
		shift = int(SR * delay)
		out[shift:] += amount * gain * lowpass(dry, 2600)[: len(out) - shift]
	return out


def finish(x: np.ndarray, rms_db: float, peak_db: float = -3.0) -> np.ndarray:
	x = x - np.mean(x)
	active = x[np.abs(x) > 10 ** (-50 / 20) * np.max(np.abs(x))]
	x = x * (10 ** (rms_db / 20) / np.sqrt(np.mean(active**2)))
	peak = np.max(np.abs(x))
	limit = 10 ** (peak_db / 20)
	if peak > limit:
		x = x * (limit / peak)
	fade = int(SR * 0.012)
	x[-fade:] *= np.linspace(1.0, 0.0, fade)
	return x


BELL = [(1.0, 1.0, 0.32), (2.0, 0.28, 0.16), (3.01, 0.12, 0.09), (4.2, 0.05, 0.05)]
SOFT = [(1.0, 1.0, 0.10), (2.0, 0.18, 0.05)]
BRIGHT = [(1.0, 1.0, 0.085), (2.0, 0.35, 0.06), (3.0, 0.16, 0.04)]
WOOD = [(1.0, 1.0, 0.045), (2.76, 0.30, 0.02), (5.4, 0.10, 0.012)]


def tone_chime() -> np.ndarray:
	return room(mix([(0.0, voice(880, 1.0, BELL))], 1.05))


def tone_knock() -> np.ndarray:
	hit = voice(392, 0.22, WOOD, attack=0.002)
	return room(mix([(0.0, hit), (0.16, 0.85 * hit)], 0.45), 0.7)


def tone_pulse() -> np.ndarray:
	pip = voice(988, 0.16, SOFT)
	return room(mix([(0.0, pip), (0.17, pip)], 0.42), 0.6)


def tone_telegraph() -> np.ndarray:
	def key(duration: float) -> np.ndarray:
		t = seconds(duration + 0.03)
		gate = envelope(len(t), 0.003, 10.0, release=0.03)
		return (np.sin(2 * np.pi * 1320 * t) + 0.22 * np.sin(2 * np.pi * 2640 * t)) * gate

	return room(mix([(0.0, key(0.055)), (0.11, key(0.055)), (0.22, key(0.15))], 0.46), 0.5)


def tone_drop() -> np.ndarray:
	return room(mix([(0.0, glide(1250, 700, 0.30, 0.09))], 0.36), 0.8)


def tone_urgent() -> np.ndarray:
	pip = voice(1175, 0.14, BRIGHT, attack=0.002)
	return room(mix([(0.0, pip), (0.15, pip), (0.30, pip)], 0.50), 0.5)


def tone_immediate() -> np.ndarray:
	high = voice(1320, 0.13, BRIGHT, attack=0.002)
	low = voice(880, 0.13, BRIGHT, attack=0.002)
	pattern = [(i * 0.28, high) for i in range(3)] + [(0.14 + i * 0.28, low) for i in range(3)]
	return room(mix(pattern, 0.90), 0.4)


def tone_reminder() -> np.ndarray:
	note = voice(523.25, 0.75, [(1.0, 1.0, 0.26), (2.0, 0.16, 0.12), (3.0, 0.05, 0.07)], attack=0.008)
	return room(mix([(0.0, note), (0.34, 0.8 * note)], 1.15))


# id, role, English label, synthesiser, RMS level in dBFS
TONES = [
	("chime", "standard", "Chime", tone_chime, -20.0),
	("knock", "standard", "Knock", tone_knock, -20.0),
	("pulse", "standard", "Pulse", tone_pulse, -20.0),
	("telegraph", "standard", "Telegraph", tone_telegraph, -20.0),
	("drop", "standard", "Drop", tone_drop, -20.0),
	("urgent", "urgent", "Urgent", tone_urgent, -18.0),
	("immediate", "immediate", "Immediate", tone_immediate, -17.0),
	("reminder", "reminder", "Reminder", tone_reminder, -21.0),
]


def write_wav(path: Path, samples: np.ndarray) -> None:
	data = np.clip(np.round(samples * 32767), -32768, 32767).astype("<i2")
	with wave.open(str(path), "wb") as handle:
		handle.setnchannels(1)
		handle.setsampwidth(2)
		handle.setframerate(SR)
		handle.writeframes(data.tobytes())


def describe(samples: np.ndarray) -> dict:
	spectrum = np.abs(np.fft.rfft(samples))
	freqs = np.fft.rfftfreq(len(samples), 1 / SR)
	return {
		"seconds": round(len(samples) / SR, 2),
		"peak_db": round(20 * np.log10(np.max(np.abs(samples))), 1),
		"centroid_hz": int(np.sum(freqs * spectrum) / np.sum(spectrum)),
		"edge_jump": round(float(max(abs(samples[0]), abs(samples[-1]))), 5),
	}


def main() -> None:
	OUT_DIR.mkdir(parents=True, exist_ok=True)
	manifest = []
	for tone_id, role, label, synth, rms_db in TONES:
		samples = finish(lowpass(synth(), 6500), rms_db)
		info = describe(samples)
		assert info["seconds"] < 2.0, tone_id
		assert info["peak_db"] <= -2.9, tone_id
		assert info["edge_jump"] < 0.002, f"{tone_id} would click"
		write_wav(OUT_DIR / f"{tone_id}.wav", samples)
		manifest.append({"id": tone_id, "file": f"{tone_id}.wav", "role": role, "label": label})
		print(f"{tone_id:10s} {role:9s} {info}")
	(OUT_DIR / "tones.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
	main()
