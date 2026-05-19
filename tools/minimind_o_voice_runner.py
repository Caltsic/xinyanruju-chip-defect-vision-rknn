from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import struct
import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace


def _write_stream_text(path: Path | None, text: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _set_runtime_env(threads: int) -> None:
    thread_count = str(max(1, threads))
    os.environ.setdefault("PYTORCH_JIT", "0")
    os.environ.setdefault("OMP_NUM_THREADS", thread_count)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", thread_count)
    os.environ.setdefault("MKL_NUM_THREADS", thread_count)
    os.environ.setdefault("NUMEXPR_NUM_THREADS", thread_count)
    os.environ.setdefault("HF_HOME", "/mnt/eaget/cache/huggingface")
    os.environ.setdefault("MODELSCOPE_CACHE", "/mnt/eaget/cache/modelscope")


def _disable_torch_jit_script() -> None:
    try:
        import torch
    except Exception:
        return

    def _passthrough(fn=None, *args, **kwargs):
        if fn is None:
            return lambda real_fn: real_fn
        return fn

    torch.jit.script = _passthrough
    if hasattr(torch.jit, "script_method"):
        torch.jit.script_method = _passthrough


def _write_tone(path: Path, duration_sec: float = 0.35, frequency: float = 880.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16000
    amplitude = 0.2
    frame_count = int(sample_rate * duration_sec)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for index in range(frame_count):
            ramp = min(1.0, index / max(1, frame_count - 1))
            window = math.sin(math.pi * ramp)
            sample = int(32767 * amplitude * window * math.sin(2 * math.pi * frequency * index / sample_rate))
            wav.writeframes(struct.pack("<h", sample))


def _decode_audio_codes(model, device: str, audio_frames: list[list[int]], reply_wav: Path) -> bool:
    import soundfile as sf
    import torch

    codes = [frame for frame in audio_frames if frame and len(frame) == 8]
    if not codes:
        return False
    mimi_codes = torch.tensor(codes, dtype=torch.long).T.unsqueeze(0).to(device)
    filtered = torch.where(mimi_codes >= 2049, torch.zeros_like(mimi_codes), mimi_codes)
    with torch.no_grad():
        audio = model.mimi_model.decode(filtered).audio_values
    reply_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(reply_wav), audio.squeeze().float().detach().cpu().numpy(), 24000)
    return reply_wav.exists() and reply_wav.stat().st_size > 44


def _collect_generation(
    model,
    tokenizer,
    prompt: str,
    *,
    device: str,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    audio_inputs=None,
    audio_lens=None,
    stream_text: Path | None = None,
) -> tuple[str, list[list[int]]]:
    import torch

    messages = [{"role": "user", "content": prompt}]
    inputs_text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        open_thinking=False,
    )
    input_ids = tokenizer(inputs_text).data["input_ids"]
    x = torch.tensor(input_ids, dtype=torch.long, device=device)[None, ...]
    audio_frames: list[list[int]] = []
    answer = ""
    _write_stream_text(stream_text, "")
    with torch.no_grad():
        stream = model.generate(
            x,
            tokenizer.eos_token_id,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=True,
            return_audio_codes=True,
            open_thinking=False,
            audio_inputs=audio_inputs,
            audio_lens=audio_lens,
        )
        for token_ids, audio_frame in stream:
            if token_ids is not None:
                decoded = tokenizer.decode(token_ids[0].tolist(), skip_special_tokens=True)
                if decoded and not decoded.endswith("\ufffd"):
                    answer = decoded
                    _write_stream_text(stream_text, answer)
            if audio_frame:
                audio_frames.append(audio_frame)
    return answer.strip(), audio_frames


def _load_model(repo: Path, args: argparse.Namespace):
    _set_runtime_env(args.threads)
    _disable_torch_jit_script()
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    from eval_omni import init_model

    model_args = SimpleNamespace(
        load_from=args.load_from,
        save_dir=args.save_dir,
        weight=args.weight,
        hidden_size=args.hidden_size,
        num_hidden_layers=args.num_hidden_layers,
        use_moe=0,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        output_dir=str(args.reply_wav.parent),
        device=args.device,
        audio_dir=str(repo / "dataset" / "eval_omni"),
        image_dir=str(repo / "dataset" / "eval_omni"),
        open_thinking=0,
        decode_audio=1,
        mode="0",
        prompt_lang=1,
    )
    return init_model(model_args)


def run(args: argparse.Namespace) -> int:
    start = time.monotonic()
    _set_runtime_env(args.threads)
    _disable_torch_jit_script()
    repo = args.repo.resolve()
    result = {
        "mode": args.mode,
        "repo": str(repo),
        "input_wav": str(args.input_wav) if args.input_wav else "",
        "reply_wav": str(args.reply_wav),
        "stream_text": str(args.stream_text) if args.stream_text else "",
        "reply_text": "",
        "audio_frames": 0,
        "audio_decoded": False,
        "audio_decode_error": "",
        "fallback_tone": False,
        "elapsed_sec": None,
        "error": "",
    }
    try:
        import torch
        from dataset.omni_dataset import OmniDataset  # type: ignore[import-not-found]
    except Exception:
        torch = None
        OmniDataset = None

    if not repo.exists():
        result["error"] = f"repo not found: {repo}"
        args.result_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 2

    try:
        args.reply_wav.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(sys.stderr):
            model, tokenizer = _load_model(repo, args)
        prompt = args.prompt
        audio_inputs = None
        audio_lens = None
        if args.stream_text is not None:
            _write_stream_text(args.stream_text, "")
        if args.mode == "audio":
            if args.input_wav is None or not args.input_wav.exists() or args.input_wav.stat().st_size <= 44:
                raise RuntimeError("input wav missing or empty")
            if torch is None or OmniDataset is None:
                import torch as torch_mod
                from dataset.omni_dataset import OmniDataset as dataset_mod

                torch = torch_mod
                OmniDataset = dataset_mod
            mel, valid_len = OmniDataset.process_audio(str(args.input_wav), model.audio_processor)
            audio_inputs = mel.unsqueeze(0).to(args.device)
            audio_lens = torch.tensor([valid_len], device=args.device)
            prompt = model.config.audio_special_token * (valid_len or 1)
        answer, audio_frames = _collect_generation(
            model,
            tokenizer,
            prompt,
            device=args.device,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            audio_inputs=audio_inputs,
            audio_lens=audio_lens,
            stream_text=args.stream_text,
        )
        result["reply_text"] = answer
        _write_stream_text(args.stream_text, answer)
        result["audio_frames"] = len(audio_frames)
        if args.decode_audio:
            try:
                result["audio_decoded"] = _decode_audio_codes(model, args.device, audio_frames, args.reply_wav)
            except Exception as exc:  # noqa: BLE001
                result["audio_decode_error"] = str(exc)
        if not result["audio_decoded"] and args.fallback_tone:
            _write_tone(args.reply_wav)
            result["fallback_tone"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        if args.fallback_tone:
            with contextlib.suppress(Exception):
                _write_tone(args.reply_wav, frequency=440.0)
                result["fallback_tone"] = True
        return_code = 1
    else:
        return_code = 0
    finally:
        result["elapsed_sec"] = round(time.monotonic() - start, 3)
        args.result_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return return_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-shot MiniMind-O voice runner for the RK3576 GUI")
    parser.add_argument("--repo", type=Path, default=Path("/mnt/eaget/workspace/minimind-o"))
    parser.add_argument("--input-wav", type=Path)
    parser.add_argument("--reply-wav", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--stream-text", type=Path)
    parser.add_argument("--mode", choices=["audio", "text"], default="audio")
    parser.add_argument("--prompt", default="请用一句话回答：芯片检测系统已经准备好了吗？")
    parser.add_argument("--load-from", default="model")
    parser.add_argument("--save-dir", default="out")
    parser.add_argument("--weight", default="sft_omni")
    parser.add_argument("--hidden-size", type=int, default=768)
    parser.add_argument("--num-hidden-layers", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=24)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.85)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--decode-audio", type=int, default=1)
    parser.add_argument("--fallback-tone", type=int, default=1)
    return parser.parse_args()


if __name__ == "__main__":
    os._exit(run(parse_args()))
