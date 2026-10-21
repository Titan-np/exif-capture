"""
updater モジュールの単体テスト
新しいバージョンの確認（リリースの選択と取得済み一覧の保持）、設定に応じた通知の出し分け、リリースページのURLを検証する
"""

from unittest.mock import MagicMock

import pytest

import lib.updater as updater


def _make_release(tag_name, prerelease=False, draft=False):
    """
    GitHub API のレスポンスを模したリリース情報を生成する

    Args:
        tag_name (str): タグ名
        prerelease (bool, optional): Pre-releaseかどうか
        draft (bool, optional): 下書きかどうか

    Returns:
        dict: テスト用のリリース情報
    """
    return {"tag_name": tag_name, "prerelease": prerelease, "draft": draft}


@pytest.fixture
def mock_fetch_releases(monkeypatch):
    """
    現在のバージョンを v1.1.3 に固定し、取得済みのリリース一覧を空に戻したうえで、リリース一覧の取得をモック化する fixture

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

    Returns:
        MagicMock: _fetch_releases のモック（return_value / side_effect でレスポンスを指定する）
    """
    monkeypatch.setattr(updater.version, "APP_VERSION", "v1.1.3")
    monkeypatch.setattr(updater, "_cached_releases", None)
    fetch_releases_mock = MagicMock(
        return_value=[
            _make_release("v1.2.0-beta.1", prerelease=True),
            _make_release("v1.1.3"),
        ]
    )
    monkeypatch.setattr(updater, "_fetch_releases", fetch_releases_mock)
    return fetch_releases_mock


class TestGetLatestRelease:
    """
    公開中の最新リリースと、新しいバージョンかの確認（get_latest_release）に関するテストクラス
    """

    def test_returns_newer_prerelease_only_when_included(self, mock_fetch_releases):
        """Pre-releaseを対象に含めた場合は新しいbeta版、含めない場合は実行中と同じ正式版（新しくない）が返ることを検証する"""
        assert updater.get_latest_release(include_prerelease=True) == updater.LatestRelease(tag="v1.2.0-beta.1", is_newer=True)
        assert updater.get_latest_release(include_prerelease=False) == updater.LatestRelease(tag="v1.1.3", is_newer=False)

    def test_selects_by_version_not_by_list_order(self, mock_fetch_releases):
        """一覧の並び順ではなく、バージョン番号を数値として比べて最大のものを返すことを検証する"""
        mock_fetch_releases.return_value = [_make_release("v1.9.0"), _make_release("v1.10.0"), _make_release("v1.2.0")]

        assert updater.get_latest_release(include_prerelease=False).tag == "v1.10.0"

    def test_excludes_draft_and_unparsable_tags(self, mock_fetch_releases):
        """下書きのリリースと、形式を解析できないタグは選択対象外になることを検証する"""
        mock_fetch_releases.return_value = [_make_release("v2.0.0", draft=True), _make_release("release-3"), _make_release("v1.1.3")]

        assert updater.get_latest_release(include_prerelease=True).tag == "v1.1.3"

    def test_returns_none_when_no_release(self, mock_fetch_releases):
        """リリースが1件も無い場合は None を返すことを検証する"""
        mock_fetch_releases.return_value = []

        assert updater.get_latest_release(include_prerelease=True) is None

    def test_reuses_fetched_releases(self, mock_fetch_releases):
        """2回目以降は、確認範囲を変えても取得済みのリリース一覧から選び直し、取得し直さないことを検証する"""
        updater.get_latest_release(include_prerelease=False)
        assert updater.get_latest_release(include_prerelease=True).tag == "v1.2.0-beta.1"

        mock_fetch_releases.assert_called_once()

    def test_refetches_when_requested(self, mock_fetch_releases):
        """refetch=True の場合は、取得済みでもリリース一覧を取得し直すことを検証する"""
        updater.get_latest_release(include_prerelease=False)
        updater.get_latest_release(include_prerelease=False, refetch=True)

        assert mock_fetch_releases.call_count == 2

    def test_raises_without_fetch_when_current_version_unparsable(self, mock_fetch_releases, monkeypatch):
        """現在のバージョンを解析できない場合、リリース一覧を取得せずに ValueError を送出することを検証する"""
        monkeypatch.setattr(updater.version, "APP_VERSION", updater.version.FALLBACK_VERSION)

        with pytest.raises(ValueError):
            updater.get_latest_release(include_prerelease=False)
        mock_fetch_releases.assert_not_called()


class TestNotifyUpdate:
    """
    設定に応じた新しいバージョンの確認と通知（notify_update）に関するテストクラス
    """

    @pytest.fixture(autouse=True)
    def run_immediately(self, monkeypatch):
        """
        結果を同じスレッドで確かめられるよう、バックグラウンドのスレッドと待機をすぐ実行する形に差し替える fixture

        Args:
            monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

        Returns:
            MagicMock: time.sleep のモック（待機秒数の確認用）
        """

        class ImmediateThread:
            """start() で対象の関数をその場で実行するスレッドの代わり"""

            def __init__(self, target, daemon=False):
                self._target = target

            def start(self):
                self._target()

        sleep_mock = MagicMock()
        monkeypatch.setattr(updater.threading, "Thread", ImmediateThread)
        monkeypatch.setattr(updater.time, "sleep", sleep_mock)
        return sleep_mock

    def test_notifies_when_newer_prerelease_exists(self, isolated_settings_manager, mock_fetch_releases, mock_notifier_actions, run_immediately):
        """「ベータ版も確認する」設定で新しいbeta版がある場合、指定秒数待ってから、そのバージョンのリリースページを開くボタン付きで通知されることを検証する"""
        updater.settings.set("update.checkMode", "prerelease")

        updater.notify_update(delay_seconds=15)

        run_immediately.assert_called_once_with(15)
        notify_arguments = mock_notifier_actions["notify"].call_args.kwargs
        assert "v1.2.0-beta.1" in notify_arguments["title"]
        assert notify_arguments["buttons"] == [updater.notifier.NotificationButton.OPEN_RELEASE_PAGE]
        assert notify_arguments["category"] == updater.notifier.NotificationCategory.UPDATE
        assert notify_arguments["release_page_url"] == updater.get_release_page_url("v1.2.0-beta.1")

    def test_does_not_notify_when_up_to_date(self, isolated_settings_manager, mock_fetch_releases, mock_notifier_actions):
        """「正式版のみ確認する」設定で正式版が最新の場合、通知されないことを検証する"""
        updater.settings.set("update.checkMode", "stable")

        updater.notify_update(delay_seconds=0)

        mock_notifier_actions["notify"].assert_not_called()

    def test_skips_fetch_when_disabled(self, isolated_settings_manager, mock_fetch_releases, mock_notifier_actions):
        """「確認しない」設定では、リリース一覧を取得しないことを検証する"""
        updater.settings.set("update.checkMode", "disabled")

        updater.notify_update(delay_seconds=0)

        mock_fetch_releases.assert_not_called()

    def test_fetch_failure_logs_without_notification(self, isolated_settings_manager, mock_fetch_releases, mock_notifier_actions):
        """取得失敗時、オフライン環境で起動のたびに通知が出ないよう、通知せずログ出力のみ行うことを検証する"""
        mock_fetch_releases.side_effect = OSError("network unreachable")

        updater.notify_update(delay_seconds=0)

        mock_notifier_actions["notify"].assert_not_called()
        mock_notifier_actions["error"].assert_not_called()
        assert "失敗" in mock_notifier_actions["log"].call_args.args[0]


class TestGetReleasePageUrl:
    """
    リリースページのURLの組み立て（get_release_page_url）に関するテストクラス
    """

    def test_returns_page_of_specified_tag(self):
        """リリース一覧ではなく、指定したタグのリリースページのURLを返すことを検証する"""
        expected_url = f"https://github.com/{updater.constants.GITHUB_REPOSITORY}/releases/tag/v1.2.0-beta.1"
        assert updater.get_release_page_url("v1.2.0-beta.1") == expected_url
