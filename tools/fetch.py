#!/usr/bin/env python3
import os
import sys
import re
import shutil
import subprocess
from urllib.parse import urlparse
from urllib.request import Request, urlopen

def is_m3u8(url: str) -> bool:
    u = url.lower()
    return ".m3u8" in u or u.endswith("manifest.m3u8")

def sanitize_filename(name: str) -> str:
    # very light sanitize (keep it simple for Actions)
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    if not name:
        return "output.mp4"
    return name

def ensure_output_for_hls(out_name: str) -> str:
    out_name = sanitize_filename(out_name)
    # HLS should be muxed into a known container -> default mp4
    root, ext = os.path.splitext(out_name)
    if ext.lower() not in [".mp4", ".mkv", ".mov", ".ts"]:
        return out_name + ".mp4"
    # If ext is empty, add mp4
    if ext == "":
        return out_name + ".mp4"
    return out_name

def run_ffmpeg_hls(url: str, out_path: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found. Install ffmpeg in the runner first.")

    # If output is mp4/mkv/mov, copy streams; for AAC in TS -> mp4, use aac_adtstoasc
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        out_path
    ]

    print("Running:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed with exit code {e.returncode}") from e

def download_direct(url: str, out_path: str) -> None:
    # Basic direct download (no special bypass). Some servers require headers; add a generic UA.
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; GitHubActionsFetcher/1.0)",
        "Accept": "*/*",
    })

    with urlopen(req, timeout=60) as r, open(out_path, "wb") as f:
        total = r.headers.get("Content-Length")
        if total:
            print("Content-Length:", total)

        chunk_size = 1024 * 1024  # 1MB
        downloaded = 0
        while True:
            chunk = r.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if downloaded % (10 * chunk_size) == 0:
                print(f"Downloaded ~{downloaded/1024/1024:.1f} MB")

def main():
    if len(sys.argv) < 2:
        print("Usage: fetch.py <URL> [OUT_NAME]")
        sys.exit(2)

    url = sys.argv[1].strip()
    out_name = sys.argv[2].strip() if len(sys.argv) >= 3 and sys.argv[2].strip() else ""

    # Default output name
    if not out_name:
        out_name = "output.mp4" if is_m3u8(url) else "output.bin"

    # For HLS, force a proper container extension if missing/unknown
    if is_m3u8(url):
        out_name = ensure_output_for_hls(out_name)

    out_name = sanitize_filename(out_name)
    out_path = os.path.abspath(out_name)

    print("URL:", url)
    print("Output:", out_path)
    print("is_hls:", is_m3u8(url))

    try:
        if is_m3u8(url):
            run_ffmpeg_hls(url, out_path)
        else:
            download_direct(url, out_path)
    except Exception as e:
        print("ERROR:", str(e))
        sys.exit(1)

    # Basic sanity check
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        print("ERROR: output file missing or empty:", out_path)
        sys.exit(1)

    print("Done. Size:", os.path.getsize(out_path), "bytes")

if __name__ == "__main__":
    main()
