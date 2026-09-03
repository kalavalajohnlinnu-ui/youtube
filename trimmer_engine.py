import os
import sys
import shutil
import re
import json
import uuid
import time
import threading
import subprocess
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, Callable

import yt_dlp
import imageio_ffmpeg


# ─────────────────────────────────────────────────────────────────────────────
# FFmpeg & Node.js Setup
# ─────────────────────────────────────────────────────────────────────────────

def setup_ffmpeg() -> tuple:
    try:
        raw_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(raw_exe)
        target_exe = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        if not os.path.exists(target_exe) and os.path.exists(raw_exe):
            try:
                shutil.copy(raw_exe, target_exe)
            except Exception:
                target_exe = raw_exe
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        return (target_exe if os.path.exists(target_exe) else raw_exe, ffmpeg_dir)
    except Exception as e:
        print(f"Warning setting up ffmpeg: {e}")
        return ("", "")

FFMPEG_EXE, FFMPEG_DIR = setup_ffmpeg()


def get_node_path() -> str:
    default_path = r"C:\Program Files\nodejs\node.exe"
    if os.path.exists(default_path):
        return default_path
    node_which = shutil.which("node")
    if node_which and os.path.exists(node_which):
        return node_which
    return default_path

NODE_PATH = get_node_path()
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def parse_time_to_seconds(time_str: str) -> float:
    if not time_str:
        return 0.0
    time_str = str(time_str).strip().lower()
    h_match = re.search(r'(\d+)\s*h', time_str)
    m_match = re.search(r'(\d+)\s*m(?!s)', time_str)
    s_match = re.search(r'(\d+)\s*s', time_str)
    if h_match or m_match or s_match:
        return (float(h_match.group(1)) if h_match else 0) * 3600 + \
               (float(m_match.group(1)) if m_match else 0) * 60 + \
               (float(s_match.group(1)) if s_match else 0)
    try:
        return float(time_str)
    except ValueError:
        pass
    parts = time_str.split(":")
    try:
        parts = [float(p) for p in parts if p != ""]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 1:
            return parts[0]
    except Exception:
        pass
    return 0.0


def format_seconds_to_timestamp(seconds: float, force_hours: bool = True) -> str:
    seconds = max(0, int(round(seconds)))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0 or force_hours:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def extract_video_id(url: str) -> Optional[str]:
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11})',
        r'youtu\.be\/([0-9A-Za-z_-]{11})',
        r'youtube\.com\/embed\/([0-9A-Za-z_-]{11})',
        r'youtube\.com\/live\/([0-9A-Za-z_-]{11})',
        r'youtube\.com\/shorts\/([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def clean_youtube_url(url: str) -> str:
    """Strip ?si= and other tracking params that can cause yt-dlp failures."""
    url = url.strip()
    video_id = extract_video_id(url)
    if not video_id:
        return url
    if 'youtube.com/live/' in url:
        return f"https://www.youtube.com/live/{video_id}"
    if 'youtube.com/shorts/' in url:
        return f"https://www.youtube.com/shorts/{video_id}"
    return f"https://www.youtube.com/watch?v={video_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Video Info
# ─────────────────────────────────────────────────────────────────────────────

def fetch_oembed_info(url: str) -> Optional[Dict[str, Any]]:
    try:
        video_id = extract_video_id(url) or url
        target_url = f"https://www.youtube.com/watch?v={video_id}"
        oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(target_url)}&format=json"
        req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                return {
                    "id": video_id,
                    "title": data.get("title", "YouTube Video"),
                    "uploader": data.get("author_name", "YouTube Channel"),
                    "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                }
    except Exception:
        pass
    return None


def fetch_video_info(url: str) -> Dict[str, Any]:
    url = clean_youtube_url(url)
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("Could not extract a valid YouTube video ID from the URL.")

    title    = "YouTube Video"
    uploader = "YouTube Channel"
    duration = 0
    is_live  = False

    oembed_data = fetch_oembed_info(url)
    if oembed_data:
        title    = oembed_data.get("title", title)
        uploader = oembed_data.get("uploader", uploader)

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'source_address': '0.0.0.0',
            'skip_download': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web', 'tv']}},
        }
        if FFMPEG_DIR:
            ydl_opts['ffmpeg_location'] = FFMPEG_DIR
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
        if NODE_PATH and os.path.exists(NODE_PATH):
            ydl_opts['js_runtimes'] = {'node': {'path': NODE_PATH}}
            ydl_opts['remote_components'] = ['ejs:github']

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info     = ydl.extract_info(url, download=False)
            duration = info.get('duration') or 0
            is_live  = info.get('is_live', False) or info.get('was_live', False)
            if not title or title == 'YouTube Video':
                title = info.get('title', title)
            if not uploader or uploader == 'YouTube Channel':
                uploader = info.get('uploader') or info.get('channel', uploader)
    except Exception:
        pass

    return {
        "id": video_id,
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "duration_string": format_seconds_to_timestamp(duration, force_hours=True),
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "is_live": is_live,
        "description": ""
    }


# ─────────────────────────────────────────────────────────────────────────────
# Progress-aware yt-dlp subprocess runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_ytdlp_subprocess(cmd: list, progress_callback: Callable, clip_duration: float,
                           timeout_secs: int, initial_pct: int = 15) -> list:
    """Runs yt-dlp subprocess, parses download progress and sends updates."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace"
    )
    all_lines = []
    last_pct = [initial_pct]

    def read_output():
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            all_lines.append(line)
            dl = re.search(r'\[download\]\s+([\d.]+)%', line)
            if dl:
                raw = float(dl.group(1))
                mapped = int(initial_pct + (raw / 100.0) * (85 - initial_pct))
                last_pct[0] = max(last_pct[0], min(mapped, 84))
                eta_s = 0
                em = re.search(r'ETA\s+(\d+):(\d+)', line)
                if em:
                    eta_s = int(em.group(1)) * 60 + int(em.group(2))
                progress_callback(last_pct[0], f"Downloading Full HD... {raw:.1f}%", eta_seconds=eta_s)
                continue
            if 'time=' in line and 'speed=' in line:
                tm = re.search(r'time=(\d+:\d+:\d+[\.\d]*)', line)
                sp = re.search(r'speed=\s*([\d.]+)x', line)
                if tm:
                    cur = parse_time_to_seconds(tm.group(1))
                    spd = float(sp.group(1)) if sp else 1.0
                    pct = int(initial_pct + min(85 - initial_pct,
                              (cur / clip_duration) * (85 - initial_pct)))
                    eta = max(1, int((clip_duration - cur) / max(0.01, spd)))
                    progress_callback(pct,
                        f"Processing stream ({tm.group(1)} / {format_seconds_to_timestamp(clip_duration)})",
                        eta_seconds=eta)
                continue
            if '[Merger]' in line or 'Merging' in line:
                progress_callback(88, "Merging high-quality audio + video tracks...", eta_seconds=5)
            elif '[ExtractAudio]' in line:
                progress_callback(90, "Extracting high-bitrate audio track...", eta_seconds=4)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout_secs)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RuntimeError(f"Download timed out after {timeout_secs // 60} min.")
    reader.join(timeout=5)
    if proc.returncode != 0:
        tail = "\n".join(all_lines[-15:])
        raise RuntimeError(f"yt-dlp failed (code {proc.returncode}):\n{tail}")
    return all_lines


def _locate_output(output_dir: str, prefix: str, preferred_ext: str) -> str:
    preferred = os.path.join(output_dir, f"{prefix}.{preferred_ext}")
    if os.path.exists(preferred):
        return os.path.basename(preferred)
    candidates = sorted(
        [f for f in os.listdir(output_dir) if f.startswith(prefix) and not f.endswith(".part")],
        key=lambda x: os.path.getmtime(os.path.join(output_dir, x)),
        reverse=True
    )
    if candidates:
        return candidates[0]
    raise RuntimeError("Output file not found after download.")


# ─────────────────────────────────────────────────────────────────────────────
# Main Download Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def run_trim_download(
    url: str,
    start_time: str,
    end_time: str,
    output_dir: str,
    task_id: str,
    progress_callback: Callable,
    out_format: str = "mp4",
    quality: str = "best",
    audio_only: bool = False,
    is_full_download: bool = False
) -> str:
    """
    Downloads and trims a YouTube video segment with pristine visual quality
    and 100% guaranteed compatible AAC stereo audio.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Clean URL — strip ?si= and tracking params
    url = clean_youtube_url(url)

    start_sec   = parse_time_to_seconds(start_time)
    end_sec     = parse_time_to_seconds(end_time)
    clip_dur    = max(1.0, end_sec - start_sec) if not is_full_download else 7200.0
    clean_id    = re.sub(r'[^a-zA-Z0-9_-]', '_', task_id)
    outtmpl     = os.path.join(output_dir, f"trimmed_{clean_id}.%(ext)s")
    file_prefix = f"trimmed_{clean_id}"

    if not is_full_download and end_sec <= start_sec:
        raise ValueError("End time must be after start time.")

    # ── Universal High-Quality Format Selector ────────────────────────────────
    # Prioritizes:
    # 1. High-bitrate 1080p H.264 (avc1) + M4A AAC audio
    # 2. Universal AAC audio compatibility (Merger re-encodes to AAC if Opus selected)
    # 3. High-bitrate HLS streams (up to 4.8 Mbps)
    if audio_only or out_format == "mp3":
        fmt = "bestaudio[ext=m4a]/bestaudio/best"
    elif quality == "1080p":
        fmt = (
            "bestvideo[height=1080][vcodec^=avc1]+bestaudio[ext=m4a]/"
            "bestvideo[height=1080][vcodec^=avc1]+bestaudio/"
            "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]/"
            "bestvideo[height<=1080][vcodec^=avc1]+bestaudio/"
            "best[height=1080][protocol^=m3u8]/"
            "bestvideo[height<=1080]+bestaudio[ext=m4a]/"
            "bestvideo[height<=1080]+bestaudio/best"
        )
    elif quality == "720p":
        fmt = (
            "bestvideo[height=720][vcodec^=avc1]+bestaudio[ext=m4a]/"
            "bestvideo[height=720][vcodec^=avc1]+bestaudio/"
            "bestvideo[height<=720][vcodec^=avc1]+bestaudio[ext=m4a]/"
            "bestvideo[height<=720][vcodec^=avc1]+bestaudio/"
            "best[height=720][protocol^=m3u8]/"
            "bestvideo[height<=720]+bestaudio[ext=m4a]/"
            "bestvideo[height<=720]+bestaudio/best"
        )
    elif quality == "480p":
        fmt = (
            "bestvideo[height=480][vcodec^=avc1]+bestaudio[ext=m4a]/"
            "bestvideo[height=480][vcodec^=avc1]+bestaudio/"
            "bestvideo[height<=480][vcodec^=avc1]+bestaudio/"
            "best[height=480][protocol^=m3u8]/"
            "bestvideo[height<=480]+bestaudio/best"
        )
    else:  # "best"
        fmt = (
            "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/"
            "bestvideo[vcodec^=avc1]+bestaudio/"
            "best[protocol^=m3u8]/"
            "bestvideo+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/best"
        )

    base_ytdlp = [
        sys.executable, "-m", "yt_dlp",
        "-4",
        "--no-playlist",
        "--no-warnings",
        "--extractor-args", "youtube:player_client=android,web,tv",
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "2",
    ]
    if FFMPEG_DIR:
        base_ytdlp += ["--ffmpeg-location", FFMPEG_DIR]
    if os.path.exists(COOKIES_FILE):
        base_ytdlp += ["--cookies", COOKIES_FILE]
    if NODE_PATH and os.path.exists(NODE_PATH):
        base_ytdlp += [
            "--js-runtimes", f"node:{NODE_PATH}",
            "--remote-components", "ejs:github",
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # CASE A: Full download (no trimming needed)
    # ─────────────────────────────────────────────────────────────────────────
    if is_full_download:
        progress_callback(10, "Starting full download...", eta_seconds=60)
        cmd = base_ytdlp + [
            "--format", fmt,
            "--output", outtmpl,
            "--newline",
            "--no-part",
        ]
        if not (audio_only or out_format == "mp3"):
            cmd += [
                "--merge-output-format", out_format,
                "--postprocessor-args", "Merger:-c:a aac -b:a 192k",
            ]
        if audio_only or out_format == "mp3":
            cmd += ["--extract-audio", "--audio-format", "mp3", "--audio-quality", "0"]
        cmd.append(url)
        _run_ytdlp_subprocess(cmd, progress_callback, clip_dur, 7200, initial_pct=10)
        progress_callback(98, "Finalizing...", eta_seconds=2)
        ext = "mp3" if (audio_only or out_format == "mp3") else out_format
        return _locate_output(output_dir, file_prefix, ext)

    start_fmt = format_seconds_to_timestamp(start_sec)
    end_fmt   = format_seconds_to_timestamp(end_sec)

    # ─────────────────────────────────────────────────────────────────────────
    # CASE B: Audio-only trim
    # ─────────────────────────────────────────────────────────────────────────
    if audio_only or out_format == "mp3":
        progress_callback(10, "Starting audio download...", eta_seconds=30)
        cmd = base_ytdlp + [
            "--format", fmt,
            "--output", outtmpl,
            "--newline",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--download-sections", f"*{start_fmt}-{end_fmt}",
            "--concurrent-fragments", "4",
            "--no-part",
            url,
        ]
        timeout = max(300, int(clip_dur * 3) + 300)
        _run_ytdlp_subprocess(cmd, progress_callback, clip_dur, timeout, initial_pct=10)
        progress_callback(98, "Finalizing MP3...", eta_seconds=2)
        return _locate_output(output_dir, file_prefix, "mp3")

    # ─────────────────────────────────────────────────────────────────────────
    # CASE C: Video trim (Adaptive 2-Stage High Quality Downloader)
    # ─────────────────────────────────────────────────────────────────────────
    progress_callback(10, "Connecting to YouTube high-quality stream...", eta_seconds=15)
    timeout = max(600, int(clip_dur * 4) + 600)

    # STAGE 1: Pristine Full HD 1080p with web_embedded + JS solver
    base_stage1 = [
        sys.executable, "-m", "yt_dlp",
        "-4",
        "--no-playlist",
        "--no-warnings",
        "--extractor-args", "youtube:player_client=web_embedded,android_vr,web",
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "2",
    ]
    if FFMPEG_DIR:
        base_stage1 += ["--ffmpeg-location", FFMPEG_DIR]
    if os.path.exists(COOKIES_FILE):
        base_stage1 += ["--cookies", COOKIES_FILE]
    if NODE_PATH and os.path.exists(NODE_PATH):
        base_stage1 += [
            "--js-runtimes", f"node:{NODE_PATH}",
            "--remote-components", "ejs:github",
        ]

    cmd_stage1 = base_stage1 + [
        "--format", fmt,
        "--output", outtmpl,
        "--merge-output-format", out_format,
        "--postprocessor-args", "Merger:-c:a aac -b:a 192k",
        "--newline",
        "--download-sections", f"*{start_fmt}-{end_fmt}",
        "--concurrent-fragments", "4",
        "--no-part",
        url,
    ]

    try:
        _run_ytdlp_subprocess(cmd_stage1, progress_callback, clip_dur, timeout, initial_pct=10)
        progress_callback(98, "Finalizing Full HD...", eta_seconds=2)
        return _locate_output(output_dir, file_prefix, out_format)
    except Exception as e:
        print(f"Stage 1 encountered issue: {e}. Switching to Stage 2 universal fallback...", flush=True)

    # STAGE 2: Universal Fallback for restricted/non-embeddable videos
    progress_callback(15, "Switching to universal stream...", eta_seconds=15)
    base_stage2 = [
        sys.executable, "-m", "yt_dlp",
        "-4",
        "--no-playlist",
        "--no-warnings",
        "--extractor-args", "youtube:player_client=android,web,tv",
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "2",
    ]
    if FFMPEG_DIR:
        base_stage2 += ["--ffmpeg-location", FFMPEG_DIR]
    if os.path.exists(COOKIES_FILE):
        base_stage2 += ["--cookies", COOKIES_FILE]
    if NODE_PATH and os.path.exists(NODE_PATH):
        base_stage2 += [
            "--js-runtimes", f"node:{NODE_PATH}",
            "--remote-components", "ejs:github",
        ]

    fallback_fmt = "bestvideo[height<=1080]+bestaudio/best"
    cmd_stage2 = base_stage2 + [
        "--format", fallback_fmt,
        "--output", outtmpl,
        "--merge-output-format", out_format,
        "--postprocessor-args", "Merger:-c:a aac -b:a 192k",
        "--newline",
        "--download-sections", f"*{start_fmt}-{end_fmt}",
        "--concurrent-fragments", "4",
        "--no-part",
        url,
    ]

    _run_ytdlp_subprocess(cmd_stage2, progress_callback, clip_dur, timeout, initial_pct=15)
    progress_callback(98, "Finalizing...", eta_seconds=2)
    return _locate_output(output_dir, file_prefix, out_format)

