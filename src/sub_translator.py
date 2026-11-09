"""
Module: Speech Transcription & Vietnamese Translation via Gemini AI
Path: src/sub_translator.py
"""

import json
import logging
import os
import re
import subprocess
from typing import Dict, Optional
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("SubTranslator")


def extract_audio_from_video(video_path: str, audio_path: str) -> str:
    """Extracts compressed MP3 audio from input video using FFmpeg."""
    os.makedirs(os.path.dirname(os.path.abspath(audio_path)), exist_ok=True)
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        "-ab", "64k",
        audio_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info(f"Extracted audio to: {audio_path}")
    return audio_path


def generate_vietnamese_subtitles(
    video_path: str,
    original_title: str,
    original_desc: str,
    output_dir: str = "temp",
    api_key: Optional[str] = None,
) -> Dict:
    """
    Transcribes Chinese audio from the video and translates it directly into Vietnamese SRT subtitles
    using Google Gemini Flash AI. Also translates the title and description for YouTube Shorts.
    """
    os.makedirs(output_dir, exist_ok=True)
    audio_path = os.path.join(output_dir, "audio.mp3")
    srt_path = os.path.join(output_dir, "subtitles.srt")

    extract_audio_from_video(video_path, audio_path)

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        logger.warning("GEMINI_API_KEY not found. Using fallback placeholder subtitle.")
        default_srt = (
            "1\n00:00:00,500 --> 00:00:04,000\n"
            f"{original_title}\n\n"
            "2\n00:00:04,500 --> 00:00:08,000\n"
            "Xem tiếp tại kênh để ủng hộ mình nhé!\n"
        )
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(default_srt)
        return {
            "srt_path": srt_path,
            "vi_title": original_title,
            "vi_desc": original_desc,
        }

    logger.info("Calling Gemini Flash API to transcribe Chinese speech and translate to Vietnamese SRT...")
    client = genai.Client(api_key=api_key)

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3")

    prompt = f"""
Bạn là chuyên gia dịch thuật và biên tập phụ đề video ngắn (TikTok/YouTube Shorts) từ tiếng Trung sang tiếng Việt.

Nhiệm vụ:
1. Lắng nghe toàn bộ lời thoại tiếng Trung trong đoạn audio đính kèm.
2. Dịch toàn bộ lời thoại sang TIẾNG VIỆT tự nhiên, bắt tai, hài hước và khớp với ngữ cảnh video ngắn.
3. Tạo ra phụ đề chuẩn định dạng SRT (SubRip) có mốc thời gian (timestamp) chính xác từng giây.
   - Mỗi câu phụ đề không quá 8-10 từ để người xem dễ đọc trên điện thoại.
4. Dịch tiêu đề gốc: "{original_title}" sang 1 câu tiêu đề tiếng Việt giật tít, cuốn hút chuẩn YouTube Shorts (tối đa 60 ký tự).
5. Tóm tắt nội dung mô tả video bằng 1-2 câu tiếng Việt.
6. Đặt 1 câu HOOK ngắn gọn (2-5 từ, VIẾT HOA) để in làm ảnh thumbnail YouTube Shorts (ví dụ: "CẢ CUỘC ĐỜI CON NGƯỜI", "1 TUỔI ĐẾN 100 TUỔI", "TẬP NÀY CỰC CĂNG").

Định dạng trả về:
Hãy trả về DUY NHẤT một chuỗi JSON hợp lệ theo cấu trúc sau (không kèm markdown ```json bọc ngoài):
{{
  "vi_title": "Tiêu đề tiếng Việt cực bắt tai",
  "vi_desc": "Mô tả ngắn tiếng Việt...",
  "thumb_hook": "HOOK NGẮN IN ẢNH BÌA",
  "srt_content": "1\\n00:00:01,000 --> 00:00:03,500\\nCâu phụ đề tiếng Việt 1\\n\\n2\\n00:00:03,600 --> 00:00:06,200\\nCâu phụ đề tiếng Việt 2"
}}
"""

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[audio_part, prompt],
        )
        text = response.text.strip()
        # Strip potential markdown formatting if model wrapped in ```json
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        data = json.loads(text)

        vi_title = data.get("vi_title", original_title)
        vi_desc = data.get("vi_desc", original_desc)
        thumb_hook = data.get("thumb_hook", vi_title)
        srt_content = data.get("srt_content", "")

        if not srt_content:
            srt_content = f"1\n00:00:00,500 --> 00:00:05,000\n{vi_title}\n"

        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(f"Generated Vietnamese subtitles -> {srt_path}")
        logger.info(f"Vietnamese Title: {vi_title}")
        logger.info(f"Thumbnail Hook: {thumb_hook}")
        return {
            "srt_path": srt_path,
            "vi_title": vi_title,
            "vi_desc": vi_desc,
            "thumb_hook": thumb_hook,
        }

    except Exception as e:
        logger.error(f"Error during Gemini subtitle translation: {e}. Falling back to default subtitle.")
        default_srt = f"1\n00:00:00,500 --> 00:00:05,000\n{original_title}\n"
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(default_srt)
        return {
            "srt_path": srt_path,
            "vi_title": original_title,
            "vi_desc": original_desc,
        }
