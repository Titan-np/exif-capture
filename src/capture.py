import ctypes
import ctypes.wintypes
import datetime
import os
import re
import threading

import win32gui
from PIL import ExifTags, ImageGrab, PngImagePlugin

import lib.filename_preset as filename_preset
import lib.notifier as notifier
import lib.paths as paths
import lib.settings as settings
import lib.windows_shell as windows_shell

# 撮影処理の連続実行による競合・滞留を防ぐためのロック
_capture_lock = threading.Lock()


def _get_active_window_properties():
    """
    現在アクティブになっているウィンドウのタイトルと画面上の座標を取得する

    Returns:
        tuple: ウィンドウタイトル（文字列）と、座標情報（左、上、右、下）のタプル
    """
    # 1. 画面上で最前面にあるウィンドウを取得
    window_handle = win32gui.GetForegroundWindow()

    # 2. ウィンドウのタイトルとクラス名を取得
    window_title = win32gui.GetWindowText(window_handle)
    class_name = win32gui.GetClassName(window_handle)

    # 3. ウィンドウタイトルが空 / 既知のシステムUIのクラス名に一致する場合、全画面を撮影対象とする
    _SYSTEM_CLASS_NAMES = (
        "Progman",  # デスクトップの背景ウィンドウ
        "WorkerW",  # デスクトップの背景ウィンドウ
        "Shell_TrayWnd",  # タスクバー
        "Shell_SecondaryTrayWnd",  # マルチディスプレイ時のタスクバー
        "NotifyIconOverflowWindow",  # タスクバーの折りたたまれているアイコン
        "TopLevelWindowForOverflowXamlIsland",  # タスクバーの折りたたまれているアイコン
        "ControlCenterWindow",  # タスクバーの設定画面
    )
    if not window_title or class_name in _SYSTEM_CLASS_NAMES:
        return "FullScreen", None

    # 4. ウィンドウの左上と右下のドット座標を取得
    # Windows 10/11ではGetWindowRectを使うと影部分も含めて取得されてしまうため、
    # DwmGetWindowAttributeを使って見た目通りの境界領域(Extended Frame Bounds)を取得する
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    rect = ctypes.wintypes.RECT()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(window_handle, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
    if result == 0:
        window_rectangle = (rect.left, rect.top, rect.right, rect.bottom)
    else:
        # DwmGetWindowAttributeが失敗した場合は、従来のGetWindowRectを使う(Windows 10以前を想定)
        window_rectangle = win32gui.GetWindowRect(window_handle)

    # 5. ウィンドウが最小化されているなど無効なサイズの場合は全画面を撮影対象とする
    left, top, right, bottom = window_rectangle
    if right - left <= 0 or bottom - top <= 0:
        return "FullScreen", None

    return window_title, window_rectangle


def _generate_output_path(window_title, captured_at):
    """
    スクリーンショットの保存先パスを生成する
    生成できない場合は、原因と対処を撮影失敗として通知する

    Args:
        window_title (str): ウィンドウのタイトル
        captured_at (datetime.datetime): ファイル名の {timestamp} に埋め込む撮影日時

    Returns:
        str | None: スクリーンショットの保存先パス。生成できない場合は None
    """

    def _notify_failure(message, buttons, log_message=None):
        """撮影失敗の通知を、原因のメッセージと対処用のボタンを指定して行う"""
        notifier.notify(
            category=notifier.NotificationCategory.ERROR,
            title="撮影に失敗しました。",
            message=message,
            log_message=log_message,
            buttons=buttons,
        )

    # 1. 保存先フォルダパスを取得・作成（失敗時はログ確認を促す）
    save_directory = windows_shell.ensure_save_directory()
    if not save_directory:
        _notify_failure(
            "保存先フォルダを準備できませんでした。詳細はログファイルを参照してください。",
            [notifier.NotificationButton.OPEN_LOG],
        )
        return None

    # 2. ファイル名プリセットを取得（例: "{timestamp}_{title}{dup}.png"）
    preset_pattern = settings.get("save.filenamePreset")

    # 3. ウィンドウタイトルをファイル名用に変換
    # Windowsのファイル名として使用できない禁止文字（記号と、タブ・改行などの制御文字 0x00〜0x1F）を安全な文字に置換する
    safe_title = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", window_title)

    # 4. ファイル名・フォルダパスを生成
    # プリセット書式エラー時は設定変更を促し、原因を特定できるよう例外の内容をログに残す
    try:
        output_path = filename_preset.build_output_path(save_directory, preset_pattern, safe_title, captured_at)
    except (KeyError, ValueError, IndexError) as exception:
        message = "ファイル名プリセットの書式が不正です。設定を見直してください。"
        _notify_failure(
            message,
            [notifier.NotificationButton.OPEN_SETTINGS, notifier.NotificationButton.OPEN_LOG],
            log_message=f"{message}\n{exception!r}",
        )
        return None

    # 5. ファイル名が Windows の最大パス長を超える場合はエラーとする
    # 設定画面では {title} が空として文字数チェックをしているため、実際のタイトル次第ではここでエラーになり得る
    if len(output_path) > paths.WINDOWS_MAX_PATH_LENGTH:
        _notify_failure(
            f"保存先パスが最大長({paths.WINDOWS_MAX_PATH_LENGTH}文字)を超えています。設定を見直してください。\n({output_path})",
            [notifier.NotificationButton.OPEN_SETTINGS, notifier.NotificationButton.OPEN_LOG],
        )
        return None

    return output_path


def _generate_exif_metadata(screenshot_image, captured_at):
    """
    画像に埋め込む撮影日時のメタデータ（EXIFデータとPNGテキストチャンク情報）を生成する
    読み取るアプリによって参照する項目が異なるため、日時に関わる項目をすべて同じ撮影日時で埋め込む
    （スクリーンショットでは、撮影・デジタル化・更新のいずれも撮影した瞬間を表すため、値が矛盾しない）
    設定で埋め込みが無効な場合は、日時に関わる項目を何も含めない（空の EXIF は保存時に書き込まれない）

    Args:
        screenshot_image (PIL.Image.Image): 撮影されたスクリーンショット画像
        captured_at (datetime.datetime): 埋め込む撮影日時

    Returns:
        tuple: EXIFメタデータとPNG情報オブジェクトのタプル
    """
    # 1. 画像の EXIF 情報と、PNG のテキストチャンク情報の保存先を用意
    exif_metadata = screenshot_image.getexif()
    png_info = PngImagePlugin.PngInfo()

    # 2. 設定で埋め込みが無効な場合は、何も埋め込まずに返す
    if not settings.get("save.embedDatetimeMetadata"):
        return exif_metadata, png_info

    # 3. 撮影日時を EXIF の日時書式（例: 2026:10:19 12:34:56）と、タイムゾーンの書式（例: +09:00）に変換
    # タイムゾーンが無いと、別のタイムゾーンで表示するサービス（Google フォト等）で時刻がずれるため併せて埋め込む
    exif_timestamp = captured_at.strftime("%Y:%m:%d %H:%M:%S")
    utc_offset = captured_at.astimezone().strftime("%z")
    exif_offset = f"{utc_offset[:3]}:{utc_offset[3:]}"

    # 4. EXIF の更新日時・撮影日時・デジタル化日時と、それぞれのタイムゾーンを埋め込む
    # 撮影日時が無い場合に、更新日時やデジタル化日時を代わりに読むアプリがあるため、すべて埋め込む
    exif_metadata[ExifTags.Base.DateTime] = exif_timestamp  # 更新日時
    exif_ifd = exif_metadata.get_ifd(ExifTags.IFD.Exif)
    exif_ifd[ExifTags.Base.OffsetTime] = exif_offset  # 更新日時のタイムゾーン
    exif_ifd[ExifTags.Base.DateTimeOriginal] = exif_timestamp  # 撮影日時
    exif_ifd[ExifTags.Base.OffsetTimeOriginal] = exif_offset  # 撮影日時のタイムゾーン
    exif_ifd[ExifTags.Base.DateTimeDigitized] = exif_timestamp  # デジタル化日時
    exif_ifd[ExifTags.Base.OffsetTimeDigitized] = exif_offset  # デジタル化日時のタイムゾーン

    # 5. PNG の作成日時を埋め込む
    # Windows のエクスプローラーは PNG の EXIF を読まず、この項目を「撮影日時」として表示するため必須
    png_info.add_text("Creation Time", exif_timestamp)

    return exif_metadata, png_info


def play_capture_sound(volume=None):
    """
    撮影時の通知音（MP3ファイル）を指定された音量で再生する

    Args:
        volume (int, optional): 再生音量（0〜100）。省略時は設定値を使用する
    """
    # 1. 音量の指定が無い場合は設定値を使い、0以下の場合は再生しない（無音）
    if volume is None:
        volume = settings.get("capture.soundVolume")
    if volume is None or volume <= 0:
        return

    # 2. 音声ファイルのパスを取得
    sound_path = paths.resolve_asset_path("capture_sound.mp3")

    try:
        # 3. WindowsのMCIコマンドでMP3を再生する
        mci_send = ctypes.windll.winmm.mciSendStringW

        # 3-1. 再生直後にcloseすると一瞬で音が途切れてしまう / 再生終了を待ってからcloseするとアプリを一時停止させることになるため、
        # 次回の再生前に以前の再生セッションをcloseする（初回は開いていないため必ず失敗するので、戻り値は確認しない）
        mci_send("close capture_sound", None, 0, 0)

        # 3-2. MCIの音量は0〜1000の範囲で指定する（0%〜100%を0〜1000にスケール変換）
        mci_volume = max(0, min(1000, int(volume * 10)))

        # 3-3. 開く・音量設定・再生を順に送信する
        # mciSendStringW は失敗時に例外ではなくエラーコード（0以外）を返すため、戻り値で判定してログに残し、以降の送信を中止する
        for command in (
            f'open "{sound_path}" type mpegvideo alias capture_sound',
            f"setaudio capture_sound volume to {mci_volume}",
            "play capture_sound",
        ):
            error_code = mci_send(command, None, 0, 0)
            if error_code != 0:
                notifier.log(f"通知音の再生に失敗しました。(コマンド: {command} / エラーコード: {error_code})")
                return
    except Exception as exception:
        notifier.log(f"通知音の再生に失敗しました。\n{exception}")


def capture_screenshot():
    """
    アクティブウィンドウをキャプチャし保存する
    """
    # 1. 連続押しによる多重実行を防止する（すでに撮影処理が走っている場合はスキップ）
    if not _capture_lock.acquire(blocking=False):
        notifier.log("撮影処理が実行中のため、キー入力をスキップしました。")
        return

    try:
        # 2. 撮影の直前に最新の設定を読み込む
        settings.load()

        # 3. アクティブウィンドウのタイトル・座標を取得
        window_title, window_rectangle = _get_active_window_properties()

        # 4. スクリーンショットを撮影し、撮影日時を取得
        if window_rectangle is None:
            # アクティブなウィンドウがない（デスクトップやタスクバー等）場合は全画面を撮影
            screenshot_image = ImageGrab.grab(all_screens=True)
        else:
            # ウィンドウの座標が取得できた場合はその領域を撮影
            left, top, right, bottom = window_rectangle
            screenshot_image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)

        # 撮影日時を1回だけ取得し、ファイル名と EXIF の双方で使う（別々に取得すると秒の境目でずれるため）
        captured_at = datetime.datetime.now()

        # 5. 保存先パス生成（プリセット書式エラー時・パス長超過時は None が返る）
        output_path = _generate_output_path(window_title, captured_at)
        if output_path is None:
            return

        # 6. EXIFデータ・PNG情報を生成
        exif_metadata, png_info = _generate_exif_metadata(screenshot_image, captured_at)

        # 7. スクリーンショットを保存
        screenshot_image.save(output_path, "PNG", exif=exif_metadata, pnginfo=png_info)

        # 8. 通知音を鳴らす（設定で有効な場合）
        play_capture_sound()

        # 9. Windows通知・ログ出力
        notifier.notify(
            category=notifier.NotificationCategory.CAPTURE,
            title="スクリーンショットを撮影しました。",
            message=os.path.basename(output_path),
            buttons=[notifier.NotificationButton.OPEN_IMAGE, notifier.NotificationButton.OPEN_FOLDER],
            image_path=output_path,
        )

    except Exception as exception:
        # エラー通知・ログ出力
        notifier.error("撮影に失敗しました。", str(exception))

    finally:
        # 撮影処理完了後にロックを解放
        _capture_lock.release()
