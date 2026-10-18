"""
utils モジュールの単体テスト
パス展開関数（expand_path）およびアプリケーションパス解決処理を検証する
"""

import os
import pytest

import lib.utils as utils


class TestExpandPath:
    """
    パス展開関数（expand_path）に関するテストクラス
    """

    def test_expand_path_with_empty_string(self):
        """空文字列またはNoneを渡した場合に空文字列が返却されることを検証する"""
        assert utils.expand_path("") == ""
        assert utils.expand_path(None) == ""

    def test_expand_path_with_tilde(self):
        """チルダ記号（~）がユーザーのホームディレクトリに展開されることを検証する"""
        expanded_result = utils.expand_path("~\\Pictures")
        expected_user_home = os.path.expanduser("~")

        assert expanded_result.startswith(expected_user_home)
        assert expanded_result.endswith("Pictures")

    def test_expand_path_with_environment_variables(self, monkeypatch):
        """環境変数（%VAR%形式）が正しく値に展開・正規化されることを検証する"""
        monkeypatch.setenv("TEST_SCREENSHOT_DIR", "C:\\CustomScreenshots")
        expanded_result = utils.expand_path("%TEST_SCREENSHOT_DIR%\\subfolder")

        assert expanded_result == os.path.normpath("C:\\CustomScreenshots\\subfolder")


class TestAppPaths:
    """
    アプリケーション基準パス解決（get_app_path, get_asset_path）に関するテストクラス
    """

    def test_get_app_path_in_development_environment(self):
        """非凍結（通常Python実行）環境において、リポジトリルートが基準パスとして返ることを検証する"""
        app_root_path = utils.get_app_path()
        # リポジトリルートに存在するはずの README.md がパス配下に存在するか確認
        readme_path = os.path.join(app_root_path, "README.md")
        assert os.path.exists(readme_path)

        # 相対パス結合の動作確認
        relative_path_result = utils.get_app_path("logs")
        assert relative_path_result == os.path.join(app_root_path, "logs")

    def test_get_asset_path_in_development_environment(self):
        """非凍結（通常Python実行）環境において、assets フォルダ配下のファイルパスが解決されることを検証する"""
        icon_path = utils.get_asset_path("icon.ico")
        expected_assets_directory = os.path.join(utils.get_app_path(), "assets", "icon.ico")

        assert icon_path == expected_assets_directory

    def test_get_app_icon_path_in_development_environment(self):
        """非凍結（通常Python実行）環境において、開発用アイコン（icon_dev.ico）のパスが返ることを検証する"""
        app_icon_path = utils.get_app_icon_path()
        assert app_icon_path == os.path.join(utils.get_app_path(), "assets", "icon_dev.ico")


class TestIconFilename:
    """
    バージョンに応じたアイコンファイル名の選択（get_icon_filename）に関するテストクラス
    """

    def test_stable_version_uses_default_icon(self):
        """正式版のタグ名で icon.ico が選ばれることを検証する"""
        assert utils.get_icon_filename("v1.2.0") == "icon.ico"

    def test_beta_version_uses_beta_icon(self):
        """beta版のタグ名で icon_beta.ico が選ばれることを検証する"""
        assert utils.get_icon_filename("v1.2.0-beta.1") == "icon_beta.ico"
