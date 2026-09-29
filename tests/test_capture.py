"""
capture モジュールの単体テスト
日時フォーマットクラス、保存先パス生成ロジック、EXIFメタデータ生成ロジックを検証する
"""

import datetime
import os
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from capture import _FormattableTimestamp, _generate_output_path, _generate_exif_metadata


class TestFormattableTimestamp:
    """
    ファイル名プレースホルダ用の日時拡張クラス（_FormattableTimestamp）に関するテストクラス
    """

    def test_default_format_without_specifier(self):
        """書式指定子を渡さない場合にデフォルト書式（%Y%m%d_%H%M%S）で出力されることを検証する"""
        target_datetime = _FormattableTimestamp(2026, 9, 28, 15, 30, 45)
        formatted_string = f"{target_datetime}"
        assert formatted_string == "20260928_153045"

    def test_custom_format_with_specifier(self):
        """任意のカスタム書式指定（例: %Y-%m-%d）が正しく適用されることを検証する"""
        target_datetime = _FormattableTimestamp(2026, 9, 28, 15, 30, 45)
        formatted_string = f"{target_datetime:%Y-%m-%d}"
        assert formatted_string == "2026-09-28"

        formatted_time_only = f"{target_datetime:%H%M%S}"
        assert formatted_time_only == "153045"


class TestGenerateOutputPath:
    """
    スクリーンショット保存先パスの生成ロジック（_generate_output_path）に関するテストクラス
    """

    def test_generate_output_path_replaces_forbidden_characters(self, monkeypatch):
        """ウィンドウタイトルに含まれる禁止文字がアンダースコアへ正しく置換されることを検証する"""
        # 保存先フォルダとプリセット設定をモック化
        monkeypatch.setattr("capture.ensure_save_directory", lambda: "C:\\Screenshots")
        monkeypatch.setattr("settings_manager.settings.get", lambda key: "{title}.png" if key == "save.filenamePreset" else None)

        unsafe_window_title = 'Sample\\/:*?"<>|Window'
        generated_path = _generate_output_path(unsafe_window_title)

        expected_filename = "Sample_________Window.png"
        assert os.path.basename(generated_path) == expected_filename

    def test_generate_output_path_formats_timestamp_and_title(self, monkeypatch):
        """タイムスタンプとウィンドウタイトルを含む標準プリセットで正しくパスが組み立てられることを検証する"""
        monkeypatch.setattr("capture.ensure_save_directory", lambda: "C:\\Screenshots")
        monkeypatch.setattr("settings_manager.settings.get", lambda key: "{timestamp}_{title}.png" if key == "save.filenamePreset" else None)

        generated_path = _generate_output_path("AppTitle")

        assert generated_path is not None
        assert generated_path.startswith("C:\\Screenshots\\")
        assert generated_path.endswith("_AppTitle.png")

    def test_generate_output_path_rejects_path_exceeding_max_length(self, monkeypatch):
        """Windows のパス最大長（259文字）を超過した場合に安全に None を返すことを検証する"""
        # 非常に長いディレクトリパスをモック
        long_directory_path = "C:\\" + "a" * 240
        monkeypatch.setattr("capture.ensure_save_directory", lambda: long_directory_path)
        monkeypatch.setattr("settings_manager.settings.get", lambda key: "{title}.png" if key == "save.filenamePreset" else None)

        long_window_title = "long_title_" * 10
        generated_path = _generate_output_path(long_window_title)

        # パス長が259文字を超えるため None が返ることを確認
        assert generated_path is None

    def test_generate_output_path_handles_format_error(self, monkeypatch):
        """プリセットのフォーマットで例外（KeyErrorなど）が発生した場合に None を返すことを検証する"""
        monkeypatch.setattr("capture.ensure_save_directory", lambda: "C:\\Screenshots")
        # 未定義のプレースホルダを含むプリセット
        monkeypatch.setattr("settings_manager.settings.get", lambda key: "{invalid_key}.png" if key == "save.filenamePreset" else None)

        generated_path = _generate_output_path("TestTitle")
        assert generated_path is None


class TestGenerateExifMetadata:
    """
    EXIFメタデータおよびPNGテキスト情報の生成（_generate_exif_metadata）に関するテストクラス
    """

    def test_generate_exif_metadata_embeds_modification_time_and_png_info(self, monkeypatch):
        """更新日時とPNGテキスト情報が常に画像情報へ付与されることを検証する"""
        # メタデータ埋め込み設定を無効化
        monkeypatch.setattr("settings_manager.settings.get", lambda key: False if key == "save.embedDatetimeMetadata" else None)

        # テスト用の小型ダミー画像を生成
        test_image = Image.new("RGB", (16, 16), color=(255, 255, 255))
        exif_metadata, png_info = _generate_exif_metadata(test_image)

        # EXIF タグ 306（更新日時）が格納されていることを確認
        assert 306 in exif_metadata
        assert isinstance(exif_metadata[306], str)

        # PNG のテキストチャンクに Creation Time が追加されていることを確認
        assert png_info is not None

    def test_generate_exif_metadata_embeds_shooting_time_when_enabled(self, monkeypatch):
        """設定が有効な場合、EXIF撮影日時（36867）およびデジタル化日時（36868）が付与されることを検証する"""
        monkeypatch.setattr("settings_manager.settings.get", lambda key: True if key == "save.embedDatetimeMetadata" else None)

        test_image = Image.new("RGB", (16, 16), color=(0, 0, 0))
        exif_metadata, _ = _generate_exif_metadata(test_image)

        # Exif IFD (34665) から詳細タグを取得
        exif_ifd = exif_metadata.get_ifd(34665)
        assert 36867 in exif_ifd  # 撮影日時
        assert 36868 in exif_ifd  # デジタル化日時

    def test_generate_exif_metadata_skips_shooting_time_when_disabled(self, monkeypatch):
        """設定が無効な場合、EXIF撮影日時（36867）が付与されないことを検証する"""
        monkeypatch.setattr("settings_manager.settings.get", lambda key: False if key == "save.embedDatetimeMetadata" else None)

        test_image = Image.new("RGB", (16, 16), color=(0, 0, 0))
        exif_metadata, _ = _generate_exif_metadata(test_image)

        # Exif IFD (34665) 内にタグが存在しないことを確認
        exif_ifd = exif_metadata.get_ifd(34665)
        assert 36867 not in exif_ifd
        assert 36868 not in exif_ifd
