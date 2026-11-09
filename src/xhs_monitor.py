"""
Module: Xiaohongshu (Rednote) Channel Monitor & Video Downloader
Path: src/xhs_monitor.py
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import urllib.request
from typing import Dict, List, Optional
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("XhsMonitor")

TARGET_PROFILE_URL = "https://www.rednote.com/user/profile/6542ed2b00000000300323af"


def parse_cookie_input(cookie_input: str) -> List[Dict]:
    """Parses Netscape cookie file, raw string, or environment variable into Playwright cookie objects."""
    cookies = []
    if not cookie_input:
        return cookies

    content = cookie_input
    # Check if input is a path to an existing cookie file
    if os.path.exists(cookie_input):
        try:
            with open(cookie_input, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Error reading cookie file {cookie_input}: {e}")

    # If Netscape HTTP Cookie format (tab-separated lines), parse lines
    if "\t" in content:
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain = parts[0]
                name = parts[5].strip()
                val = parts[6].strip()
                for d in [domain, ".rednote.com", ".xiaohongshu.com"]:
                    cookies.append({
                        "name": name,
                        "value": val,
                        "domain": d,
                        "path": parts[2] or "/",
                    })
        return cookies

    # Standard 'name=value; ...' string parsing
    items = content.split(";")
    for item in items:
        if "=" in item:
            name, value = item.strip().split("=", 1)
            name = name.strip()
            value = value.strip()
            if name:
                for domain in [".rednote.com", ".xiaohongshu.com"]:
                    cookies.append({
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": "/",
                    })
    return cookies


async def check_and_download_latest_video(
    profile_url: str = TARGET_PROFILE_URL,
    history_file: str = "history.json",
    output_dir: str = "temp",
    cookie_str: Optional[str] = None,
) -> Optional[Dict]:
    """
    Checks the target creator's profile, identifies the newest video not in history.json,
    downloads the watermark-free MP4, and returns the video metadata.
    """
    os.makedirs(output_dir, exist_ok=True)
    processed_ids = set()
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("processed_notes", []):
                    processed_ids.add(str(item.get("note_id")))
                    processed_ids.add(str(item.get("title")))
        except Exception as e:
            logger.warning(f"Could not read {history_file}: {e}")

    logger.info(f"Loaded {len(processed_ids)} already processed items from history.")

    # Retrieve cookie from argument, local file, or environment variable
    if not cookie_str:
        if os.path.exists("www.rednote.com_cookies.txt"):
            cookie_str = "www.rednote.com_cookies.txt"
        elif os.path.exists("cookies.txt"):
            cookie_str = "cookies.txt"
        else:
            cookie_str = os.environ.get("XHS_COOKIE", "")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )

        parsed_cookies = parse_cookie_input(cookie_str)
        if parsed_cookies:
            logger.info(f"Injecting {len(parsed_cookies)} session cookies into browser context...")
            await context.add_cookies(parsed_cookies)

        page = await context.new_page()

        # Intercept real MP4 media streams from CDN (ignore blob: URLs)
        captured_mp4_urls = []

        def handle_network(item):
            try:
                url = item.url
                if (".mp4" in url or "sns-video" in url or "/stream/" in url) and not url.startswith("blob:"):
                    clean_url = url.split("?")[0] if ("range=" in url or "bytes=" in url) else url
                    if clean_url.startswith("http") and clean_url not in captured_mp4_urls:
                        captured_mp4_urls.append(clean_url)
            except Exception:
                pass

        page.on("response", handle_network)
        page.on("request", handle_network)

        logger.info(f"Visiting Rednote creator profile: {profile_url}")
        try:
            await page.goto(profile_url, wait_until="networkidle", timeout=35000)
        except Exception as e:
            logger.warning(f"Initial navigation warning: {e}")

        await page.wait_for_timeout(3000)

        # Inspect note cards
        cards = await page.query_selector_all("section.note-item")
        logger.info(f"Found {len(cards)} note cards on channel profile.")

        target_card = None
        target_info = None

        for idx, card in enumerate(cards):
            # Check if this card has a play icon (is a video)
            is_video = await card.query_selector(".play-icon")
            title_el = await card.query_selector(".footer .title span, .footer .title")
            title_text = (await title_el.inner_text()).strip() if title_el else f"video_{idx}"

            # Check cover link or unique tokens
            cover_a = await card.query_selector("a.cover")
            href = (await cover_a.get_attribute("href")) if cover_a else ""

            # Check cover image URL
            img_el = await card.query_selector("img")
            cover_url = (await img_el.get_attribute("src")) if img_el else ""

            # Extract note ID from href or hash of title
            m = re.search(r"/explore/([a-zA-Z0-9]+)", href)
            note_id = m.group(1) if m else hashlib.md5(title_text.encode("utf-8")).hexdigest()[:16]

            if not is_video:
                continue

            if note_id in processed_ids or title_text in processed_ids:
                logger.info(f"Card #{idx} ('{title_text}') already processed. Skipping.")
                continue

            logger.info(f"Found NEW unprocessed video: '{title_text}' (ID: {note_id})")
            target_card = card
            target_info = {
                "note_id": note_id,
                "title": title_text,
                "href": href,
                "cover_url": cover_url,
            }
            break

        if not target_card or not target_info:
            logger.info("No new video posts found to process. Channel is up to date!")
            await browser.close()
            return None

        # Click into target video note to reveal the player
        logger.info(f"Opening video detail for: {target_info['title']}...")
        captured_mp4_urls.clear()

        try:
            # Click card directly or cover anchor
            cover = await target_card.query_selector("a.cover, .cover")
            if cover:
                await cover.click(force=True)
            else:
                await target_card.click(force=True)
        except Exception as e:
            logger.warning(f"Click trigger note: {e}")

        # Wait up to 10 seconds for real video stream request to be captured
        for _ in range(20):
            if captured_mp4_urls:
                break
            await page.wait_for_timeout(500)

        # 1. Pick from captured network responses (guaranteed clean stream)
        video_src = None
        for u in captured_mp4_urls:
            if u.startswith("http") and not u.startswith("blob:"):
                video_src = u
                break

        # 2. Fallback to video tag src if not captured yet
        if not video_src:
            try:
                video_el = await page.query_selector("video")
                if video_el:
                    src = await video_el.get_attribute("src")
                    if src and src.startswith("http") and not src.startswith("blob:"):
                        video_src = src
                    else:
                        source_el = await video_el.query_selector("source")
                        if source_el:
                            src_s = await source_el.get_attribute("src")
                            if src_s and src_s.startswith("http") and not src_s.startswith("blob:"):
                                video_src = src_s
            except Exception:
                pass

        # Extract full description if available
        desc_text = ""
        try:
            desc_el = await page.query_selector("#detail-desc, .desc")
            if desc_el:
                desc_text = (await desc_el.inner_text()).strip()
        except Exception:
            pass

        # Also update note_id if page URL has real /explore/ ID
        current_url = page.url
        m_curr = re.search(r"/explore/([a-zA-Z0-9]+)", current_url)
        if m_curr:
            target_info["note_id"] = m_curr.group(1)

        await browser.close()

        if not video_src:
            logger.error(
                "Could not extract direct video MP4 URL. If a login popup appeared, "
                "please ensure XHS_COOKIE is set with valid session cookies."
            )
            return None

        logger.info(f"Found clean MP4 stream: {video_src[:90]}...")
        raw_video_path = os.path.join(output_dir, f"xhs_{target_info['note_id']}.mp4")

        # Download clean MP4 file
        req = urllib.request.Request(
            video_src,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.rednote.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp, open(raw_video_path, "wb") as out_f:
            out_f.write(resp.read())

        file_sz = os.path.getsize(raw_video_path)
        logger.info(f"Successfully downloaded clean video: {raw_video_path} ({file_sz / 1024 / 1024:.2f} MB)")

        # Download or extract thumbnail cover
        cover_path = os.path.join(output_dir, f"cover_{target_info['note_id']}.jpg")
        cover_url = target_info.get("cover_url", "")
        if cover_url and cover_url.startswith("http"):
            try:
                req_cov = urllib.request.Request(
                    cover_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Referer": "https://www.rednote.com/",
                    },
                )
                with urllib.request.urlopen(req_cov, timeout=20) as c_resp, open(cover_path, "wb") as c_out:
                    c_out.write(c_resp.read())
                logger.info(f"Downloaded XHS cover image -> {cover_path}")
            except Exception as e:
                logger.warning(f"Error downloading cover image: {e}")

        # Fallback thumbnail: 1.5-second frame from clean video
        if not os.path.exists(cover_path) or os.path.getsize(cover_path) == 0:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-ss", "00:00:01.500", "-i", raw_video_path, "-vframes", "1", "-q:v", "2", cover_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        return {
            "note_id": target_info["note_id"],
            "title": target_info["title"],
            "desc": desc_text or target_info["title"],
            "video_path": raw_video_path,
            "cover_path": cover_path,
        }


if __name__ == "__main__":
    res = asyncio.run(check_and_download_latest_video())
    print("Result:", res)
