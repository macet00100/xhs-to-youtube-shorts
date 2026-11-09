# 🚀 Xiaohongshu to YouTube Shorts 100% Automated Pipeline

Hệ thống tự động theo dõi kênh Xiaohongshu (Rednote) mục tiêu: **拧不动啊真拧不动** (`6542ed2b00000000300323af`), khi có video mới sẽ:
1. 📥 Tự động tải video gốc MP4 sạch (không logo watermark).
2. 🎙️ Sử dụng **Gemini Flash AI** bóc âm thanh tiếng Trung và dịch thẳng thành phụ đề tiếng Việt chuẩn thời gian (`.srt`).
3. 🎬 Sử dụng **FFmpeg** phủ dải mờ (*blur bar*) xóa sub tiếng Trung cũ và in phụ đề tiếng Việt viền đen chữ to chuẩn phong cách YouTube Shorts.
4. 📤 Tự động tải lên **YouTube Shorts** qua YouTube Data API v3 (tự gắn `#Shorts`, tiêu đề và mô tả tiếng Việt).
5. ☁️ **Chạy tự động 100% trên GitHub Actions** mỗi 30 phút mà không cần bật máy tính!

---

## 🛠️ Cài đặt & Chạy thử nghiệm trên máy tính

### 1. Cài đặt thư viện:
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Chạy thử nghiệm chế độ Dry-Run (không upload lên YouTube):
```bash
python main.py --dry-run
```

---

## 🔑 Hướng dẫn lấy 4 cấu hình GitHub Secrets để chạy 100% trên mây

Truy cập kho GitHub của bạn: **Settings** -> **Secrets and variables** -> **Actions** -> bấm **New repository secret** và thêm 5 biến sau:

### 1. `GEMINI_API_KEY` (Dùng để dịch giọng nói & phụ đề)
* Truy cập [Google AI Studio](https://aistudio.google.com/app/apikey).
* Bấm **Create API Key** (hoàn toàn miễn phí).
* Copy mã key dán vào secret `GEMINI_API_KEY`.

### 2. `XHS_COOKIE` (Dùng để tải video Xiaohongshu không bị chặn)
* Mở trình duyệt máy tính, truy cập [xiaohongshu.com](https://www.xiaohongshu.com) hoặc [rednote.com](https://www.rednote.com) và đăng nhập tài khoản của bạn.
* Bấm phím **F12** (Developer Tools) -> chuyển sang tab **Network** (Mạng).
* Tải lại trang (F5) -> bấm vào bất kỳ yêu cầu web nào -> nhìn sang mục **Request Headers** -> copy toàn bộ giá trị sau chữ `Cookie: ...`.
* Dán chuỗi đó vào secret `XHS_COOKIE`.

### 3. `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` (Dùng để tự upload YouTube Shorts)
* Truy cập [Google Cloud Console](https://console.cloud.google.com/).
* Tạo một dự án mới (Project).
* Vào mục **APIs & Services** -> **Library** -> tìm kiếm và bật **YouTube Data API v3**.
* Vào mục **OAuth consent screen** -> chọn **External** -> điền tên ứng dụng và thêm email của bạn vào danh sách **Test users**.
* Vào mục **Credentials** -> **Create Credentials** -> chọn **OAuth client ID** -> loại **Desktop app** -> bấm Create.
* Tải file JSON cấu hình về đổi tên thành `client_secrets.json` đặt vào thư mục dự án này.
* Mở terminal chạy lệnh xác thực 1 lần duy nhất:
  ```bash
  python src/auth_youtube_local.py --client-secrets client_secrets.json
  ```
  *(Trình duyệt sẽ mở lên để bạn cấp quyền cho kênh YouTube của mình. Sau khi xong, script sẽ in ra trực tiếp 3 giá trị `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` và `YOUTUBE_REFRESH_TOKEN` để bạn copy dán vào GitHub Secrets).*

---

## 📁 Cấu trúc thư mục

```
├── .github/workflows/
│   └── auto_reup.yml          # Lịch trình chạy tự động 30 phút/lần trên GitHub Actions
├── src/
│   ├── xhs_monitor.py         # Quét kênh Xiaohongshu & tải video sạch không watermark
│   ├── sub_translator.py      # Tách audio & dùng Gemini AI bóc sub dịch sang tiếng Việt
│   ├── video_processor.py     # FFmpeg che sub cũ & đè sub Việt chuẩn Shorts
│   ├── youtube_uploader.py    # Tự động đẩy video lên YouTube Shorts qua API
│   └── auth_youtube_local.py  # Script hỗ trợ lấy YouTube Refresh Token nhanh
├── history.json               # Lưu danh sách ID các video đã reup để không bị trùng lặp
├── main.py                    # File điều khiển luồng chạy chính
└── requirements.txt           # Danh sách các thư viện cần cài đặt
```
