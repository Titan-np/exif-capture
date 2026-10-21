"""
アプリケーション全体で使用する固定の定数定義
"""

# アプリケーション表示名
APP_NAME = "EXIF Capture"

# 設定画面の「このアプリについて」に表示する著作権表示
COPYRIGHT = "© 2026 Titan-np"

# 設定画面のタスクバーアイコンで使用するアプリケーションID（AUMID）
# 常駐側・通知の AUMID は APP_NAME を使う（変えるとスタートメニューのショートカットや Windows 側の通知設定との紐づけが切れるため）
APP_SETTINGS_USER_MODEL_ID = "exif_capture.settings"

# アップデート確認で参照する GitHub リポジトリ（所有者/リポジトリ名）
GITHUB_REPOSITORY = "Titan-np/exif-capture"

# GitHub リポジトリのURL（リリースページの組み立てと、設定画面のリンクに使う）
REPOSITORY_URL = f"https://github.com/{GITHUB_REPOSITORY}"
