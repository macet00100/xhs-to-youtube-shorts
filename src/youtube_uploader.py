"""
Module: Automated YouTube Shorts Uploader via YouTube Data API v3
Path: src/youtube_uploader.py
"""

import json
import logging
import os
from typing import Dict, List, Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from src.video_processor import get_video_info

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("YouTubeUploader")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_youtube_service():
    """Initializes authorized YouTube Data API service from environment variables or credentials file."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    # Or read from a JSON secret string if set as YOUTUBE_SECRETS_JSON
    secrets_json = os.environ.get("YOUTUBE_SECRETS_JSON")
    if secrets_json:
        try:
            data = json.loads(secrets_json)
            client_id = data.get("client_id", client_id)
            client_secret = data.get("client_secret", client_secret)
            refresh_token = data.get("refresh_token", refresh_token)
        except Exception:
            pass

    if not (client_id and client_secret and refresh_token):
        logger.warning(
            "YouTube API credentials missing (YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN). "
            "Running in DRY-RUN mode."
        )
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds)


def upload_to_youtube_shorts(
    video_path: str,
    title: str,
    description: str,
    tags: Optional[List[str]] = None,
    thumbnail_path: Optional[str] = None,
    privacy_status: str = "public",
    is_short: Optional[bool] = None,
) -> Optional[str]:
    """Uploads MP4 video to YouTube with automatic detection of Shorts vs Long-form video."""
    if is_short is None:
        try:
            info = get_video_info(video_path)
            is_short = info.get("is_short", False)
            logger.info(
                f"Video specs: {info['width']}x{info['height']}, duration: {info['duration']:.1f}s -> "
                f"Classification: {'YouTube Short (Dọc/Vuông <= 180s)' if is_short else 'Long-form Video (Video dài / ngang)'}"
            )
        except Exception as e:
            logger.warning(f"Could not inspect video dimensions: {e}. Defaulting to is_short=False")
            is_short = False

    clean_title = title.replace("#Shorts", "").replace("#shorts", "").strip()

    if is_short:
        # YouTube Shorts: Gắn hashtag #Shorts
        if len(clean_title) > 90:
            clean_title = clean_title[:88] + "..."
        final_title = f"{clean_title} #Shorts"
        final_desc = (
            f"{description}\n\n"
            f"---\n"
            f"#Shorts #gaming #haihuoc #review #game"
        )
        if tags is None:
            tags = ["shorts", "short", "gaming", "funny", "game", "haihuoc", "giaitri", "reviewgame"]
    else:
        # Long-form video (Video dài hoặc ngang): KHÔNG gắn #Shorts vào title hay description!
        if len(clean_title) > 98:
            clean_title = clean_title[:95] + "..."
        final_title = clean_title
        final_desc = (
            f"{description}\n\n"
            f"---\n"
            f"#gaming #haihuoc #reviewgame #hoathinh3d #phimhoathinh #game"
        )
        if tags is None:
            tags = ["gaming", "game", "haihuoc", "giaitri", "reviewgame", "hoathinh3d", "phimhoathinh", "video hay"]

    service = get_youtube_service()
    if not service:
        logger.info(f"[DRY-RUN] Would upload '{final_title}' to YouTube ({privacy_status}, is_short={is_short}).")
        return "DRY_RUN_VIDEO_ID"

    body = {
        "snippet": {
            "title": final_title,
            "description": final_desc,
            "tags": tags,
            "categoryId": "20",  # Gaming
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")

    logger.info(f"Uploading to YouTube Shorts: '{final_title}'...")
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = request.execute()
    video_id = response.get("id")
    logger.info(f"Successfully published to YouTube Shorts! URL: https://youtu.be/{video_id}")

    # Set custom thumbnail if generated
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            logger.info(f"Setting custom thumbnail for YouTube video {video_id}...")
            service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            logger.info("Custom thumbnail uploaded successfully!")
        except Exception as e:
            logger.info(f"Custom thumbnail skipped (channel may require verified phone number for custom thumbs): {e}")

    return video_id
