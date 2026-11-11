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
    Supports both direct upload and Chunked Resumable Upload (for large videos).
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

    file_size = os.path.getsize(video_path)
    logger.info(f"Uploading video ({file_size / 1024 / 1024:.2f} MB) to Facebook Page ID: {page_id}...")

    clean_caption = (
        f"{title}\n\n"
        f"{description}\n\n"
        f"#reels #gaming #haihuoc #reviewgame #shorts"
    )

    # Use Resumable Chunked Upload for files >= 20 MB or when direct upload fails
    if file_size >= 20 * 1024 * 1024:
        return _upload_resumable(video_path, file_size, title, clean_caption, page_id, access_token)

    # Direct single-POST upload for small files (< 20 MB)
    url = f"https://graph-video.facebook.com/v21.0/{page_id}/videos"
    data = {
        "access_token": access_token,
        "description": clean_caption,
        "title": title[:100],
    }

    try:
        with open(video_path, "rb") as video_file:
            files = {"source": video_file}
            response = requests.post(url, data=data, files=files, timeout=180)

        if response.status_code == 200:
            res_json = response.json()
            fb_video_id = res_json.get("id")
            if fb_video_id:
                logger.info(
                    f"[SUCCESS] Video published to Facebook Page successfully! "
                    f"Video ID: {fb_video_id} -> https://www.facebook.com/{page_id}/videos/{fb_video_id}"
                )
                return fb_video_id

        if response.status_code == 413:
            logger.info("Direct upload returned HTTP 413 (Payload Too Large). Falling back to Resumable Chunked Upload...")
            return _upload_resumable(video_path, file_size, title, clean_caption, page_id, access_token)

        logger.error(f"Facebook Graph API Error (HTTP {response.status_code}): {response.text[:300]}")
        return None

    except Exception as e:
        logger.warning(f"Direct Facebook upload failed: {e}. Trying resumable upload...")
        return _upload_resumable(video_path, file_size, title, clean_caption, page_id, access_token)


def _upload_resumable(
    video_path: str,
    file_size: int,
    title: str,
    caption: str,
    page_id: str,
    access_token: str,
) -> Optional[str]:
    """Uploads large video using Meta Graph API Resumable Chunked Upload protocol."""
    try:
        # Phase 1: Start
        start_url = f"https://graph.facebook.com/v21.0/{page_id}/videos"
        r_start = requests.post(
            start_url,
            data={"upload_phase": "start", "file_size": file_size, "access_token": access_token},
            timeout=60,
        )
        if r_start.status_code != 200:
            logger.error(f"Resumable upload start phase failed ({r_start.status_code}): {r_start.text}")
            return None

        start_data = r_start.json()
        upload_session_id = start_data.get("upload_session_id")
        video_id = start_data.get("video_id")
        start_offset = int(start_data.get("start_offset", 0))
        end_offset = int(start_data.get("end_offset", file_size))

        logger.info(f"Resumable upload session started. Session ID: {upload_session_id}, Video ID: {video_id}")

        # Phase 2: Transfer Chunks
        transfer_url = f"https://graph-video.facebook.com/v21.0/{page_id}/videos"
        with open(video_path, "rb") as f:
            while start_offset < file_size:
                f.seek(start_offset)
                chunk_len = end_offset - start_offset
                chunk_data = f.read(chunk_len)

                r_tr = requests.post(
                    transfer_url,
                    data={
                        "upload_phase": "transfer",
                        "upload_session_id": upload_session_id,
                        "start_offset": start_offset,
                        "access_token": access_token,
                    },
                    files={"video_file_chunk": ("chunk.mp4", chunk_data, "application/octet-stream")},
                    timeout=180,
                )
                if r_tr.status_code != 200:
                    logger.error(f"Chunk transfer failed at offset {start_offset}: {r_tr.text}")
                    return None

                tr_data = r_tr.json()
                new_start = int(tr_data.get("start_offset", file_size))
                new_end = int(tr_data.get("end_offset", file_size))
                if new_start == start_offset:
                    logger.error("No progress made in chunk transfer. Aborting.")
                    return None
                start_offset = new_start
                end_offset = new_end

        # Phase 3: Finish
        finish_url = f"https://graph.facebook.com/v21.0/{page_id}/videos"
        r_finish = requests.post(
            finish_url,
            data={
                "upload_phase": "finish",
                "upload_session_id": upload_session_id,
                "title": title[:100],
                "description": caption,
                "access_token": access_token,
            },
            timeout=60,
        )
        if r_finish.status_code == 200 and r_finish.json().get("success"):
            logger.info(
                f"[SUCCESS] Resumable video upload completed! "
                f"Video ID: {video_id} -> https://www.facebook.com/{page_id}/videos/{video_id}"
            )
            return video_id
        else:
            logger.error(f"Resumable upload finish phase failed ({r_finish.status_code}): {r_finish.text}")
            return None

    except Exception as e:
        logger.error(f"Exception during resumable Facebook video upload: {e}")
        return None
