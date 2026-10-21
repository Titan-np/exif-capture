"""
アプリケーションのバージョン情報を動的に解決し、タグ名の形式を解析するモジュール
ビルド成果物（exe）実行時とローカル開発環境実行時で適切なバージョン文字列を取得する
"""

import os
import re
import subprocess

import lib.paths as paths

# バージョン情報が取得できなかった場合の代替文字列
FALLBACK_VERSION = "バージョン番号取得失敗"


def get_app_version() -> str:
    """
    アプリケーションのバージョン文字列を取得する

    優先順位:
    1. ビルド時に埋め込まれた _version.py（exe実行時のみ）
    2. CI環境（GitHub Actions等）で渡される環境変数
    3. Gitコマンドによる直近のタグ名（開発環境でのスクリプト直接実行時）
    4. フォールバック定数文字列（GitタグやGit環境が存在しない場合）

    Returns:
        str: バージョン文字列（例: "v1.1.2-beta.1"、失敗時は "バージョン番号取得失敗"）
    """
    # 1. exe実行時は、ビルド時にPyInstallerバンドル対象として自動生成されたファイルを最優先で参照
    # （ビルド中断で src/_version.py が残っても、開発時に古いバージョンを拾わないよう exe 実行時に限定する）
    if paths.is_executable():
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
        # リポジトリルートを取得
        repository_root_path = paths.resolve_app_relative_path()

        # 引数をリストで渡すため cmd.exe は経由せず、git を直接起動する
        # コンソールの無い pythonw 実行時に git のコンソールウィンドウが一瞬表示されないよう、CREATE_NO_WINDOW を指定する
        git_command = ["git", "describe", "--tags", "--abbrev=0"]
        execution_result = subprocess.run(
            git_command,
            cwd=repository_root_path,
            capture_output=True,
            text=True,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        tag_name = execution_result.stdout.strip()
        if tag_name:
            return tag_name
    except Exception:
        # Gitが未インストール、タグが存在しない、または.gitが存在しない環境などのエラー時はフォールバックへ流す
        pass

    # 4. すべての取得手段に失敗した場合は固定のフォールバック値を返却
    return FALLBACK_VERSION


def parse_version(tag):
    """
    タグ名を大小比較用のタプルに変換する
    同じバージョン番号では正式版がbeta版より新しくなるよう、4番目の要素に正式版=1・beta版=0を入れる
    アップデート確認での比較と、ビルド時のタグ名の形式チェック（tools/build.py）の双方で使う

    Args:
        tag (str): タグ名（例: "v1.2.0"、"v1.2.0-beta.1"）

    Returns:
        tuple | None: (major, minor, patch, 正式版フラグ, beta番号)。形式が不正な場合は None
    """
    # 1. 「v1.2.0」「v1.2.0-beta.1」形式のタグ名を、メジャー・マイナー・パッチ・beta番号に分解する
    match = re.match(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$", str(tag).strip())
    if match is None:
        return None

    # 2. 正式版は beta 番号を持たないため、正式版フラグを1、beta番号を0として返す
    major, minor, patch, beta_number = match.groups()
    if beta_number is None:
        return (int(major), int(minor), int(patch), 1, 0)
    return (int(major), int(minor), int(patch), 0, int(beta_number))


# 外部から簡単に参照できるよう、モジュール読み込み時に解決したバージョン文字列を定数として公開
APP_VERSION = get_app_version()
