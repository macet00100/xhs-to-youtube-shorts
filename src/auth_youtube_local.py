"""
Helper Script: One-Time Local Authorization for YouTube Data API v3
Path: src/auth_youtube_local.py

Run this script once locally on your computer to obtain your YOUTUBE_REFRESH_TOKEN:
    python src/auth_youtube_local.py
    hoặc:
    python src/auth_youtube_local.py --client-secrets client_secrets.json
"""

import argparse
import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def update_env_file(key: str, value: str):
    """Appends or updates key-value in .env file."""
    lines = []
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    with open(".env", "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def main():
    parser = argparse.ArgumentParser(description="Authorize YouTube API and get Refresh Token.")
    parser.add_argument(
        "--client-secrets",
        default="client_secrets.json",
        help="Path to downloaded client_secrets.json from Google Cloud Console.",
    )
    parser.add_argument("--client-id", default=None, help="Google OAuth Client ID")
    parser.add_argument("--client-secret", default=None, help="Google OAuth Client Secret")
    args = parser.parse_args()

    client_id = args.client_id
    client_secret = args.client_secret

    if os.path.exists(args.client_secrets):
        print(f"[*] Tìm thấy file {args.client_secrets}, đang đọc thông tin OAuth...")
        with open(args.client_secrets, "r", encoding="utf-8") as f:
            data = json.load(f)
            client_info = data.get("installed") or data.get("web", {})
            client_id = client_info.get("client_id")
            client_secret = client_info.get("client_secret")
        flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, SCOPES)
    elif client_id and client_secret:
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    else:
        print("=" * 65)
        print("CHƯA CÓ FILE client_secrets.json HOẶC CLIENT ID/SECRET!")
        print("=" * 65)
        print("Bạn có thể nhập trực tiếp tại đây:")
        client_id = input("Nhập Client ID (kết thúc bằng .apps.googleusercontent.com): ").strip()
        client_secret = input("Nhập Client Secret: ").strip()
        if not client_id or not client_secret:
            print("Đã hủy xác thực. Vui lòng làm theo hướng dẫn trong README.md để lấy Client ID/Secret.")
            return

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    print("\n[*] Đang mở trình duyệt để bạn đăng nhập tài khoản Google / YouTube...")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    print("\n" + "=" * 65)
    print("XÁC THỰC YOUTUBE THÀNH CÔNG! (YOUTUBE AUTHORIZATION SUCCESSFUL)")
    print("=" * 65)
    print("Hãy copy 3 giá trị này lưu vào GitHub Repository Secrets:\n")
    print(f"YOUTUBE_CLIENT_ID     : {client_id}")
    print(f"YOUTUBE_CLIENT_SECRET : {client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN : {creds.refresh_token}")
    print("=" * 65)

    # Automatically save to local .env and token.json for immediate testing
    update_env_file("YOUTUBE_CLIENT_ID", client_id)
    update_env_file("YOUTUBE_CLIENT_SECRET", client_secret)
    update_env_file("YOUTUBE_REFRESH_TOKEN", creds.refresh_token)

    with open("token.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": creds.refresh_token,
            },
            f,
            indent=2,
        )
    print("[*] Đã tự động cập nhật vào file .env và token.json trên máy của bạn!")


if __name__ == "__main__":
    main()
