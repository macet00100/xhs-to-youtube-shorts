"""
Module: Video Processor - Old Subtitle Masking & New Subtitle Burning via FFmpeg
Path: src/video_processor.py
"""

import json
import logging
import os
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


def process_video_and_burn_subs(
    input_video_path: str,
    srt_subtitles_path: str,
    output_video_path: str,
    blur_y_ratio: float = 0.745,
    blur_height_ratio: float = 0.135,
) -> str:
    """
    Applies FFmpeg filters to:
    1. Create a smooth frosted-glass blur band over the old Chinese subtitle area.
    2. Burn the new Vietnamese subtitles directly on top of the blurred zone with
       high-contrast Shorts styling (white text, thick black outline, bottom-centered).
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
    w, h = get_video_dimensions(input_video_path)
    logger.info(f"Input video dimensions: {w}x{h}")

    # Standardize path for FFmpeg filter (use relative path if possible to avoid Windows drive colon escaping)
    try:
        clean_srt_path = os.path.relpath(srt_subtitles_path).replace("\\", "/")
    except Exception:
        clean_srt_path = srt_subtitles_path.replace("\\", "/").replace(":", "\\:")

    # Scale font size dynamically based on video height (ideal: ~22px for 1920p, ~18px for 1280p)
    font_size = max(18, int(h * 0.016))
    margin_v = int(h * (1.0 - (blur_y_ratio + blur_height_ratio * 0.55)))

    style = (
        f"FontName=Arial,"
        f"FontSize={font_size},"
        f"Bold=1,"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"BorderStyle=1,"
        f"Outline=3.5,"
        f"Shadow=1,"
        f"Alignment=2,"
        f"MarginV={margin_v}"
    )

    # Filter complex:
    # 1. Split video stream into [base] and [crop_strip]
    # 2. Crop subtitle band [ih * blur_y_ratio] and apply boxblur
    # 3. Overlay blurred band back onto [base] at y = H * blur_y_ratio
    # 4. Burn the styled Vietnamese subtitles on top
    filter_complex = (
        f"[0:v]split=2[v_base][v_crop];"
        f"[v_crop]crop=w=iw:h=ih*{blur_height_ratio:.3f}:x=0:y=ih*{blur_y_ratio:.3f},"
        f"boxblur=luma_radius=22:luma_power=5[v_blur];"
        f"[v_base][v_blur]overlay=0:H*{blur_y_ratio:.3f}[v_masked];"
        f"[v_masked]subtitles='{clean_srt_path}':force_style='{style}'[v_out]"
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
