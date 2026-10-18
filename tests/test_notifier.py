"""
notifier モジュールの単体テスト
通知の種別ごとの設定に応じたトースト通知の表示有無と、ログファイルの世代切り替えを検証する
"""

import os

import pytest

import lib.notifier as notifier
import lib.paths as paths

# conftest の autouse fixture で notify がモック化される前に、テスト対象の元の関数を退避しておく
_original_notify = notifier.notify

# 通知の種別ごとの、表示する設定値と表示しない設定値の組
_CATEGORY_SETTING_CASES = [
    (notifier.NotificationCategory.CAPTURE, True, False),
    (notifier.NotificationCategory.APP_EVENT, True, False),
    (notifier.NotificationCategory.ERROR, True, False),
    (notifier.NotificationCategory.UPDATE, "stable", "disabled"),
]


class TestNotifyCategory:
    """
    通知の種別（category）による表示有無の切り替えに関するテストクラス
    """

    @pytest.mark.parametrize("category, enabled_value, disabled_value", _CATEGORY_SETTING_CASES)
    def test_sends_toast_when_category_enabled(self, isolated_settings_manager, category, enabled_value, disabled_value):
        """種別に対応する設定がオンの場合、トースト通知が送信されることを検証する"""
        isolated_settings_manager.set(category, enabled_value)

        _original_notify("テスト通知", category=category)

        notifier._send.assert_called_once()

    @pytest.mark.parametrize("category, enabled_value, disabled_value", _CATEGORY_SETTING_CASES)
    def test_skips_toast_when_category_disabled(self, isolated_settings_manager, mock_notifier_actions, category, enabled_value, disabled_value):
        """種別に対応する設定がオフの場合、トースト通知は送信されずログのみ出力されることを検証する"""
        isolated_settings_manager.set(category, disabled_value)

        _original_notify("テスト通知", category=category)

        notifier._send.assert_not_called()
        # fixture の設定ファイル作成時のログも同じモックに記録されるため、回数ではなく最後の呼び出し内容で確認する
        mock_notifier_actions["log"].assert_called_with("テスト通知")

    def test_other_category_setting_does_not_affect(self, isolated_settings_manager):
        """他の種別の設定がオフでも、対象の種別の設定がオンなら送信されることを検証する"""
        isolated_settings_manager.set(notifier.NotificationCategory.CAPTURE, False)
        isolated_settings_manager.set(notifier.NotificationCategory.ERROR, True)

        _original_notify("テスト通知", category=notifier.NotificationCategory.ERROR)

        notifier._send.assert_called_once()

    def test_category_is_required(self):
        """種別を指定せずに呼び出すと TypeError になり、設定で制御できない通知を作れないことを検証する"""
        with pytest.raises(TypeError):
            _original_notify("テスト通知")


class TestRotateLogFile:
    """
    ログファイルの世代切り替え（rotate_log_file）に関するテストクラス
    """

    @pytest.fixture
    def log_directory(self, tmp_path, monkeypatch):
        """
        ログの保存先を一時ディレクトリに差し替え、判定を容易にするため基準サイズを小さくする fixture

        Args:
            tmp_path (pathlib.Path): pytest が提供する一時ディレクトリのパス
            monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

        Returns:
            pathlib.Path: ログファイルを置くディレクトリ
        """
        monkeypatch.setattr(paths, "get_app_path", lambda relative_path="": str(tmp_path / relative_path))
        monkeypatch.setattr(notifier, "LOG_FILE_MAX_BYTES", 10)

        directory = tmp_path / notifier.LOG_DIRECTORY_NAME
        directory.mkdir()
        return directory

    def test_keeps_file_within_limit(self, log_directory):
        """基準サイズ以下のログファイルは切り替えられないことを検証する"""
        log_file = log_directory / notifier.LOG_FILE_NAME
        log_file.write_text("1234567890", encoding="utf-8")

        notifier.rotate_log_file()

        assert log_file.read_text(encoding="utf-8") == "1234567890"
        assert not (log_directory / (notifier.LOG_FILE_NAME + ".old")).exists()

    def test_does_nothing_without_log_file(self, log_directory):
        """ログファイルが存在しない場合に例外を出さず何もしないことを検証する"""
        notifier.rotate_log_file()

        assert os.listdir(log_directory) == []

    def test_moves_oversized_file_and_overwrites_old(self, log_directory, mock_notifier_actions):
        """基準サイズを超えたログファイルが旧世代へ移り、既存の旧世代は上書きされることを検証する"""
        log_file = log_directory / notifier.LOG_FILE_NAME
        old_log_file = log_directory / (notifier.LOG_FILE_NAME + ".old")
        log_file.write_text("new-oversized-log", encoding="utf-8")
        old_log_file.write_text("previous-generation", encoding="utf-8")

        notifier.rotate_log_file()

        assert not log_file.exists()
        assert old_log_file.read_text(encoding="utf-8") == "new-oversized-log"
        mock_notifier_actions["log"].assert_called_once()

    def test_continues_when_replace_fails(self, log_directory, monkeypatch, mock_notifier_actions):
        """他プロセスがファイルを開いていて置換に失敗しても、例外を外に出さず失敗を記録することを検証する"""
        log_file = log_directory / notifier.LOG_FILE_NAME
        log_file.write_text("new-oversized-log", encoding="utf-8")

        def raise_permission_error(source, destination):
            raise PermissionError("locked")

        monkeypatch.setattr(os, "replace", raise_permission_error)

        notifier.rotate_log_file()

        assert log_file.exists()
        logged_message = mock_notifier_actions["log"].call_args.args[0]
        assert "失敗" in logged_message
