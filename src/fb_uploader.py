"""
Module: Automated Facebook Page Reels / Video Uploader via Facebook Graph API
Path: src/fb_uploader.py
"""

import json
import logging
import os
from typing import Optional
import requests

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("FacebookUploader")


def upload_to_facebook_page(
    video_path: str,
    title: str,
    description: str,
    page_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[str]:
    """
    Publishes a vertical video directly to a Facebook Page as a Reel / Video via Meta Graph API.
    """
    if not page_id:
        page_id = os.environ.get("FB_PAGE_ID")
    if not access_token:
        access_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")

    if not page_id or not access_token:
        logger.info(
            "[FB-SKIP] Facebook credentials (FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN) not set. Skipping Facebook upload."
        )
        return None

    if not os.path.exists(video_path):
        logger.error(f"Video file not found for Facebook upload: {video_path}")
        return None

    logger.info(f"Uploading video to Facebook Page ID: {page_id}...")
    url = f"https://graph-video.facebook.com/v21.0/{page_id}/videos"

    clean_caption = (
        f"{title}\n\n"
        f"{description}\n\n"
        f"#reels #gaming #haihuoc #reviewgame #shorts"
    )

    data = {
        "access_token": access_token,
        "description": clean_caption,
        "title": title[:100],
    }

    try:
        with open(video_path, "rb") as video_file:
            files = {"source": video_file}
            response = requests.post(url, data=data, files=files, timeout=180)

        res_json = response.json()
        if response.status_code == 200 and "id" in res_json:
            fb_video_id = res_json["id"]
            logger.info(
                f"[SUCCESS] Video published to Facebook Page successfully! "
                f"Video ID: {fb_video_id} -> https://www.facebook.com/{page_id}/videos/{fb_video_id}"
            )
            return fb_video_id
        else:
            logger.error(f"Facebook Graph API Error (HTTP {response.status_code}): {res_json}")
            return None

    except Exception as e:
        logger.error(f"Unexpected error during Facebook video upload: {e}")
        return None
