"""
GitHub Releases を参照して新しいバージョンの公開を検知し、Windows通知で知らせるモジュール
起動時の自動確認と、設定画面などからの手動確認の両方から利用する
"""

import json
import os
import re
import threading
import time
import urllib.request
from enum import StrEnum

import lib.constants as constants
import lib.notifier as notifier
import lib.settings as settings
import lib.version as version

# 起動から自動確認までの待機秒数（起動通知との重なりや、PC起動直後のネットワーク未接続を避けるため）
STARTUP_CHECK_DELAY_SECONDS = 15

# GitHub API へのリクエストのタイムアウト秒数
REQUEST_TIMEOUT_SECONDS = 10

# 一度に取得するリリース件数（直近のbetaが続いても正式版を取りこぼさない件数）
RELEASES_FETCH_COUNT = 10

# リリース一覧を取得する GitHub API のURL（/releases/latest はPre-releaseを返さないため一覧APIを使う）
RELEASES_API_URL = f"https://api.github.com/repos/{constants.GITHUB_REPOSITORY}/releases?per_page={RELEASES_FETCH_COUNT}"

# 「v1.2.0」「v1.2.0-beta.1」形式のタグ名を、メジャー・マイナー・パッチ・beta番号に分解する正規表現
_VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")


class UpdateCheckMode(StrEnum):
    """アップデート確認の対象範囲。設定ファイル（notify.updateCheck）に保存する値として使用する。"""

    DISABLED = "disabled"
    STABLE = "stable"
    PRERELEASE = "prerelease"


def parse_version(tag):
    """
    タグ名を大小比較用のタプルに変換する
    同じバージョン番号では正式版がbeta版より新しくなるよう、4番目の要素に正式版=1・beta版=0を入れる

    Args:
        tag (str): タグ名（例: "v1.2.0"、"v1.2.0-beta.1"）

    Returns:
        tuple | None: (major, minor, patch, 正式版フラグ, beta番号)。形式が不正な場合は None
    """
    match = _VERSION_PATTERN.match(str(tag).strip())
    if match is None:
        return None

    major, minor, patch, beta_number = match.groups()
    if beta_number is None:
        return (int(major), int(minor), int(patch), 1, 0)
    return (int(major), int(minor), int(patch), 0, int(beta_number))


def find_latest_release(releases, include_prerelease):
    """
    リリース一覧から、確認対象となる最新バージョンのリリースを選ぶ
    一覧の並び順は作成日時順でバージョン順とは限らないため、タグ名を解析して最大のものを選ぶ

    Args:
        releases (list[dict]): GitHub API から取得したリリース情報のリスト
        include_prerelease (bool): Pre-release（beta版）も対象に含めるかどうか

    Returns:
        dict | None: 最新リリースの情報。対象が存在しない場合は None
    """
    # 1. 下書きと（対象外の場合は）Pre-release、タグ名を解析できないリリースを除外
    candidates = []
    for release in releases:
        if release.get("draft"):
            continue
        if release.get("prerelease") and not include_prerelease:
            continue
        parsed_version = parse_version(release.get("tag_name", ""))
        if parsed_version is None:
            continue
        candidates.append((parsed_version, release))

    # 2. 残ったリリースの中から最大バージョンのものを返す
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def _fetch_releases():
    """
    GitHub API からリリース一覧を取得する

    Returns:
        list[dict]: リリース情報のリスト

    Raises:
        Exception: 通信エラーやレスポンスの解析に失敗した場合
    """
    # GitHub API は User-Agent ヘッダーが無いリクエストを拒否するため明示する
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": constants.APP_NAME,
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def check_for_update(is_manual=False):
    """
    新しいバージョンが公開されているかを確認し、公開されていればWindows通知で知らせる
    メインプロセス・設定画面プロセスのどちらからも呼び出せる。通信を伴うため、UIから呼ぶ場合は別スレッドで実行する

    Args:
        is_manual (bool, optional): ユーザー操作による確認かどうか。
            True の場合は設定が「確認しない」でも正式版を対象に確認する。
            ただし通知の表示可否は各通知設定に従うため、「確認しない」設定では結果の通知は表示されない。

    Returns:
        str | None: 新しいバージョンのタグ名。新しいバージョンが無い場合や確認できなかった場合は None
    """
    # 1. 設定から確認対象の範囲を決定（自動確認で「確認しない」の場合は通信せずに終了）
    check_mode = settings.get("notify.updateCheck")
    if check_mode == UpdateCheckMode.DISABLED and not is_manual:
        return None
    include_prerelease = check_mode == UpdateCheckMode.PRERELEASE

    # 2. 実行中のバージョンを解析（開発環境でタグが取得できない場合などは比較できないため終了）
    current_version = parse_version(version.APP_VERSION)
    if current_version is None:
        notifier.log(f"現在のバージョン ({version.APP_VERSION}) を解析できないため、アップデートの確認を中止しました。")
        return None

    # 3. GitHub からリリース一覧を取得
    try:
        releases = _fetch_releases()
    except Exception as exception:
        # 自動確認時はオフライン環境で起動のたびに通知が出ないよう、ログ出力のみとする
        if is_manual:
            notifier.error("アップデートの確認に失敗しました。", f"リリース情報の取得に失敗しました。\n{exception}")
        else:
            notifier.log(f"アップデートの確認に失敗しました。\n{exception}")
        return None

    # 4. 最新リリースと現在のバージョンを比較
    latest_release = find_latest_release(releases, include_prerelease)
    if latest_release is None or parse_version(latest_release["tag_name"]) <= current_version:
        message = f"最新版を使用しています。({version.APP_VERSION})"
        if is_manual:
            notifier.notify(message, category=notifier.NotificationCategory.UPDATE)
        else:
            notifier.log(message)
        return None

    # 5. 新しいバージョンがあれば、リリースページを開くボタン付きで通知
    latest_tag = latest_release["tag_name"]
    notifier.notify(
        title=f"新しいバージョン ({latest_tag}) が公開されています。",
        message=f"現在のバージョン: {version.APP_VERSION}",
        buttons=[notifier.NotificationButton.OPEN_RELEASE_PAGE],
        category=notifier.NotificationCategory.UPDATE,
    )
    return latest_tag


def start_startup_check():
    """
    起動から一定時間後に、アップデートの自動確認を1回だけバックグラウンドで実行する
    """
    # テスト実行時は外部APIへの通信を発生させない
    if os.environ.get("EXIF_CAPTURE_TESTING") == "1":
        return

    def _delayed_check():
        time.sleep(STARTUP_CHECK_DELAY_SECONDS)
        check_for_update()

    threading.Thread(target=_delayed_check, daemon=True).start()
