"""
capture モジュールの単体テスト
保存先パス生成ロジック、EXIFメタデータ生成ロジック、多重実行防止、通知音の音量変換を検証する
"""

import os
from unittest.mock import MagicMock

from PIL import Image

import capture


class TestGenerateOutputPath:
    """
    スクリーンショット保存先パスの生成ロジック（_generate_output_path）に関するテストクラス
    """

    def test_generate_output_path_replaces_forbidden_characters(self, monkeypatch):
        """ウィンドウタイトルに含まれる禁止文字がアンダースコアへ正しく置換されることを検証する"""
        # 保存先フォルダとプリセット設定をモック化
        monkeypatch.setattr("lib.utils.ensure_save_directory", lambda: "C:\\Screenshots")
        monkeypatch.setattr("lib.settings.get", lambda key: "{title}.png" if key == "save.filenamePreset" else None)

        unsafe_window_title = 'Sample\\/:*?"<>|Window'
        generated_path = capture._generate_output_path(unsafe_window_title)

        expected_filename = "Sample_________Window.png"
        assert os.path.basename(generated_path) == expected_filename

    def test_generate_output_path_formats_timestamp_and_title(self, monkeypatch):
        """タイムスタンプとウィンドウタイトルを含む標準プリセットで正しくパスが組み立てられることを検証する"""
        monkeypatch.setattr("lib.utils.ensure_save_directory", lambda: "C:\\Screenshots")
        monkeypatch.setattr("lib.settings.get", lambda key: "{timestamp}_{title}.png" if key == "save.filenamePreset" else None)

        generated_path = capture._generate_output_path("AppTitle")

        assert generated_path is not None
        assert generated_path.startswith("C:\\Screenshots\\")
        assert generated_path.endswith("_AppTitle.png")

    def test_generate_output_path_avoids_existing_file(self, monkeypatch, tmp_path):
        """同名ファイルがある場合に {dup} の連番付きパスが返ることを検証する"""
        monkeypatch.setattr("lib.utils.ensure_save_directory", lambda: str(tmp_path))
        monkeypatch.setattr("lib.settings.get", lambda key: "{title}{dup}.png" if key == "save.filenamePreset" else None)
        (tmp_path / "AppTitle.png").touch()

        generated_path = capture._generate_output_path("AppTitle")

        assert os.path.basename(generated_path) == "AppTitle (2).png"

    def test_generate_output_path_rejects_path_exceeding_max_length(self, monkeypatch):
        """Windows のパス最大長（259文字）を超過した場合に安全に None を返すことを検証する"""
        # 非常に長いディレクトリパスをモック
        long_directory_path = "C:\\" + "a" * 240
        monkeypatch.setattr("lib.utils.ensure_save_directory", lambda: long_directory_path)
        monkeypatch.setattr("lib.settings.get", lambda key: "{title}.png" if key == "save.filenamePreset" else None)

        long_window_title = "long_title_" * 10
        generated_path = capture._generate_output_path(long_window_title)

        # パス長が259文字を超えるため None が返ることを確認
        assert generated_path is None

    def test_generate_output_path_handles_format_error(self, monkeypatch):
        """プリセットのフォーマットで例外（KeyErrorなど）が発生した場合に None を返すことを検証する"""
        monkeypatch.setattr("lib.utils.ensure_save_directory", lambda: "C:\\Screenshots")
        # 未定義のプレースホルダを含むプリセット
        monkeypatch.setattr("lib.settings.get", lambda key: "{invalid_key}.png" if key == "save.filenamePreset" else None)

        generated_path = capture._generate_output_path("TestTitle")
        assert generated_path is None


class TestGenerateExifMetadata:
    """
    EXIFメタデータおよびPNGテキスト情報の生成（_generate_exif_metadata）に関するテストクラス
    """

    def test_generate_exif_metadata_embeds_modification_time_and_png_info(self, monkeypatch):
        """更新日時とPNGテキスト情報が常に画像情報へ付与されることを検証する"""
        # メタデータ埋め込み設定を無効化
        monkeypatch.setattr("lib.settings.get", lambda key: False if key == "save.embedDatetimeMetadata" else None)

        # テスト用の小型ダミー画像を生成
        test_image = Image.new("RGB", (16, 16), color=(255, 255, 255))
        exif_metadata, png_info = capture._generate_exif_metadata(test_image)

        # EXIF タグ 306（更新日時）が格納されていることを確認
        assert 306 in exif_metadata
        assert isinstance(exif_metadata[306], str)

        # PNG のテキストチャンクに Creation Time が追加されていることを確認
        assert png_info is not None

    def test_generate_exif_metadata_embeds_shooting_time_when_enabled(self, monkeypatch):
        """設定が有効な場合、EXIF撮影日時（36867）およびデジタル化日時（36868）が付与されることを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: True if key == "save.embedDatetimeMetadata" else None)

        test_image = Image.new("RGB", (16, 16), color=(0, 0, 0))
        exif_metadata, _ = capture._generate_exif_metadata(test_image)

        # Exif IFD (34665) から詳細タグを取得
        exif_ifd = exif_metadata.get_ifd(34665)
        assert 36867 in exif_ifd  # 撮影日時
        assert 36868 in exif_ifd  # デジタル化日時

    def test_generate_exif_metadata_skips_shooting_time_when_disabled(self, monkeypatch):
        """設定が無効な場合、EXIF撮影日時（36867）が付与されないことを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: False if key == "save.embedDatetimeMetadata" else None)

        test_image = Image.new("RGB", (16, 16), color=(0, 0, 0))
        exif_metadata, _ = capture._generate_exif_metadata(test_image)

        # Exif IFD (34665) 内にタグが存在しないことを確認
        exif_ifd = exif_metadata.get_ifd(34665)
        assert 36867 not in exif_ifd
        assert 36868 not in exif_ifd


class TestCaptureLock:
    """
    撮影処理の多重実行防止（_capture_lock）に関するテストクラス
    """

    def test_skips_capture_while_running(self, monkeypatch, mock_notifier_actions):
        """撮影処理の実行中にキー入力があった場合、撮影せずにスキップのログのみ出力されることを検証する"""
        mock_settings_load = MagicMock()
        monkeypatch.setattr("lib.settings.load", mock_settings_load)

        # 撮影処理が実行中の状態を再現するため、ロックを先に取得しておく
        capture._capture_lock.acquire()
        try:
            capture.capture_screenshot()
        finally:
            capture._capture_lock.release()

        # 撮影処理の最初の手順（設定の読み込み）に進んでいないことを確認
        mock_settings_load.assert_not_called()
        mock_notifier_actions["log"].assert_called_once_with("撮影処理が実行中のため、キー入力をスキップしました。")


class TestPlayCaptureSound:
    """
    撮影時の通知音の再生（play_capture_sound）に関するテストクラス
    """

    def test_does_not_play_when_volume_is_zero(self, monkeypatch):
        """音量0%の場合、MCIコマンドを一切送信しないことを検証する"""
        mock_mci_send = MagicMock()
        monkeypatch.setattr(capture.ctypes.windll.winmm, "mciSendStringW", mock_mci_send)

        capture.play_capture_sound(0)

        mock_mci_send.assert_not_called()

    def test_plays_with_scaled_volume(self, monkeypatch):
        """音量0〜100%がMCIの0〜1000にスケール変換されて再生されることを検証する"""
        mock_mci_send = MagicMock()
        monkeypatch.setattr(capture.ctypes.windll.winmm, "mciSendStringW", mock_mci_send)

        capture.play_capture_sound(50)

        # 送信されたMCIコマンド文字列（第1引数）を抽出して確認
        sent_commands = [call_arguments.args[0] for call_arguments in mock_mci_send.call_args_list]
        assert "setaudio capture_sound volume to 500" in sent_commands
        assert sent_commands[-1] == "play capture_sound"
