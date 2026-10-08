"""
pytest の共通設定およびテスト用 fixture 定義
テスト実行時の外部副作用（通知表示・ショートカット更新など）を安全にモック化する
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# src ディレクトリへのパスを解決し、インポート可能にする
SOURCE_DIRECTORY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SOURCE_DIRECTORY_PATH not in sys.path:
    # 最優先で検索されるよう先頭に追加
    sys.path.insert(0, SOURCE_DIRECTORY_PATH)

# テスト実行時の副作用（スタートメニューショートカット更新など）を防止するフラグを設定
os.environ["EXIF_CAPTURE_TESTING"] = "1"

import lib.notifier as notifier
import lib.settings as settings
import lib.utils as utils


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

    # モジュールの関数をモックに差し替え
    monkeypatch.setattr(notifier, "notify", dummy_notify)
    monkeypatch.setattr(notifier, "log", dummy_log)
    monkeypatch.setattr(notifier, "error", dummy_error)
    monkeypatch.setattr(notifier, "_send", MagicMock())

    return {
        "notify": dummy_notify,
        "log": dummy_log,
        "error": dummy_error,
    }


@pytest.fixture
def isolated_settings_manager(tmp_path, monkeypatch):
    """
    実環境の settings.json に影響を与えないよう、一時ディレクトリ内で動作する lib.settings を初期化する fixture

    Args:
        tmp_path (pathlib.Path): pytest が提供する一時ディレクトリのパス
        monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

    Returns:
        module: テスト用の独立した設定モジュール (lib.settings)
    """

    # lib.utils.get_app_path の戻り先を一時ディレクトリ配下に変更
    def mock_get_app_path(relative_path: str = ""):
        if relative_path:
            return str(tmp_path / relative_path)
        return str(tmp_path)

    monkeypatch.setattr(utils, "get_app_path", mock_get_app_path)
    monkeypatch.setattr(settings.utils, "get_app_path", mock_get_app_path)

    # テスト開始前にメモリ上の設定データをクリアし、一時ディレクトリ上で初期ロードを行う
    settings._data.clear()
    settings.load()
    return settings
