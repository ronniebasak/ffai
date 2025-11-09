#!/usr/bin/env python3
"""
detect_hw_encoders.py

Cross-platform (Windows/Linux/macOS) detection and functional probe for FFmpeg
hardware accelerated encoders: NVENC, QSV, VAAPI, AMF, VideoToolbox.

Requirements: Python 3.x, ffmpeg available on PATH.

Usage:
    python detect_hw_encoders.py
"""
from __future__ import annotations
import shutil
import subprocess
import sys
import platform
import os
import tempfile
from typing import List, Tuple

FFPROBE_TIMEOUT = 12  # seconds for quick probes

def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FileNotFoundError("ffmpeg not found in PATH")
    return path

def run(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    try:
        completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, universal_newlines=True)
        return completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as e:
        return -9, "", f"TIMEOUT after {timeout}s"

def list_encoders(ffmpeg: str) -> List[str]:
    rc, out, err = run([ffmpeg, "-hide_banner", "-encoders"])
    text = out + "\n" + err
    encs = []
    for line in text.splitlines():
        # ffmpeg encoder lines typically like: " V..... h264_nvenc           NVIDIA NVENC H.264 encoder"
        parts = line.strip().split()
        if len(parts) >= 2:
            # take the second token usually encoder name, but be cautious
            token = parts[1]
            if token.islower() and all(c.isalnum() or c == '_' for c in token):
                encs.append(token)
    return sorted(set(encs))

def hwaccels(ffmpeg: str) -> List[str]:
    rc, out, err = run([ffmpeg, "-hide_banner", "-hwaccels"])
    text = out + "\n" + err
    lines = []
    for line in text.splitlines():
        l = line.strip()
        if not l: 
            continue
        # skip header line "Hardware acceleration methods:"
        if "Hardware acceleration methods" in l:
            continue
        lines.append(l)
    return lines

def probe_encoder(ffmpeg: str, codec: str, extra_args: List[str]=None, timeout: int = FFPROBE_TIMEOUT) -> Tuple[bool, str]:
    """
    Try a tiny encode using testsrc (1 second) to /dev/null or ffmpeg null sink.
    Returns (success_bool, combined_output).
    """
    extra_args = extra_args or []
    # Use small resolution and short duration
    base_cmd = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=size=128x128:rate=5:duration=1",
    ]
    cmd = base_cmd + extra_args + ["-c:v", codec, "-t", "1", "-f", "null", "-"]
    rc, out, err = run(cmd, timeout=timeout)
    combined = out + "\n" + err
    if rc == 0 and "error" not in combined.lower() and "failed" not in combined.lower():
        return True, combined
    else:
        return False, combined

def device_exists(path: str) -> bool:
    try:
        return os.path.exists(path)
    except Exception:
        return False

def main():
    try:
        ffmpeg = find_ffmpeg()
    except FileNotFoundError as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(2)

    print("FFmpeg:", ffmpeg)
    print("Platform:", platform.system(), platform.release())
    print()

    encoders = list_encoders(ffmpeg)
    print("Encoders found (filtered):", ", ".join(encoders[:50]) + ("" if len(encoders) <= 50 else " ..."))
    print()

    accels = hwaccels(ffmpeg)
    print("Reported hardware acceleration methods:", ", ".join(accels) if accels else "(none listed)")
    print()

    results = {}

    # NVENC (NVIDIA)
    nvenc_names = ["h264_nvenc", "hevc_nvenc", "av1_nvenc"]
    if any(name in encoders for name in nvenc_names):
        print("NVENC encoders listed by ffmpeg.")
        # optional: check nvidia-smi if available
        nvsmi = shutil.which("nvidia-smi")
        if nvsmi:
            rc, out, err = run([nvsmi, "--query-gpu=name,driver_version", "--format=csv,noheader"], timeout=5)
            print("  nvidia-smi:", out.strip() or err.strip())
        ok, out = False, ""
        for c in nvenc_names:
            if c in encoders:
                # Try multiple strategies to initialize NVENC
                # Strategy 1: Direct probe (works if CUDA is default)
                ok, out = probe_encoder(ffmpeg, c)
                if not ok:
                    # Strategy 2: Try with explicit CUDA device initialization
                    ok, out = probe_encoder(ffmpeg, c, extra_args=["-hwaccel", "cuda"])
                if not ok:
                    # Strategy 3: Try with CUDA device initialization
                    ok, out = probe_encoder(ffmpeg, c, extra_args=["-init_hw_device", "cuda=cuda:0"])
                
                print(f"  probe {c}: {'OK' if ok else 'FAIL'}")
                if not ok:
                    # print short reason
                    print("\n".join(line for line in out.splitlines()[-6:]))
                results["nvenc"] = ok
                break
    else:
        print("NVENC: not listed")
        results["nvenc"] = False

    # QSV (Intel Quick Sync)
    qsv_names = ["h264_qsv", "hevc_qsv", "av1_qsv"]
    if any(name in encoders for name in qsv_names):
        print("\nQSV encoders listed by ffmpeg.")
        # QSV probe requires init_hw_device qsv=hw
        codec = next((c for c in qsv_names if c in encoders), qsv_names[0])
        ok, out = probe_encoder(ffmpeg, codec, extra_args=["-init_hw_device", "qsv=hw"])
        print(f"  probe {codec} with -init_hw_device qsv=hw: {'OK' if ok else 'FAIL'}")
        if not ok:
            print("\n".join(line for line in out.splitlines()[-8:]))
        results["qsv"] = ok
    else:
        print("\nQSV: not listed")
        results["qsv"] = False

    # VAAPI (Linux DRM + Intel/AMD)
    vaapi_names = ["h264_vaapi", "hevc_vaapi"]
    if platform.system().lower() != "windows" and any(name in encoders for name in vaapi_names):
        print("\nVAAPI encoders listed by ffmpeg.")
        # common device path
        dev = "/dev/dri/renderD128"
        if not device_exists(dev):
            # sometimes different render node; still attempt generic probe without device
            print("  render node", dev, "not present; probe may fail without proper DRM device.")
        codec = next((c for c in vaapi_names if c in encoders), vaapi_names[0])
        extra = ["-init_hw_device", f"vaapi=va:{dev}", "-filter_hw_device", "va", "-vf", "format=nv12,hwupload"]
        ok, out = probe_encoder(ffmpeg, codec, extra_args=extra)
        print(f"  probe {codec}: {'OK' if ok else 'FAIL'}")
        if not ok:
            print("\n".join(line for line in out.splitlines()[-8:]))
        results["vaapi"] = ok
    else:
        print("\nVAAPI: not detected/listed on this platform")
        results["vaapi"] = False

    # AMD AMF (usually Windows)
    amf_names = ["h264_amf", "hevc_amf"]
    if any(name in encoders for name in amf_names):
        print("\nAMD AMF encoders listed by ffmpeg.")
        codec = next((c for c in amf_names if c in encoders), amf_names[0])
        ok, out = probe_encoder(ffmpeg, codec)
        print(f"  probe {codec}: {'OK' if ok else 'FAIL'}")
        if not ok:
            print("\n".join(line for line in out.splitlines()[-8:]))
        results["amf"] = ok
    else:
        print("\nAMD AMF: not listed")
        results["amf"] = False

    # Apple VideoToolbox (macOS)
    vt_names = ["h264_videotoolbox", "hevc_videotoolbox"]
    if platform.system().lower() == "darwin" and any(name in encoders for name in vt_names):
        print("\nVideoToolbox encoders listed by ffmpeg.")
        codec = next((c for c in vt_names if c in encoders), vt_names[0])
        ok, out = probe_encoder(ffmpeg, codec)
        print(f"  probe {codec}: {'OK' if ok else 'FAIL'}")
        if not ok:
            print("\n".join(line for line in out.splitlines()[-8:]))
        results["videotoolbox"] = ok
    else:
        print("\nVideoToolbox: not detected/listed on this platform")
        results["videotoolbox"] = False

    # Summary
    print("\nSummary:")
    for k, v in results.items():
        print(f"  {k:12s}: {'usable' if v else 'not usable'}")

    print("\nNotes:")
    print(" - 'listed' means ffmpeg advertises the encoder name.")
    print(" - 'probe OK' means a minimal encode succeeded; still may need correct drivers/permissions.")
    print(" - On Linux, ensure the user can access /dev/dri/renderD128 for VAAPI.")
    print(" - On Windows, NVENC and AMF require vendor drivers; QSV requires Intel Media drivers and Intel iGPU present.")

if __name__ == "__main__":
    main()
