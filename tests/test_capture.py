"""
capture モジュールの単体テスト
アクティブウィンドウの判定、保存先パス生成ロジック、EXIFメタデータ生成ロジック、撮影から保存・通知までの流れ、多重実行防止、通知音の再生を検証する
"""

import datetime
import os
import re
from unittest.mock import MagicMock

import pytest
from PIL import ExifTags, Image

import capture

# テストで使う撮影日時
_CAPTURED_AT = datetime.datetime(2026, 10, 19, 12, 34, 56)


class TestGenerateOutputPath:
    """
    スクリーンショット保存先パスの生成ロジック（_generate_output_path）に関するテストクラス
    """

    def test_generate_output_path_replaces_forbidden_characters(self, monkeypatch):
        """ウィンドウタイトルに含まれる禁止文字（記号・制御文字）がアンダースコアへ正しく置換されることを検証する"""
        # 保存先フォルダとプリセット設定をモック化
        monkeypatch.setattr("lib.windows_shell.ensure_save_directory", lambda: "C:\\Screenshots")
        monkeypatch.setattr("lib.settings.get", lambda key: "{title}.png" if key == "save.filenamePreset" else None)

        # 記号9文字と、制御文字（タブ・改行）2文字を含むタイトル
        unsafe_window_title = 'Sample\\/:*?"<>|\t\nWindow'
        generated_path = capture._generate_output_path(unsafe_window_title, _CAPTURED_AT)

        expected_filename = "Sample___________Window.png"
        assert os.path.basename(generated_path) == expected_filename

    def test_generate_output_path_formats_timestamp_and_title(self, monkeypatch):
        """タイムスタンプとウィンドウタイトルを含む標準プリセットで正しくパスが組み立てられることを検証する"""
        monkeypatch.setattr("lib.windows_shell.ensure_save_directory", lambda: "C:\\Screenshots")
        monkeypatch.setattr("lib.settings.get", lambda key: "{timestamp}_{title}.png" if key == "save.filenamePreset" else None)

        generated_path = capture._generate_output_path("AppTitle", _CAPTURED_AT)

        assert generated_path is not None
        assert generated_path.startswith("C:\\Screenshots\\")
        assert generated_path.endswith("_AppTitle.png")

    def test_generate_output_path_rejects_path_exceeding_max_length(self, monkeypatch):
        """Windows のパス最大長（259文字）を超過した場合に安全に None を返すことを検証する"""
        # 非常に長いディレクトリパスをモック
        long_directory_path = "C:\\" + "a" * 240
        monkeypatch.setattr("lib.windows_shell.ensure_save_directory", lambda: long_directory_path)
        monkeypatch.setattr("lib.settings.get", lambda key: "{title}.png" if key == "save.filenamePreset" else None)

        long_window_title = "long_title_" * 10
        generated_path = capture._generate_output_path(long_window_title, _CAPTURED_AT)

        # パス長が259文字を超えるため None が返ることを確認
        assert generated_path is None

    def test_generate_output_path_handles_format_error(self, monkeypatch, mock_notifier_actions):
        """プリセットの書式エラー時に None を返し、原因となった例外の内容をログ用メッセージに含めて通知することを検証する"""
        monkeypatch.setattr("lib.windows_shell.ensure_save_directory", lambda: "C:\\Screenshots")
        # 未定義のプレースホルダを含むプリセット
        monkeypatch.setattr("lib.settings.get", lambda key: "{invalid_key}.png" if key == "save.filenamePreset" else None)

        generated_path = capture._generate_output_path("TestTitle", _CAPTURED_AT)

        assert generated_path is None
        assert "invalid_key" in mock_notifier_actions["notify"].call_args.kwargs["log_message"]

    def test_generate_output_path_notifies_when_save_directory_unavailable(self, monkeypatch, mock_notifier_actions):
        """保存先フォルダを準備できない場合に None を返し、撮影失敗を通知することを検証する"""
        monkeypatch.setattr("lib.windows_shell.ensure_save_directory", lambda: None)

        generated_path = capture._generate_output_path("TestTitle", _CAPTURED_AT)

        assert generated_path is None
        assert mock_notifier_actions["notify"].call_args.kwargs["title"] == "撮影に失敗しました。"


class TestGetActiveWindowProperties:
    """
    アクティブウィンドウのタイトルと座標の取得（_get_active_window_properties）に関するテストクラス
    """

    @pytest.fixture
    def mock_window(self, monkeypatch):
        """
        win32gui と DwmGetWindowAttribute をモック化し、アクティブウィンドウの情報を差し替えられるようにする fixture
        DwmGetWindowAttribute は失敗（0以外）を返し、座標は GetWindowRect の戻り値を使わせる

        Args:
            monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

        Returns:
            dict: タイトル・クラス名・座標の設定値（テスト内で書き換える）
        """
        window = {"title": "AppTitle", "class_name": "Notepad", "rectangle": (10, 20, 110, 220)}
        monkeypatch.setattr(capture.win32gui, "GetForegroundWindow", lambda: 1)
        monkeypatch.setattr(capture.win32gui, "GetWindowText", lambda window_handle: window["title"])
        monkeypatch.setattr(capture.win32gui, "GetClassName", lambda window_handle: window["class_name"])
        monkeypatch.setattr(capture.win32gui, "GetWindowRect", lambda window_handle: window["rectangle"])
        monkeypatch.setattr(capture.ctypes.windll, "dwmapi", MagicMock(DwmGetWindowAttribute=MagicMock(return_value=1)))
        return window

    def test_returns_title_and_rectangle_of_normal_window(self, mock_window):
        """通常のウィンドウでは、タイトルと座標（DWM 失敗時は GetWindowRect の値）を返すことを検証する"""
        assert capture._get_active_window_properties() == ("AppTitle", (10, 20, 110, 220))

    def test_returns_full_screen_for_empty_title(self, mock_window):
        """タイトルが空のウィンドウでは、全画面を撮影対象とすることを検証する"""
        mock_window["title"] = ""
        assert capture._get_active_window_properties() == ("FullScreen", None)

    def test_returns_full_screen_for_system_window(self, mock_window):
        """タスクバーなどのシステムUIのウィンドウでは、全画面を撮影対象とすることを検証する"""
        mock_window["class_name"] = "Shell_TrayWnd"
        assert capture._get_active_window_properties() == ("FullScreen", None)

    def test_returns_full_screen_for_minimized_window(self, mock_window):
        """最小化などで幅・高さが0のウィンドウでは、全画面を撮影対象とすることを検証する"""
        mock_window["rectangle"] = (0, 0, 0, 0)
        assert capture._get_active_window_properties() == ("FullScreen", None)


class TestGenerateExifMetadata:
    """
    EXIFメタデータおよびPNGテキスト情報の生成（_generate_exif_metadata）に関するテストクラス
    """

    def test_generate_exif_metadata_embeds_all_datetime_items_when_enabled(self, monkeypatch):
        """設定が有効な場合、EXIF の更新日時・撮影日時・デジタル化日時とタイムゾーン、PNG の作成日時がすべて同じ撮影日時で付与されることを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: True if key == "save.embedDatetimeMetadata" else None)

        test_image = Image.new("RGB", (16, 16), color=(0, 0, 0))
        exif_metadata, png_info = capture._generate_exif_metadata(test_image, _CAPTURED_AT)

        # 更新日時（0th IFD）と、撮影日時・デジタル化日時（Exif IFD）が撮影日時になっていることを確認
        exif_ifd = exif_metadata.get_ifd(ExifTags.IFD.Exif)
        assert exif_metadata[ExifTags.Base.DateTime] == "2026:10:19 12:34:56"
        assert exif_ifd[ExifTags.Base.DateTimeOriginal] == "2026:10:19 12:34:56"
        assert exif_ifd[ExifTags.Base.DateTimeDigitized] == "2026:10:19 12:34:56"

        # タイムゾーンが「+09:00」形式で3項目とも付与されていることを確認
        for offset_tag in (ExifTags.Base.OffsetTime, ExifTags.Base.OffsetTimeOriginal, ExifTags.Base.OffsetTimeDigitized):
            assert re.fullmatch(r"[+-]\d{2}:\d{2}", exif_ifd[offset_tag])

        # PNG のテキストチャンクに Creation Time が追加されていることを確認
        assert (b"tEXt", b"Creation Time\x002026:10:19 12:34:56") in [chunk[:2] for chunk in png_info.chunks]

    def test_generate_exif_metadata_embeds_nothing_when_disabled(self, monkeypatch):
        """設定が無効な場合、日時に関わる EXIF 項目と PNG の作成日時がどれも付与されないことを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: False if key == "save.embedDatetimeMetadata" else None)

        test_image = Image.new("RGB", (16, 16), color=(0, 0, 0))
        exif_metadata, png_info = capture._generate_exif_metadata(test_image, _CAPTURED_AT)

        # EXIF が空（保存時に書き込まれない）で、PNG のテキストチャンクも無いことを確認
        assert len(exif_metadata) == 0
        assert png_info.chunks == []


class TestCaptureScreenshot:
    """
    撮影から保存・通知までの一連の処理（capture_screenshot）に関するテストクラス
    """

    @pytest.fixture
    def capture_environment(self, monkeypatch, tmp_path):
        """
        画面取得・アクティブウィンドウ取得・設定値をモック化し、一時フォルダへ保存させる fixture

        Args:
            monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト
            tmp_path (pathlib.Path): pytest が提供する一時ディレクトリのパス

        Returns:
            pathlib.Path: 撮影した画像の保存先フォルダ
        """
        # 撮影時に使う設定値（通知音は鳴らさない）
        setting_values = {
            "save.directory": str(tmp_path),
            "save.filenamePreset": "{timestamp}_{title}.png",
            "save.embedDatetimeMetadata": True,
            "capture.soundVolume": 0,
        }
        monkeypatch.setattr("lib.settings.load", MagicMock())
        monkeypatch.setattr("lib.settings.get", lambda key: setting_values.get(key))
        monkeypatch.setattr(capture, "_get_active_window_properties", lambda: ("AppTitle", (0, 0, 16, 16)))
        monkeypatch.setattr(capture.ImageGrab, "grab", lambda **kwargs: Image.new("RGB", (16, 16), color=(255, 255, 255)))
        return tmp_path

    def test_saved_image_has_same_time_in_filename_and_exif(self, capture_environment):
        """保存した画像の EXIF の撮影日時が、ファイル名の {timestamp} と同じ時刻であることを検証する"""
        capture.capture_screenshot()

        # 保存された1枚の画像を取得し、ファイル名の日時（例: 20261019_123456）を EXIF の書式に変換する
        saved_files = list(capture_environment.glob("*.png"))
        assert len(saved_files) == 1
        filename_time = datetime.datetime.strptime(saved_files[0].name.split("_AppTitle")[0], "%Y%m%d_%H%M%S")

        # 保存した画像から EXIF の撮影日時を読み取り、ファイル名の日時と比較する
        with Image.open(saved_files[0]) as saved_image:
            exif_ifd = saved_image.getexif().get_ifd(34665)
        assert exif_ifd[36867] == filename_time.strftime("%Y:%m:%d %H:%M:%S")

    def test_notifies_capture_with_saved_image(self, capture_environment, mock_notifier_actions):
        """撮影後に、保存した画像を添えた撮影時の通知を送ることを検証する"""
        capture.capture_screenshot()

        notify_arguments = mock_notifier_actions["notify"].call_args.kwargs
        assert notify_arguments["category"] == capture.notifier.NotificationCategory.CAPTURE
        assert notify_arguments["image_path"] == str(next(capture_environment.glob("*.png")))


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
        # MCIは成功時に0を返す
        mock_mci_send = MagicMock(return_value=0)
        monkeypatch.setattr(capture.ctypes.windll.winmm, "mciSendStringW", mock_mci_send)

        capture.play_capture_sound(50)

        # 送信されたMCIコマンド文字列（第1引数）を抽出して確認
        sent_commands = [call_arguments.args[0] for call_arguments in mock_mci_send.call_args_list]
        assert "setaudio capture_sound volume to 500" in sent_commands
        assert sent_commands[-1] == "play capture_sound"

    def test_logs_and_stops_when_mci_command_fails(self, monkeypatch, mock_notifier_actions):
        """MCIコマンドがエラーコードを返した場合、ログに残して以降のコマンドを送信しないことを検証する"""

        # open のみ失敗（エラーコード 263: ファイルを開けない）させ、他のコマンドは成功させる
        def fake_mci_send(command, *args):
            return 263 if command.startswith("open") else 0

        mock_mci_send = MagicMock(side_effect=fake_mci_send)
        monkeypatch.setattr(capture.ctypes.windll.winmm, "mciSendStringW", mock_mci_send)

        capture.play_capture_sound(50)

        # 失敗がエラーコード付きでログに残り、再生コマンドは送信されないことを確認
        sent_commands = [call_arguments.args[0] for call_arguments in mock_mci_send.call_args_list]
        assert "play capture_sound" not in sent_commands
        mock_notifier_actions["log"].assert_called_once()
        assert "エラーコード: 263" in mock_notifier_actions["log"].call_args.args[0]
