"""
paths モジュールの単体テスト
パス展開関数（expand_path）、アプリ基準・assets のパス解決、バージョンと実行形態に応じたアイコン選択を検証する
"""

import os

import lib.paths as paths


class TestExpandPath:
    """
    パス展開関数（expand_path）に関するテストクラス
    """

    def test_expand_path_with_empty_string(self):
        """空文字列またはNoneを渡した場合に空文字列が返却されることを検証する"""
        assert paths.expand_path("") == ""
        assert paths.expand_path(None) == ""

    def test_expand_path_with_tilde(self):
        """チルダ記号（~）がユーザーのホームディレクトリに展開されることを検証する"""
        expanded_result = paths.expand_path("~\\Pictures")
        expected_user_home = os.path.expanduser("~")

        assert expanded_result.startswith(expected_user_home)
        assert expanded_result.endswith("Pictures")

    def test_expand_path_with_environment_variables(self, monkeypatch):
        """環境変数（%VAR%形式）が正しく値に展開・正規化されることを検証する"""
        monkeypatch.setenv("TEST_SCREENSHOT_DIR", "C:\\CustomScreenshots")
        expanded_result = paths.expand_path("%TEST_SCREENSHOT_DIR%\\subfolder")

        assert expanded_result == os.path.normpath("C:\\CustomScreenshots\\subfolder")


class TestAppPaths:
    """
    アプリケーション基準パス解決（resolve_app_relative_path, resolve_asset_path）に関するテストクラス
    """

    def test_resolve_app_relative_path_in_development_environment(self):
        """非凍結（通常Python実行）環境において、リポジトリルートが基準パスとして返ることを検証する"""
        app_root_path = paths.resolve_app_relative_path()
        # リポジトリルートに存在するはずの README.md がパス配下に存在するか確認
        readme_path = os.path.join(app_root_path, "README.md")
        assert os.path.exists(readme_path)

        # 相対パス結合の動作確認
        relative_path_result = paths.resolve_app_relative_path("logs")
        assert relative_path_result == os.path.join(app_root_path, "logs")

    def test_resolve_asset_path_in_development_environment(self):
        """非凍結（通常Python実行）環境において、assets フォルダ配下のファイルパスが解決されることを検証する"""
        sound_path = paths.resolve_asset_path("capture_sound.mp3")
        expected_assets_path = os.path.join(paths.resolve_app_relative_path(), "assets", "capture_sound.mp3")

        assert sound_path == expected_assets_path


class TestIconPath:
    """
    バージョンと実行形態に応じたアイコンの選択（get_icon_path）に関するテストクラス
    """

    def test_development_uses_dev_icon(self):
        """開発時は、バージョンに関わらず icon_dev.ico が選ばれることを検証する"""
        assert os.path.basename(paths.get_icon_path("v1.2.0", is_development=True)) == "icon_dev.ico"

    def test_stable_version_uses_default_icon(self):
        """正式版のタグ名で icon.ico が選ばれることを検証する"""
        assert os.path.basename(paths.get_icon_path("v1.2.0", is_development=False)) == "icon.ico"

    def test_beta_version_uses_beta_icon(self):
        """beta版のタグ名で icon_beta.ico が選ばれることを検証する"""
        assert os.path.basename(paths.get_icon_path("v1.2.0-beta.1", is_development=False)) == "icon_beta.ico"

    def test_icon_files_exist_in_assets(self):
        """選ばれうるアイコンファイルが、すべて assets フォルダに存在することを検証する"""
        for icon_path in (
            paths.get_icon_path("v1.2.0", is_development=True),
            paths.get_icon_path("v1.2.0", is_development=False),
            paths.get_icon_path("v1.2.0-beta.1", is_development=False),
        ):
            assert os.path.exists(icon_path), icon_path
