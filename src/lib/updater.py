"""
GitHub Releases を参照して新しいバージョンの公開を検知し、Windows通知で知らせるモジュール
起動時の自動確認と、設定画面の「今すぐ確認」ボタンの両方から利用する
"""

import json
import threading
import time
import urllib.request
from enum import StrEnum
from typing import NamedTuple

import lib.constants as constants
import lib.notifier as notifier
import lib.settings as settings
import lib.version as version


class UpdateCheckMode(StrEnum):
    """アップデート確認の対象範囲。設定ファイル（update.checkMode）に保存する値として使用する。"""

    DISABLED = "disabled"
    STABLE = "stable"
    PRERELEASE = "prerelease"


class LatestRelease(NamedTuple):
    """確認範囲で公開中の最新リリースと、実行中のバージョンより新しいかの組"""

    tag: str  # 最新リリースのタグ名
    is_newer: bool  # 実行中のバージョンより新しい場合は True


# 取得済みのリリース一覧（未取得の間は None）
# 一覧には正式版と Pre-release（beta版）の両方が含まれるため、確認範囲を変えるたびに取得し直さず、この一覧から選び直す
_cached_releases = None


def _fetch_releases():
    """
    GitHub API からリリース一覧を取得する（get_latest_release() の通信部分。テストで通信を差し替えるため分けている）

    Returns:
        list[dict]: リリース情報のリスト

    Raises:
        Exception: 通信エラーやレスポンスの解析に失敗した場合
    """
    # 一度に取得するリリース件数（直近のbetaが続いても正式版を取りこぼさない件数）
    RELEASES_FETCH_COUNT = 10
    # リリース一覧を取得する GitHub API のURL（/releases/latest はPre-releaseを返さないため一覧APIを使う）
    RELEASES_API_URL = f"https://api.github.com/repos/{constants.GITHUB_REPOSITORY}/releases?per_page={RELEASES_FETCH_COUNT}"
    # GitHub API へのリクエストのタイムアウト秒数
    REQUEST_TIMEOUT_SECONDS = 10

    # 1. リクエストを作成する（GitHub API は User-Agent ヘッダーが無いリクエストを拒否するため明示する）
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": constants.APP_NAME,
        },
    )

    # 2. リリース一覧を取得し、JSON を解析して返す
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def get_latest_release(include_prerelease, refetch=False):
    """
    確認範囲（正式版のみ / beta版も含む）で公開中の最新リリースと、それが実行中のバージョンより新しいかを取得する
    新しいバージョンが無い場合も、比べた相手（公開中の最新版）を表示できるよう、タグ名を返す
    リリース一覧は、未取得の場合か refetch=True の場合だけ GitHub から取得し、それ以外は取得済みの一覧から選び直す（通信しない）
    結果の伝え方は呼び出し元（起動時の自動確認・設定画面）で異なるため、通知やログ出力は行わない
    取得する場合は通信を伴うため、UIから呼ぶ場合は別スレッドで実行する

    Args:
        include_prerelease (bool): Pre-release（beta版）も対象に含めるかどうか
        refetch (bool, optional): 取得済みでも GitHub から取得し直す場合は True

    Returns:
        LatestRelease | None: 最新リリースのタグ名と、実行中のバージョンより新しいか。確認範囲にリリースが無い場合は None

    Raises:
        ValueError: 実行中のバージョンを解析できない場合
        Exception: リリース一覧の取得に失敗した場合
    """
    global _cached_releases

    # 1. 実行中のバージョンを解析（開発環境でタグが取得できない場合などは比較できないため、通信せずに中止）
    current_version = version.parse_version(version.APP_VERSION)
    if current_version is None:
        raise ValueError(f"現在のバージョン ({version.APP_VERSION}) を解析できません。")

    # 2. 未取得の場合か、取得し直す指定がある場合だけ、GitHub からリリース一覧を取得して保持する
    if _cached_releases is None or refetch:
        _cached_releases = _fetch_releases()

    # 3. 下書きと（対象外の場合は）Pre-release、タグ名を解析できないリリースを除き、最大バージョンを選ぶ
    # 一覧の並び順は作成日時順でバージョン順とは限らないため、タグ名を解析して比較する
    candidate_versions = {}
    for release in _cached_releases:
        if release.get("draft"):
            continue
        if release.get("prerelease") and not include_prerelease:
            continue
        parsed_version = version.parse_version(release.get("tag_name", ""))
        if parsed_version is not None:
            candidate_versions[release["tag_name"]] = parsed_version

    # 4. 最大バージョンのタグ名と、実行中のバージョンより新しいかを返す
    if not candidate_versions:
        return None
    latest_tag = max(candidate_versions, key=candidate_versions.get)
    return LatestRelease(tag=latest_tag, is_newer=candidate_versions[latest_tag] > current_version)


def notify_update(delay_seconds):
    """
    指定した秒数待ってから、設定に従って新しいバージョンを確認し、公開されていればWindows通知で知らせる
    起動処理を止めないよう、バックグラウンドのスレッドで実行する

    Args:
        delay_seconds (float): 確認を始めるまでの待機秒数
    """

    def _check_and_notify():
        # 1. 指定した秒数待つ
        time.sleep(delay_seconds)

        # 2. 設定から確認対象の範囲を決定（「確認しない」の場合は通信せずに終了）
        check_mode = settings.get("update.checkMode")
        if check_mode == UpdateCheckMode.DISABLED:
            return

        # 3. 新しいバージョンを確認（オフライン環境で起動のたびに通知が出ないよう、失敗・最新時はログ出力のみとする）
        try:
            latest_release = get_latest_release(include_prerelease=check_mode == UpdateCheckMode.PRERELEASE)
        except Exception as exception:
            notifier.log(f"アップデートの確認に失敗しました。\n{exception}")
            return
        if latest_release is None or not latest_release.is_newer:
            # 何と比べたかを後から確認できるよう、公開中の最新版も記録する
            latest_tag_text = latest_release.tag if latest_release else "なし"
            notifier.log(f"新しいバージョンはありません。(現在: {version.APP_VERSION} / 最新: {latest_tag_text})")
            return

        # 4. 新しいバージョンがあれば、そのバージョンのリリースページを開くボタン付きで通知
        notifier.notify(
            category=notifier.NotificationCategory.UPDATE,
            title=f"新しいバージョン ({latest_release.tag}) が公開されています。",
            message=f"現在のバージョン: {version.APP_VERSION}",
            buttons=[notifier.NotificationButton.OPEN_RELEASE_PAGE],
            release_page_url=get_release_page_url(latest_release.tag),
        )

    threading.Thread(target=_check_and_notify, daemon=True).start()


def get_release_page_url(tag):
    """
    指定したバージョンのリリースページのURLを取得する
    リリース一覧には Pre-release も並ぶため、検知したバージョンのページを直接開けるようにする

    Args:
        tag (str): タグ名（例: "v1.2.0"）

    Returns:
        str: リリースページのURL
    """
    return f"{constants.REPOSITORY_URL}/releases/tag/{tag}"
