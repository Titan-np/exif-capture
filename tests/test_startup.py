"""
startup モジュールの単体テスト
スタートアップへの登録状態の判定、登録・解除、起動時のショートカット更新を検証する
"""

from unittest.mock import MagicMock

import pytest

import lib.startup as startup


@pytest.fixture
def shortcut_path(tmp_path, monkeypatch):
    """
    実環境のスタートアップフォルダに影響を与えないよう、ショートカットの保存先を一時ディレクトリに差し替える fixture

    Args:
        tmp_path (pathlib.Path): pytest が提供する一時ディレクトリのパス
        monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

    Returns:
        pathlib.Path: テスト用のショートカットのパス（作成はしない）
    """
    path = tmp_path / "EXIF Capture.lnk"
    monkeypatch.setattr(startup, "_get_shortcut_path", lambda: str(path))
    return path


@pytest.fixture
def mock_create_shortcut(monkeypatch):
    """
    ショートカット作成（COM呼び出し）をモックに差し替え、exe実行時として扱う fixture

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

    Returns:
        MagicMock: windows_shell.create_app_shortcut の代わりのモック
    """
    create_shortcut = MagicMock()
    monkeypatch.setattr(startup.windows_shell, "create_app_shortcut", create_shortcut)
    monkeypatch.setattr(startup.paths, "is_executable", lambda: True)
    return create_shortcut


def _mock_startup_approved_value(monkeypatch, approved_value):
    """
    StartupApproved レジストリの読み取り結果を差し替える

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト
        approved_value (bytes | None): 読み取れる値（None の場合は記録が無い状態）
    """
    monkeypatch.setattr(startup.winreg, "OpenKey", MagicMock())
    if approved_value is None:
        monkeypatch.setattr(startup.winreg, "QueryValueEx", MagicMock(side_effect=FileNotFoundError))
    else:
        monkeypatch.setattr(startup.winreg, "QueryValueEx", MagicMock(return_value=(approved_value, 3)))


class TestGetStatus:
    """
    登録状態の判定（get_status）に関するテストクラス
    """

    def test_returns_unregistered_when_shortcut_missing(self, shortcut_path):
        """ショートカットが無い場合に未登録と判定されることを検証する"""
        assert startup.get_status() == startup.StartupStatus.UNREGISTERED

    @pytest.mark.parametrize(
        "approved_value",
        [None, b"\x02" + b"\x00" * 11, b"\x06" + b"\x00" * 11],
    )
    def test_returns_enabled_when_not_disabled_by_windows(self, shortcut_path, monkeypatch, approved_value):
        """ショートカットがあり、StartupApproved の記録が無いか先頭バイトが偶数の場合に有効と判定されることを検証する"""
        shortcut_path.touch()
        _mock_startup_approved_value(monkeypatch, approved_value)

        assert startup.get_status() == startup.StartupStatus.ENABLED

    def test_returns_disabled_when_disabled_by_windows(self, shortcut_path, monkeypatch):
        """ショートカットがあり、StartupApproved の先頭バイトが奇数の場合にWindows側で無効と判定されることを検証する"""
        shortcut_path.touch()
        _mock_startup_approved_value(monkeypatch, b"\x03" + b"\x00" * 11)

        assert startup.get_status() == startup.StartupStatus.DISABLED_BY_WINDOWS


class TestRegistration:
    """
    登録・解除（register, unregister）に関するテストクラス
    """

    def test_register_creates_shortcut(self, shortcut_path, mock_create_shortcut):
        """登録時にスタートアップフォルダのパスでショートカットが作成されることを検証する"""
        assert startup.register() is True
        mock_create_shortcut.assert_called_once_with(str(shortcut_path))

    def test_register_notifies_error_on_failure(self, shortcut_path, mock_create_shortcut, mock_notifier_actions):
        """ショートカットの作成に失敗した場合に False を返し、エラー通知されることを検証する"""
        mock_create_shortcut.side_effect = OSError("access denied")

        assert startup.register() is False
        mock_notifier_actions["error"].assert_called_once()

    def test_unregister_removes_shortcut(self, shortcut_path, mock_create_shortcut):
        """解除時にショートカットが削除されることを検証する"""
        shortcut_path.touch()

        assert startup.unregister() is True
        assert not shortcut_path.exists()

    def test_unregister_succeeds_when_shortcut_missing(self, shortcut_path, mock_create_shortcut, mock_notifier_actions):
        """ショートカットが既に無い場合も解除成功として扱い、エラー通知しないことを検証する"""
        assert startup.unregister() is True
        mock_notifier_actions["error"].assert_not_called()

    def test_skips_in_development_environment(self, shortcut_path, mock_create_shortcut, monkeypatch):
        """開発時（Python実行）は、登録・解除・更新のいずれもショートカットを操作しないことを検証する"""
        monkeypatch.setattr(startup.paths, "is_executable", lambda: False)
        shortcut_path.touch()

        assert startup.register() is False
        assert startup.unregister() is False
        startup.refresh_shortcut()

        mock_create_shortcut.assert_not_called()
        assert shortcut_path.exists()


class TestRefreshShortcut:
    """
    起動時のショートカット更新（refresh_shortcut）に関するテストクラス
    """

    def test_skips_when_unregistered(self, shortcut_path, mock_create_shortcut):
        """未登録の場合はショートカットを作成しないことを検証する"""
        startup.refresh_shortcut()
        mock_create_shortcut.assert_not_called()

    def test_recreates_when_target_missing(self, shortcut_path, mock_create_shortcut, monkeypatch, tmp_path):
        """登録済みでリンク先が存在しない（exeを移動した）場合はショートカットを作り直すことを検証する"""
        shortcut_path.touch()
        missing_target_path = str(tmp_path / "moved" / "EXIF Capture.exe")
        monkeypatch.setattr(startup.windows_shell, "get_shortcut_target_path", lambda path: missing_target_path)

        startup.refresh_shortcut()
        mock_create_shortcut.assert_called_once_with(str(shortcut_path))

    def test_keeps_when_target_exists(self, shortcut_path, mock_create_shortcut, monkeypatch, tmp_path):
        """登録済みでリンク先が存在する（別フォルダのexeを起動した）場合はショートカットを作り直さないことを検証する"""
        shortcut_path.touch()
        existing_target_path = tmp_path / "EXIF Capture.exe"
        existing_target_path.touch()
        monkeypatch.setattr(startup.windows_shell, "get_shortcut_target_path", lambda path: str(existing_target_path))

        startup.refresh_shortcut()
        mock_create_shortcut.assert_not_called()
