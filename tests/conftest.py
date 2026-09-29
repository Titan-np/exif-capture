"""
pytest の共通設定およびテスト用 fixture 定義
テスト実行時の外部副作用（通知表示・ショートカット更新など）を安全にモック化する
"""

import os
import sys
from unittest.mock import MagicMock, patch
import pytest

# src ディレクトリへのパスを解決し、インポート可能にする
SOURCE_DIRECTORY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SOURCE_DIRECTORY_PATH not in sys.path:
    # 最優先で検索されるよう先頭に追加
    sys.path.insert(0, SOURCE_DIRECTORY_PATH)

# notifier モジュール読み込み時の副作用（スタートメニューショートカットの作成・更新）を防止するため、
# モジュール読み込み前に該当メソッドを空実装に差し替える
with patch("notifier.Notifier._ensure_start_menu_shortcut", return_value=None):
    import notifier


@pytest.fixture(autouse=True)
def mock_notifier_actions(monkeypatch):
    """
    全テストで自動的にトースト通知の送信やエラー通知をモック化し、実環境への通知発火を防ぐ fixture

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト
    """
    # 実際の通知送信・ログ出力を抑制するためのモック関数
    dummy_notify = MagicMock()
    dummy_log = MagicMock()
    dummy_error = MagicMock()

    # シングルトンインスタンスのメソッドをモックに差し替え
    monkeypatch.setattr(notifier.notifier, "notify", dummy_notify)
    monkeypatch.setattr(notifier.notifier, "log", dummy_log)
    monkeypatch.setattr(notifier.notifier, "error", dummy_error)
    monkeypatch.setattr(notifier.notifier, "_send", MagicMock())

    return {
        "notify": dummy_notify,
        "log": dummy_log,
        "error": dummy_error,
    }


@pytest.fixture
def isolated_settings_manager(tmp_path, monkeypatch):
    """
    実環境の settings.json に影響を与えないよう、一時ディレクトリ内で動作する SettingsManager を生成する fixture

    Args:
        tmp_path (pathlib.Path): pytest が提供する一時ディレクトリのパス
        monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

    Returns:
        SettingsManager: テスト用の独立した設定マネージャーインスタンス
    """

    # utils.get_app_path の戻り先を一時ディレクトリ配下に変更
    def mock_get_app_path(relative_path: str = ""):
        if relative_path:
            return str(tmp_path / relative_path)
        return str(tmp_path)

    monkeypatch.setattr("utils.get_app_path", mock_get_app_path)
    monkeypatch.setattr("settings_manager.get_app_path", mock_get_app_path)

    from settings_manager import SettingsManager

    # テスト専用の新しいインスタンスを生成
    settings_instance = SettingsManager()
    return settings_instance
