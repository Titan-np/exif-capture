"""
windows_shell モジュールの単体テスト
ファイル・フォルダを開く処理の失敗時の扱いと、保存先フォルダの準備を検証する
"""

import os

import lib.windows_shell as windows_shell


class TestSafeOpenPath:
    """
    既定アプリでファイル・フォルダを開く処理（safe_open_path）に関するテストクラス
    """

    def test_opens_existing_path(self, monkeypatch, tmp_path):
        """存在するパスは既定アプリで開き、True を返すことを検証する"""
        opened_paths = []
        monkeypatch.setattr(os, "startfile", opened_paths.append, raising=False)

        assert windows_shell.safe_open_path(str(tmp_path)) is True
        assert opened_paths == [str(tmp_path)]

    def test_notifies_error_for_missing_path(self, mock_notifier_actions, tmp_path):
        """存在しないパスは開かずに False を返し、エラー通知することを検証する"""
        missing_path = str(tmp_path / "missing.png")

        assert windows_shell.safe_open_path(missing_path, resource_name="キャプチャした画像") is False
        assert mock_notifier_actions["error"].call_args.args[0] == "キャプチャした画像を開けませんでした。"

    def test_notifies_missing_association(self, monkeypatch, mock_notifier_actions, tmp_path):
        """関連付けアプリが無い（エラーコード 1155）場合、その旨を通知して False を返すことを検証する"""

        def raise_no_association(target_path):
            error = OSError("no association")
            error.winerror = 1155
            raise error

        monkeypatch.setattr(os, "startfile", raise_no_association, raising=False)

        assert windows_shell.safe_open_path(str(tmp_path)) is False
        assert "既定のアプリケーションが設定されていません" in mock_notifier_actions["error"].call_args.args[1]


class TestEnsureSaveDirectory:
    """
    保存先フォルダの取得・作成（ensure_save_directory）に関するテストクラス
    """

    def test_creates_missing_directory(self, monkeypatch, tmp_path):
        """設定された保存先フォルダが存在しない場合は作成し、そのパスを返すことを検証する"""
        target_directory = tmp_path / "Screenshots"
        monkeypatch.setattr("lib.settings.get", lambda key: str(target_directory))

        assert windows_shell.ensure_save_directory() == str(target_directory)
        assert target_directory.is_dir()

    def test_returns_none_when_directory_not_configured(self, monkeypatch):
        """保存先フォルダが未設定の場合は None を返すことを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: "")

        assert windows_shell.ensure_save_directory() is None

    def test_returns_none_when_directory_cannot_be_created(self, monkeypatch, tmp_path):
        """保存先フォルダを作成できない場合は None を返すことを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: str(tmp_path / "Screenshots"))

        def raise_permission_error(path, exist_ok=False):
            raise PermissionError("denied")

        monkeypatch.setattr(os, "makedirs", raise_permission_error)

        assert windows_shell.ensure_save_directory() is None
