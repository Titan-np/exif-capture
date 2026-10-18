"""
アプリケーション全体で使用する固定の定数定義
"""

# アプリケーション表示名
APP_NAME = "EXIF Capture"

# Windowsタスクバーや通知で使用するアプリケーションID（AUMID）
APP_USER_MODEL_ID = "exif_capture.app"
APP_SETTINGS_USER_MODEL_ID = "exif_capture.settings"

# アップデート確認で参照する GitHub リポジトリ（所有者/リポジトリ名）
GITHUB_REPOSITORY = "Titan-np/exif-capture"

# 新しいバージョンの通知から開くリリースページのURL
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"

# Windows の最大パス長（MAX_PATH 260 から終端文字分を引いた値）
WINDOWS_MAX_PATH_LENGTH = 259
