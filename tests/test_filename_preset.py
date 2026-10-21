"""
filename_preset モジュールの単体テスト
ファイル名用の日時フォーマット、{dup} の書式、保存先パスの組み立てと既存ファイルと被らない連番の探索を検証する
"""

import datetime
import os
import pytest

import lib.filename_preset as filename_preset

# テストで使う撮影日時
_CAPTURED_AT = datetime.datetime(2026, 10, 19, 12, 34, 56)


class TestFormattableTimestamp:
    """
    ファイル名プレースホルダ用の日時拡張クラス（FormattableTimestamp）に関するテストクラス
    """

    def test_default_format_without_specifier(self):
        """書式指定子を渡さない場合にデフォルト書式（%Y%m%d_%H%M%S）で出力されることを検証する"""
        target_datetime = filename_preset.FormattableTimestamp(2026, 9, 28, 15, 30, 45)
        formatted_string = f"{target_datetime}"
        assert formatted_string == "20260928_153045"

    def test_custom_format_with_specifier(self):
        """任意のカスタム書式指定（例: %Y-%m-%d）が正しく適用されることを検証する"""
        target_datetime = filename_preset.FormattableTimestamp(2026, 9, 28, 15, 30, 45)
        formatted_string = f"{target_datetime:%Y-%m-%d}"
        assert formatted_string == "2026-09-28"

        formatted_time_only = f"{target_datetime:%H%M%S}"
        assert formatted_time_only == "153045"


class TestFormatOutputPath:
    """
    プレースホルダを埋めた保存先フルパスの組み立て（format_output_path）に関するテストクラス
    """

    def test_format_output_path_expands_directory_and_formats_preset(self, monkeypatch):
        """フォルダの環境変数が展開され、プリセットの {title} が置換されたフルパスが返ることを検証する"""
        monkeypatch.setenv("TEST_SCREENSHOT_DIR", "C:\\CustomScreenshots")
        output_path = filename_preset.format_output_path("%TEST_SCREENSHOT_DIR%", "{title}.png", "AppTitle")

        assert output_path == "C:\\CustomScreenshots\\AppTitle.png"

    def test_format_output_path_formats_index(self):
        """{index} に連番が入り、{index:03} でゼロ埋めされることを検証する"""
        assert filename_preset.format_output_path("C:\\Shots", "shot_{index}.png", "", sequence_number=2) == "C:\\Shots\\shot_2.png"
        assert filename_preset.format_output_path("C:\\Shots", "shot_{index:03}.png", "", sequence_number=2) == "C:\\Shots\\shot_002.png"


class TestDuplicateSuffix:
    """
    ファイル名プレースホルダ {dup} 用のクラス（DuplicateSuffix）に関するテストクラス
    """

    def test_first_file_has_no_suffix(self):
        """1件目は書式指定に関わらず空文字になることを検証する"""
        assert f"{filename_preset.DuplicateSuffix(1)}" == ""
        assert f"{filename_preset.DuplicateSuffix(1):_%d:1}" == ""

    def test_default_format_without_specifier(self):
        """書式指定が無い場合は「 (2)」形式になることを検証する"""
        assert f"{filename_preset.DuplicateSuffix(2)}" == " (2)"
        assert f"{filename_preset.DuplicateSuffix(3)}" == " (3)"

    def test_custom_template_and_zero_padding(self):
        """テンプレートで区切り文字やゼロ埋めを指定できることを検証する"""
        assert f"{filename_preset.DuplicateSuffix(2):_%d}" == "_2"
        assert f"{filename_preset.DuplicateSuffix(2):_%02d}" == "_02"

    def test_custom_start_number(self):
        """「:」区切りで2件目の番号を指定できることを検証する"""
        assert f"{filename_preset.DuplicateSuffix(2):_%d:1}" == "_1"
        assert f"{filename_preset.DuplicateSuffix(3):_%d:1}" == "_2"

    def test_invalid_format_raises_value_error(self):
        """変換指定の無いテンプレートや整数でない開始番号は ValueError になることを検証する"""
        with pytest.raises(ValueError):
            f"{filename_preset.DuplicateSuffix(2):_copy}"
        with pytest.raises(ValueError):
            f"{filename_preset.DuplicateSuffix(2):_%d:one}"


class TestBuildOutputPath:
    """
    既存ファイルと被らない撮影時の保存先フルパスの確定（build_output_path）に関するテストクラス
    """

    def test_returns_first_path_when_not_exists(self, tmp_path):
        """同名ファイルが無い場合は連番なし（1件目）のパスが返ることを検証する"""
        output_path = filename_preset.build_output_path(str(tmp_path), "{title}{dup}.png", "AppTitle", _CAPTURED_AT)
        assert output_path == os.path.join(str(tmp_path), "AppTitle.png")

    def test_uses_captured_at_for_timestamp(self, tmp_path):
        """{timestamp} に、引数で渡した撮影日時がデフォルト書式で埋め込まれることを検証する"""
        output_path = filename_preset.build_output_path(str(tmp_path), "{timestamp}.png", "", _CAPTURED_AT)
        assert output_path == os.path.join(str(tmp_path), "20261019_123456.png")

    def test_skips_existing_files(self, tmp_path):
        """同名ファイルがある場合は空いている連番のパスが返ることを検証する"""
        (tmp_path / "AppTitle.png").touch()
        (tmp_path / "AppTitle (2).png").touch()

        output_path = filename_preset.build_output_path(str(tmp_path), "{title}{dup}.png", "AppTitle", _CAPTURED_AT)
        assert output_path == os.path.join(str(tmp_path), "AppTitle (3).png")

    def test_skips_existing_files_with_index(self, tmp_path):
        """{index} の場合も既存ファイルと被らない番号が返ることを検証する"""
        (tmp_path / "shot_001.png").touch()

        output_path = filename_preset.build_output_path(str(tmp_path), "shot_{index:03}.png", "", _CAPTURED_AT)
        assert output_path == os.path.join(str(tmp_path), "shot_002.png")

    def test_returns_existing_path_without_sequence_placeholder(self, tmp_path):
        """{index} / {dup} が無いプリセットでは、同名ファイルがあってもそのパス（上書き）が返ることを検証する"""
        (tmp_path / "AppTitle.png").touch()

        output_path = filename_preset.build_output_path(str(tmp_path), "{title}.png", "AppTitle", _CAPTURED_AT)
        assert output_path == os.path.join(str(tmp_path), "AppTitle.png")
