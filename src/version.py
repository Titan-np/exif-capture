"""
アプリケーションのバージョン情報を動的に解決するモジュール
ビルド成果物（exe）実行時とローカル開発環境実行時で適切なバージョン文字列を取得する
"""

import os
import subprocess
import sys

# バージョン情報が取得できなかった場合の代替文字列
FALLBACK_VERSION = "バージョン番号取得失敗"


def get_app_version() -> str:
    """
    アプリケーションのバージョン文字列を取得する

    優先順位:
    1. ビルド時に埋め込まれた _version.py（exe実行時およびビルド直後）
    2. CI環境（GitHub Actions等）で渡される環境変数
    3. Gitコマンドによる直近のタグ名（開発環境でのスクリプト直接実行時）
    4. フォールバック定数文字列（GitタグやGit環境が存在しない場合）

    Returns:
        str: バージョン文字列（例: "v1.1.2-beta.1"、失敗時は "バージョン番号取得失敗"）
    """
    # 1. ビルド時にPyInstallerバンドル対象として自動生成されたファイルが存在すれば最優先で参照
    try:
        from _version import APP_VERSION as EMBEDDED_VERSION

        return EMBEDDED_VERSION
    except ImportError:
        pass

    # 2. GitHub Actions等のCI環境で環境変数が指定されている場合はそれを参照
    environment_version = os.environ.get("GITHUB_REF_NAME") or os.environ.get("EXIF_CAPTURE_VERSION")
    if environment_version:
        return environment_version.strip()

    # 3. 開発環境での直接実行時は、ローカルGitリポジトリから直近のタグ名を取得
    try:
        # srcフォルダの親ディレクトリ（リポジトリルート）を取得
        script_directory_path = os.path.dirname(os.path.abspath(__file__))
        repository_root_path = os.path.dirname(script_directory_path)

        git_command = ["git", "describe", "--tags", "--abbrev=0"]
        execution_result = subprocess.run(
            git_command,
            cwd=repository_root_path,
            capture_output=True,
            text=True,
            check=True,
            shell=True,
        )
        tag_name = execution_result.stdout.strip()
        if tag_name:
            return tag_name
    except Exception:
        # Gitが未インストール、タグが存在しない、または.gitが存在しない環境などのエラー時はフォールバックへ流す
        pass

    # 4. すべての取得手段に失敗した場合は固定のフォールバック値を返却
    return FALLBACK_VERSION


# 外部から簡単に参照できるよう、モジュール読み込み時に解決したバージョン文字列を定数として公開
APP_VERSION = get_app_version()
