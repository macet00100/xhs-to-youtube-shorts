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
import subprocess
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
    order: str = "oldest_first",
) -> Optional[Dict]:
    """
    Checks the target creator's profile, identifies unprocessed videos,
    selects target video according to strategy (oldest_first or newest_first),
    downloads the watermark-free MP4, and returns the video metadata.
    """
    os.makedirs(output_dir, exist_ok=True)
    order = os.environ.get("REUP_ORDER", order)
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

        # Intercept user_posted API to capture full catalogue of creator videos
        all_api_notes = []
        has_more_flag = True

        async def handle_user_posted(res):
            nonlocal has_more_flag
            if "user_posted" in res.url:
                try:
                    data = await res.json()
                    if data.get("success") and "data" in data:
                        notes = data["data"].get("notes", [])
                        has_more_flag = data["data"].get("has_more", False)
                        all_api_notes.extend(notes)
                except Exception:
                    pass

        page.on("response", handle_user_posted)

        logger.info(f"Visiting Rednote creator profile: {profile_url}")
        try:
            await page.goto(profile_url, wait_until="networkidle", timeout=35000)
        except Exception as e:
            logger.warning(f"Initial navigation warning: {e}")

        await page.wait_for_timeout(2500)

        # Scroll dynamically using mouse wheel to trigger all user_posted batches
        logger.info("Scanning complete channel backlog via infinite scroll...")
        last_note_count = 0
        consecutive_idle = 0
        for scroll_i in range(50):
            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(1000)
            cur_count = len(all_api_notes)
            if cur_count == last_note_count:
                consecutive_idle += 1
                if (not has_more_flag and consecutive_idle >= 2) or consecutive_idle >= 5:
                    break
            else:
                consecutive_idle = 0
                last_note_count = cur_count

        logger.info(f"Total notes captured from channel API: {len(all_api_notes)}")

        # Deduplicate and extract video items
        unprocessed_items = []
        seen_ids = set()

        if all_api_notes:
            for n in all_api_notes:
                nid = n.get("note_id")
                if not nid or nid in seen_ids:
                    continue
                seen_ids.add(nid)

                # Filter video posts only
                if n.get("type") != "video":
                    continue

                title = (n.get("display_title") or n.get("title") or "").strip()
                if not title:
                    title = f"video_{nid}"

                if nid in processed_ids or title in processed_ids:
                    continue

                cover_info = n.get("cover") or {}
                cover_url = cover_info.get("url_default") or cover_info.get("url_pre") or cover_info.get("url", "")

                unprocessed_items.append({
                    "note_id": nid,
                    "title": title,
                    "cover_url": cover_url,
                    "xsec_token": n.get("xsec_token", ""),
                    "time": n.get("time", 0),
                })
        else:
            # Fallback to scraping visible DOM cards if API intercept was empty
            logger.warning("API intercept was empty, falling back to DOM cards...")
            cards = await page.query_selector_all("section.note-item")
            for idx, card in enumerate(cards):
                is_video = await card.query_selector(".play-icon")
                if not is_video:
                    continue
                title_el = await card.query_selector(".footer .title span, .footer .title")
                title_text = (await title_el.inner_text()).strip() if title_el else f"video_{idx}"
                cover_a = await card.query_selector("a.cover")
                href = (await cover_a.get_attribute("href")) if cover_a else ""
                img_el = await card.query_selector("img")
                cover_url = (await img_el.get_attribute("src")) if img_el else ""
                m = re.search(r"/explore/([a-zA-Z0-9]+)", href)
                note_id = m.group(1) if m else hashlib.md5(title_text.encode("utf-8")).hexdigest()[:16]

                if note_id in processed_ids or title_text in processed_ids:
                    continue

                unprocessed_items.append({
                    "note_id": note_id,
                    "title": title_text,
                    "cover_url": cover_url,
                    "xsec_token": "",
                    "time": 0,
                })

        if not unprocessed_items:
            logger.info("No new video posts found to process. All channel videos are up to date!")
            await browser.close()
            return None

        logger.info(f"Found {len(unprocessed_items)} unprocessed videos in channel backlog.")

        # Select target video according to strategy (oldest_first by default)
        if order == "oldest_first":
            target_info = unprocessed_items[-1]
            logger.info(f"[OLDEST FIRST] Selected oldest unprocessed video: '{target_info['title']}' (ID: {target_info['note_id']})")
        else:
            target_info = unprocessed_items[0]
            logger.info(f"[NEWEST FIRST] Selected newest unprocessed video: '{target_info['title']}' (ID: {target_info['note_id']})")

        # Navigate directly to target video detail page
        xsec = target_info.get("xsec_token", "")
        detail_url = (
            f"https://www.rednote.com/explore/{target_info['note_id']}?xsec_token={xsec}&xsec_source=pc_user"
            if xsec else f"https://www.rednote.com/explore/{target_info['note_id']}"
        )
        logger.info(f"Opening video detail page: {detail_url}...")
        captured_mp4_urls.clear()

        try:
            await page.goto(detail_url, wait_until="networkidle", timeout=35000)
        except Exception as e:
            logger.warning(f"Direct note navigation warning: {e}")

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
