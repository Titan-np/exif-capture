"""
notifier モジュールの単体テスト
通知の種別ごとの設定に応じて、トースト通知の表示有無が切り替わることを検証する
"""

import pytest

import lib.notifier as notifier

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
        mock_notifier_actions["log"].assert_called_once()

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
