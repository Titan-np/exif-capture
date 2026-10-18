"""
updater モジュールの単体テスト
タグ名の解析・比較、リリースの選択、設定に応じたアップデート確認と通知の出し分けを検証する
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


class TestParseVersion:
    """
    タグ名の解析（parse_version）と、解析結果による大小比較に関するテストクラス
    """

    def test_parse_stable_version(self):
        """正式版のタグ名が、正式版フラグ付きのタプルに変換されることを検証する"""
        assert updater.parse_version("v1.2.3") == (1, 2, 3, 1, 0)

    def test_parse_beta_version(self):
        """beta版のタグ名が、beta番号付きのタプルに変換されることを検証する"""
        assert updater.parse_version("v1.2.0-beta.4") == (1, 2, 0, 0, 4)

    @pytest.mark.parametrize("invalid_tag", ["1.2.0", "v1.2", "v1.2.0-rc.1", "バージョン番号取得失敗", ""])
    def test_parse_invalid_version_returns_none(self, invalid_tag):
        """想定外の形式のタグ名では None が返ることを検証する"""
        assert updater.parse_version(invalid_tag) is None

    @pytest.mark.parametrize(
        "older_tag, newer_tag",
        [
            ("v1.2.0-beta.2", "v1.2.0"),
            ("v1.2.0-beta.1", "v1.2.0-beta.2"),
            ("v1.1.3", "v1.2.0-beta.1"),
            ("v1.9.0", "v1.10.0"),
        ],
    )
    def test_version_ordering(self, older_tag, newer_tag):
        """beta版は同番号の正式版より古く、番号は数値として比較されることを検証する"""
        assert updater.parse_version(older_tag) < updater.parse_version(newer_tag)


class TestFindLatestRelease:
    """
    リリース一覧からの最新リリース選択（find_latest_release）に関するテストクラス
    """

    def test_excludes_prerelease_when_not_included(self):
        """Pre-releaseを含めない場合、正式版の中で最大のものが選ばれることを検証する"""
        releases = [
            _make_release("v1.2.0-beta.1", prerelease=True),
            _make_release("v1.1.3"),
            _make_release("v1.1.2"),
        ]
        assert updater.find_latest_release(releases, include_prerelease=False)["tag_name"] == "v1.1.3"

    def test_includes_prerelease_when_included(self):
        """Pre-releaseを含める場合、beta版も選択対象になることを検証する"""
        releases = [
            _make_release("v1.1.3"),
            _make_release("v1.2.0-beta.1", prerelease=True),
        ]
        assert updater.find_latest_release(releases, include_prerelease=True)["tag_name"] == "v1.2.0-beta.1"

    def test_excludes_draft(self):
        """下書きのリリースは選択対象外になることを検証する"""
        releases = [
            _make_release("v2.0.0", draft=True),
            _make_release("v1.1.3"),
        ]
        assert updater.find_latest_release(releases, include_prerelease=True)["tag_name"] == "v1.1.3"

    def test_returns_none_when_no_candidate(self):
        """対象となるリリースが無い場合は None が返ることを検証する"""
        assert updater.find_latest_release([], include_prerelease=True) is None
        assert updater.find_latest_release([_make_release("v1.2.0-beta.1", prerelease=True)], include_prerelease=False) is None


@pytest.fixture
def update_environment(monkeypatch, isolated_settings_manager):
    """
    現在のバージョンを v1.1.3 に固定し、リリース一覧の取得をモック化する fixture

    Returns:
        MagicMock: _fetch_releases のモック（return_value / side_effect でレスポンスを指定する）
    """
    monkeypatch.setattr(updater.version, "APP_VERSION", "v1.1.3")
    fetch_releases_mock = MagicMock(
        return_value=[
            _make_release("v1.2.0-beta.1", prerelease=True),
            _make_release("v1.1.3"),
        ]
    )
    monkeypatch.setattr(updater, "_fetch_releases", fetch_releases_mock)
    return fetch_releases_mock


class TestGetNewerReleaseTag:
    """
    新しいバージョンの有無の確認（get_newer_release_tag）に関するテストクラス
    """

    def test_returns_newer_prerelease_only_when_included(self, update_environment):
        """新しいbeta版は、Pre-releaseを対象に含めた場合のみ返ることを検証する"""
        assert updater.get_newer_release_tag(include_prerelease=True) == "v1.2.0-beta.1"
        assert updater.get_newer_release_tag(include_prerelease=False) is None

    def test_raises_on_fetch_failure(self, update_environment):
        """リリース一覧の取得に失敗した場合、例外がそのまま送出されることを検証する"""
        update_environment.side_effect = OSError("network unreachable")

        with pytest.raises(OSError):
            updater.get_newer_release_tag(include_prerelease=False)

    def test_raises_without_fetch_when_current_version_unparsable(self, update_environment, monkeypatch):
        """現在のバージョンを解析できない場合、リリース一覧を取得せずに ValueError を送出することを検証する"""
        monkeypatch.setattr(updater.version, "APP_VERSION", updater.version.FALLBACK_VERSION)

        with pytest.raises(ValueError):
            updater.get_newer_release_tag(include_prerelease=False)
        update_environment.assert_not_called()


class TestCheckForUpdate:
    """
    起動時の自動確認として、設定に応じたアップデート確認と通知（check_for_update）に関するテストクラス
    """

    def test_notifies_when_newer_prerelease_exists(self, update_environment, mock_notifier_actions):
        """「ベータ版も確認する」設定で新しいbeta版がある場合、リリースページボタン付きで通知されることを検証する"""
        updater.settings.set("update.checkMode", "prerelease")

        assert updater.check_for_update() == "v1.2.0-beta.1"
        notify_arguments = mock_notifier_actions["notify"].call_args.kwargs
        assert "v1.2.0-beta.1" in notify_arguments["title"]
        assert notify_arguments["buttons"] == [updater.notifier.NotificationButton.OPEN_RELEASE_PAGE]
        assert notify_arguments["category"] == updater.notifier.NotificationCategory.UPDATE

    def test_does_not_notify_when_up_to_date(self, update_environment, mock_notifier_actions):
        """「正式版のみ確認する」設定で正式版が最新の場合、自動確認では通知されないことを検証する"""
        updater.settings.set("update.checkMode", "stable")

        assert updater.check_for_update() is None
        mock_notifier_actions["notify"].assert_not_called()

    def test_skips_fetch_when_disabled(self, update_environment, mock_notifier_actions):
        """「確認しない」設定の自動確認では、リリース一覧を取得しないことを検証する"""
        updater.settings.set("update.checkMode", "disabled")

        assert updater.check_for_update() is None
        update_environment.assert_not_called()

    def test_fetch_failure_logs_without_notification(self, update_environment, mock_notifier_actions):
        """取得失敗時、オフライン環境で起動のたびに通知が出ないよう、通知せずログ出力のみ行うことを検証する"""
        update_environment.side_effect = OSError("network unreachable")

        assert updater.check_for_update() is None
        mock_notifier_actions["notify"].assert_not_called()
        mock_notifier_actions["error"].assert_not_called()
        assert "失敗" in mock_notifier_actions["log"].call_args.args[0]
