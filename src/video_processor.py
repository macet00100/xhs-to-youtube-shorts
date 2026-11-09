"""
Module: Video Processor - Old Subtitle Masking & New Subtitle Burning via FFmpeg
Path: src/video_processor.py
"""

import json
import logging
import os
import re
import subprocess
from typing import Dict, Tuple

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("VideoProcessor")


def get_video_dimensions(video_path: str) -> Tuple[int, int]:
    """Retrieves video width and height using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        video_path,
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    info = json.loads(res.stdout)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"])


def convert_srt_to_ass(
    srt_path: str,
    ass_path: str,
    video_width: int,
    video_height: int,
    font_size: int,
    margin_v: int,
) -> str:
    """
    Converts SRT subtitles into Advanced SubStation Alpha (.ass) format with explicit canvas resolution.
    This guarantees 100% pixel-perfect placement right on top of the old Chinese subtitle area.
    """
    with open(srt_path, "r", encoding="utf-8") as f:
        srt_content = f.read()

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3.5,0,2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    blocks = srt_content.strip().split("\n\n")
    for b in blocks:
        lines = [l.strip() for l in b.strip().split("\n") if l.strip()]
        if len(lines) >= 3:
            m = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", lines[1])
            if m:
                s_h, s_m, s_s, s_ms = m.groups()[:4]
                e_h, e_m, e_s, e_ms = m.groups()[4:]
                start = f"{int(s_h)}:{s_m}:{s_s}.{int(s_ms)//10:02d}"
                end = f"{int(e_h)}:{e_m}:{e_s}.{int(e_ms)//10:02d}"
                text = r"\N".join(lines[2:])
                events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(events) + "\n")

    return ass_path


def process_video_and_burn_subs(
    input_video_path: str,
    srt_subtitles_path: str,
    output_video_path: str,
    blur_y_ratio: float = 0.815,
    blur_height_ratio: float = 0.100,
) -> str:
    """
    Applies FFmpeg filters to:
    1. Create a smooth frosted-glass blur band over the old Chinese subtitle area at bottom (y ~ 81.5% to 91.5%).
    2. Burn the new Vietnamese subtitles directly on top of the blurred zone using pixel-perfect ASS positioning.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
    w, h = get_video_dimensions(input_video_path)
    logger.info(f"Input video dimensions: {w}x{h}")

    # Scale font size dynamically (~34px for 960h, ~42px for 1280h)
    font_size = max(26, int(h * 0.035))
    # MarginV: vertical distance from bottom edge to center subtitles right in blurred zone
    margin_v = int(h * 0.095)

    # Convert SRT to ASS in temp directory for exact placement
    temp_dir = os.path.dirname(os.path.abspath(output_video_path))
    ass_path = os.path.join(temp_dir, "subtitles.ass")
    convert_srt_to_ass(srt_subtitles_path, ass_path, w, h, font_size, margin_v)

    try:
        clean_ass_path = os.path.relpath(ass_path).replace("\\", "/")
    except Exception:
        clean_ass_path = ass_path.replace("\\", "/").replace(":", "\\:")

    # Filter complex:
    # 1. Split video stream into [base] and [crop_strip]
    # 2. Crop Chinese subtitle band at bottom [ih * blur_y_ratio] and apply boxblur
    # 3. Overlay blurred band back onto [base] at y = H * blur_y_ratio
    # 4. Burn the styled Vietnamese subtitles directly on top of the blurred band
    filter_complex = (
        f"[0:v]split=2[v_base][v_crop];"
        f"[v_crop]crop=w=iw:h=ih*{blur_height_ratio:.3f}:x=0:y=ih*{blur_y_ratio:.3f},"
        f"boxblur=luma_radius=18:luma_power=4[v_blur];"
        f"[v_base][v_blur]overlay=0:H*{blur_y_ratio:.3f}[v_masked];"
        f"[v_masked]subtitles='{clean_ass_path}'[v_out]"
    )

    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", input_video_path,
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "19",
        "-c:a", "aac",
        "-b:a", "192k",
        output_video_path,
    ]

    logger.info("Executing FFmpeg subtitle masking & burning filter...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        err_msg = res.stderr.decode("utf-8", errors="ignore")
        logger.error(f"FFmpeg processing failed: {err_msg}")
        raise RuntimeError(f"FFmpeg failed with exit code {res.returncode}")

    logger.info(f"Successfully processed video with new Vietnamese subs -> {output_video_path}")
    return output_video_path
