"""
Main Entry Point: Automated Xiaohongshu to YouTube Shorts Pipeline
Author: Automated Bot
Target: 拧不动啊真拧不动 (Xiaohongshu: 6542ed2b00000000300323af)
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import shutil
import sys

from src.xhs_monitor import check_and_download_latest_video
from src.sub_translator import generate_vietnamese_subtitles
from src.video_processor import process_video_and_burn_subs, generate_shorts_thumbnail
from src.youtube_uploader import upload_to_youtube_shorts
from src.fb_uploader import upload_to_facebook_page

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("AutoReupPipeline")


def update_history(history_file: str, note_record: dict):
    """Appends newly processed note record to history.json."""
    data = {"last_updated": "", "target_user_id": "6542ed2b00000000300323af", "processed_notes": []}
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data.setdefault("processed_notes", []).append(note_record)

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Updated {history_file} with note: {note_record.get('note_id')}")


def main():
    parser = argparse.ArgumentParser(description="Automated Xiaohongshu to YouTube Shorts Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run without uploading to YouTube")
    parser.add_argument("--history", default="history.json", help="Path to history tracking file")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"], help="YouTube Shorts privacy")
    parser.add_argument("--order", default="oldest_first", choices=["oldest_first", "newest_first"], help="Strategy for backlog processing")
    args = parser.parse_args()

    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)

    # Load local .env file if present
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    logger.info("=" * 65)
    logger.info("[START] Xiaohongshu -> YouTube Shorts Auto-Reup Pipeline")
    logger.info("Target Creator: 拧不动啊真拧不动 (6542ed2b00000000300323af)")
    logger.info("=" * 65)

    # STEP 1: Scan Xiaohongshu and download targeted video (oldest or newest)
    logger.info(f">>> STEP 1: Checking Xiaohongshu channel for videos (order={args.order})...")
    video_info = asyncio.run(check_and_download_latest_video(
        history_file=args.history,
        output_dir=temp_dir,
        order=args.order,
    ))

    if not video_info:
        logger.info("No new video found. Everything is up to date. Exiting cleanly.")
        sys.exit(0)

    logger.info(f"Target Video Acquired: '{video_info['title']}' (ID: {video_info['note_id']})")

    # STEP 2: Speech transcription & Vietnamese subtitle generation via Gemini
    logger.info(">>> STEP 2: Transcribing Chinese audio & generating Vietnamese SRT subtitles...")
    sub_info = generate_vietnamese_subtitles(
        video_path=video_info["video_path"],
        original_title=video_info["title"],
        original_desc=video_info["desc"],
        output_dir=temp_dir,
    )

    # STEP 3: Mask old Chinese subtitles & burn new Vietnamese subtitles with FFmpeg
    logger.info(">>> STEP 3: Applying FFmpeg subtitle blur-mask & burning Vietnamese subtitles...")
    final_shorts_path = os.path.join(temp_dir, "final_shorts.mp4")
    process_video_and_burn_subs(
        input_video_path=video_info["video_path"],
        srt_subtitles_path=sub_info["srt_path"],
        output_video_path=final_shorts_path,
    )

    # STEP 3.5: Generate eye-catching YouTube Shorts thumbnail with Vietnamese hook banner
    thumb_path = os.path.join(temp_dir, "thumb.jpg")
    final_thumb = generate_shorts_thumbnail(
        cover_image_path=video_info.get("cover_path", ""),
        output_thumbnail_path=thumb_path,
        hook_text=sub_info.get("thumb_hook", ""),
    )

    # STEP 4: Upload to YouTube Shorts
    logger.info(">>> STEP 4: Uploading to YouTube Shorts...")
    privacy_setting = os.environ.get("YOUTUBE_PRIVACY") or args.privacy
    if args.dry_run:
        logger.info("[DRY-RUN] Skipping YouTube upload step.")
        yt_id = "DRY_RUN_ID"
    else:
        yt_id = upload_to_youtube_shorts(
            video_path=final_shorts_path,
            title=sub_info["vi_title"],
            description=sub_info["vi_desc"],
            thumbnail_path=final_thumb,
            privacy_status=privacy_setting,
        )

    # STEP 5: Upload to Facebook Page (Reels) if configured
    logger.info(">>> STEP 5: Checking & Uploading to Facebook Page (Reels)...")
    if args.dry_run:
        logger.info("[DRY-RUN] Skipping Facebook upload step.")
        fb_id = "DRY_RUN_FB_ID"
    else:
        fb_id = upload_to_facebook_page(
            video_path=final_shorts_path,
            title=sub_info["vi_title"],
            description=sub_info["vi_desc"],
        )

    # STEP 6: Record to history
    record = {
        "note_id": video_info["note_id"],
        "title": video_info["title"],
        "vi_title": sub_info["vi_title"],
        "youtube_id": yt_id,
        "facebook_id": fb_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    if not args.dry_run:
        update_history(args.history, record)
        # Cleanup temp directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
    else:
        logger.info("[DRY-RUN] Retaining temp directory and skipping history update for inspection.")

    logger.info("=" * 65)
    logger.info("[SUCCESS] Pipeline completed successfully!")
    logger.info(f"Published Short: {sub_info['vi_title']} (YouTube ID: {yt_id})")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
