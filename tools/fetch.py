import sys
import os
import subprocess
from urllib.parse import urlparse

def guess_name(url: str) -> str:
    p = urlparse(url)
    name = os.path.basename(p.path) or "output.bin"
    if "m3u8" in name.lower():
        return "output.mp4"
    return name

def main():
    url = sys.argv[1].strip()
    out_name = (sys.argv[2].strip() if len(sys.argv) > 2 and sys.argv[2] else "")

    is_hls = ".m3u8" in url.lower()

    if not out_name:
        out_name = guess_name(url)

    out_path = "output.bin"
    print(f"URL: {url}")
    print(f"is_hls: {is_hls}")
    print(f"out_name: {out_name}")

    if is_hls:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            out_path
        ]
        print("Running:", " ".join(cmd))
        p = subprocess.run(cmd, text=True, capture_output=True)
        if p.returncode != 0:
            raise SystemExit(f"ffmpeg failed:\n{p.stderr[:2000]}")
    else:
        cmd = ["curl", "-L", "--fail", "-o", out_path, url]
        print("Running:", " ".join(cmd))
        p = subprocess.run(cmd, text=True, capture_output=True)
        if p.returncode != 0:
            raise SystemExit(f"curl failed:\n{p.stderr[:2000]}")

    size = os.path.getsize(out_path)
    print(f"Saved {out_path} size={size} bytes")

    with open("output.name.txt", "w", encoding="utf-8") as f:
        f.write(out_name)

if __name__ == "__main__":
    main()
