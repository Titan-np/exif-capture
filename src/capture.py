import os
import sys
import re
import datetime
import ctypes
import ctypes.wintypes
import threading
import win32gui
from PIL import ImageGrab, PngImagePlugin

from settings_manager import *
from utils import *
from constants import *
from notifier import *

# Windows の最大パス長（MAX_PATH 260 から終端文字分を引いた値）
_WINDOWS_MAX_PATH_LENGTH = 259

# 撮影処理の連続実行による競合・滞留を防ぐためのロック
_capture_lock = threading.Lock()


class _FormattableTimestamp(datetime.datetime):
    """
    ファイル名プリセットの {timestamp} に対応する datetime サブクラス
    書式指定がない場合はデフォルト書式を使用する
    """

    _DEFAULT_FORMAT = "%Y%m%d_%H%M%S"

    def __format__(self, spec):
        # 書式指定がない場合はデフォルト書式を使用する
        if not spec:
            return self.strftime(self._DEFAULT_FORMAT)
        return self.strftime(spec)


def _get_active_window_properties():
    """
    現在アクティブになっているウィンドウのタイトルと画面上の座標を取得する

    Returns:
        tuple: ウィンドウタイトル（文字列）と、座標情報（左、上、右、下）のタプル
    """
    # 画面上で最前面にあるウィンドウを取得
    window_handle = win32gui.GetForegroundWindow()

    # ウィンドウのタイトルとクラス名を取得
    window_title = win32gui.GetWindowText(window_handle)
    class_name = win32gui.GetClassName(window_handle)

    # ウィンドウタイトルが空 / 既知のシステムUIのクラス名に一致する場合、全画面を撮影対象とする
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

    # ウィンドウの左上と右下のドット座標を取得
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

    # ウィンドウが最小化されているなど無効なサイズの場合の処理
    left, top, right, bottom = window_rectangle
    if right - left <= 0 or bottom - top <= 0:
        return "FullScreen", None

    return window_title, window_rectangle


def _generate_output_path(window_title):
    """
    スクリーンショットの保存先パスを生成する

    Args:
        window_title (str): ウィンドウのタイトル

    Returns:
        str: スクリーンショットの保存先パス
    """

    # 保存先フォルダパスを取得し、フォルダが無ければ作成
    save_directory = settings.get("save.directory")
    if not os.path.exists(save_directory):
        os.makedirs(save_directory)

    # ファイル名プリセットを取得（例: "{timestamp}_{title}.png"）
    preset_pattern = settings.get("save.filenamePreset")

    # ウィンドウタイトルをファイル名用に変換
    # Windowsのファイル名として使用できない禁止文字を安全な文字に置換する
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", window_title)

    # 現在時刻を取得（書式指定対応のタイムスタンプ）
    current_time = _FormattableTimestamp.now()

    # ファイル名・フォルダパスを生成
    try:
        output_filename = preset_pattern.format(timestamp=current_time, title=safe_title)
    except (KeyError, ValueError, IndexError) as exception:
        # プリセット書式エラー時は設定変更を促す
        notifier.notify(
            title="撮影に失敗しました。",
            message="ファイル名プリセットの書式が不正です。設定画面で修正してください。",
            buttons=[BUTTON_OPEN_SETTINGS, BUTTON_OPEN_LOG],
        )
        return None

    output_path = os.path.join(save_directory, output_filename)

    # ファイル名が Windows の最大パス長を超える場合はエラーとする
    if len(output_path) > _WINDOWS_MAX_PATH_LENGTH:
        notifier.notify(
            title="撮影に失敗しました。",
            message=f"保存先パスが最大長({_WINDOWS_MAX_PATH_LENGTH}文字)を超えています。設定を見直してください。\n({output_path})",
            buttons=[BUTTON_OPEN_SETTINGS, BUTTON_OPEN_LOG],
        )
        return None

    return output_path


def _generate_exif_metadata(screenshot_image):
    """
    画像に埋め込むEXIFデータとPNGテキストチャンク情報を生成する

    Args:
        screenshot_image (PIL.Image.Image): 撮影されたスクリーンショット画像

    Returns:
        tuple: EXIFメタデータとPNG情報オブジェクトのタプル
    """
    # 現在時刻のタイムスタンプを取得
    current_time = datetime.datetime.now()
    exif_timestamp = current_time.strftime("%Y:%m:%d %H:%M:%S")

    # 情報保存先を取得
    exif_metadata = screenshot_image.getexif()
    png_info = PngImagePlugin.PngInfo()

    # ファイル更新日時を埋め込む
    exif_metadata[306] = exif_timestamp  # ファイル更新日時(EXIF)
    png_info.add_text("Creation Time", exif_timestamp)  # ファイル作成日時(PNG)

    # 画像を保存する。設定でEXIFメタデータの埋め込みが有効な場合はそれを含める。
    if settings.get("save.embedDatetimeMetadata"):
        exif_ifd = exif_metadata.get_ifd(34665)
        exif_ifd[36867] = exif_timestamp  # 撮影日時
        exif_ifd[36868] = exif_timestamp  # デジタル化日時

    return exif_metadata, png_info


def play_capture_sound(volume=None):
    """
    撮影時の通知音（MP3ファイル）を指定された音量で再生する

    Args:
        volume (int, optional): 再生音量（0〜100）。省略時は設定値を使用する
    """
    if volume is None:
        volume = settings.get("capture.soundVolume")

    # 音量が0以下の場合は再生しない（無音）
    if volume is None or volume <= 0:
        return

    # 音声ファイルのパスを取得
    sound_path = get_asset_path("capture_sound.mp3")

    try:
        # WindowsのMCIコマンドでMP3を再生する
        mci_send = ctypes.windll.winmm.mciSendStringW
        # 再生直後にcloseすると一瞬で音が途切れてしまう / 再生終了を待ってからcloseするとアプリを一時停止させることになるため、
        # 次回の再生前に以前の再生セッションをcloseする
        mci_send("close capture_sound", None, 0, 0)
        mci_send(f'open "{sound_path}" type mpegvideo alias capture_sound', None, 0, 0)
        # MCIの音量は0〜1000の範囲で指定する（0%〜100%を0〜1000にスケール変換）
        mci_volume = max(0, min(1000, int(volume * 10)))
        mci_send(f"setaudio capture_sound volume to {mci_volume}", None, 0, 0)
        mci_send("play capture_sound", None, 0, 0)
    except Exception as exception:
        notifier.log(f"通知音の再生に失敗しました。\n{exception}")


def capture_screenshot():
    """
    アクティブウィンドウをキャプチャし保存する
    """
    # 連続押しによる多重実行を防止する（すでに撮影処理が走っている場合はスキップ）
    if not _capture_lock.acquire(blocking=False):
        notifier.log("撮影処理が実行中のため、キー入力をスキップしました。")
        return

    try:
        # 1. 撮影の直前に最新の設定を読み込む
        settings.load()

        # 2. アクティブウィンドウのタイトル・座標を取得
        window_title, window_rectangle = _get_active_window_properties()

        # 3. スクリーンショットを撮影
        if window_rectangle is None:
            # アクティブなウィンドウがない（デスクトップやタスクバー等）場合は全画面を撮影
            screenshot_image = ImageGrab.grab(all_screens=True)
        else:
            # ウィンドウの座標が取得できた場合はその領域を撮影
            left, top, right, bottom = window_rectangle
            screenshot_image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)

        # 4. 保存先パス生成（プリセット書式エラー時・パス長超過時は None が返る）
        output_path = _generate_output_path(window_title)
        if output_path is None:
            return

        # 5. EXIFデータ・PNG情報を生成
        exif_metadata, png_info = _generate_exif_metadata(screenshot_image)

        # 6. スクリーンショットを保存
        screenshot_image.save(output_path, "PNG", exif=exif_metadata, pnginfo=png_info)

        # 7. 通知音を鳴らす（設定で有効な場合）
        play_capture_sound()

        # 8. Windows通知・ログ出力
        notifier.notify(
            title="スクリーンショットを撮影しました。",
            message=os.path.basename(output_path),
            buttons=[BUTTON_OPEN_IMAGE, BUTTON_OPEN_FOLDER],
            image_path=output_path,
        )

    except Exception as exception:
        # エラー通知・ログ出力
        notifier.notify(
            title="撮影に失敗しました。",
            message="エラーが発生しました。詳細はログファイルを参照してください。",
            log_message=f"エラーが発生しました。\n{exception}",
            buttons=[BUTTON_OPEN_LOG],
        )

    finally:
        # 撮影処理完了後にロックを解放
        _capture_lock.release()
