"""
version モジュールの単体テスト
環境変数、Gitコマンド、およびフォールバックによるバージョン番号解決ロジックを検証する
"""

import subprocess
from unittest.mock import MagicMock, patch
import pytest

import lib.version as version


class TestVersionResolution:
    """
    アプリケーションバージョン解決（get_app_version）に関するテストクラス
    """

    def test_get_app_version_from_custom_environment_variable(self, monkeypatch):
        """環境変数 EXIF_CAPTURE_VERSION が設定されている場合、その値が優先されることを検証する"""
        monkeypatch.setenv("EXIF_CAPTURE_VERSION", "v1.2.3-test")
        # GITHUB_REF_NAME は空にしておく
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

        resolved_version = version.get_app_version()
        assert resolved_version == "v1.2.3-test"

    def test_get_app_version_from_github_ref_name(self, monkeypatch):
        """CI環境等で環境変数 GITHUB_REF_NAME が設定されている場合、その値が取得されることを検証する"""
        monkeypatch.delenv("EXIF_CAPTURE_VERSION", raising=False)
        monkeypatch.setenv("GITHUB_REF_NAME", "v2.0.0")

        resolved_version = version.get_app_version()
        assert resolved_version == "v2.0.0"

    def test_get_app_version_from_git_describe(self, monkeypatch):
        """環境変数が存在せずGitコマンドが成功する場合、Gitタグ名が取得されることを検証する"""
        monkeypatch.delenv("EXIF_CAPTURE_VERSION", raising=False)
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

        # subprocess.run の実行結果をモック化
        mock_result = MagicMock()
        mock_result.stdout = "v1.1.2\n"

        with patch("subprocess.run", return_value=mock_result):
            resolved_version = version.get_app_version()
            assert resolved_version == "v1.1.2"

    def test_get_app_version_fallback(self, monkeypatch):
        """環境変数もGitタグも存在せず全取得手段が失敗した場合、フォールバック文字列を返すことを検証する"""
        monkeypatch.delenv("EXIF_CAPTURE_VERSION", raising=False)
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

        # subprocess.run がエラー（Gitコマンド失敗）となるようモック化
        with patch("subprocess.run", side_effect=Exception("Git command failed")):
            resolved_version = version.get_app_version()
            assert resolved_version == version.FALLBACK_VERSION
