import os
import sys
import threading
import multiprocessing
import pystray
from PIL import Image

from settings_manager import *
from settings_ui import *
from capture import *
from utils import *
from constants import *
from notifier import *
from hotkey_manager import HotkeyManager

# ホットキー管理者インスタンス
_hotkey_manager = None


def _create_tray_icon_image():
    """
    通知領域に表示するためのアイコン画像を読み込む

    Returns:
        PIL.Image.Image: 生成されたアイコン画像
    """
    # アイコン保存先パスを取得
    icon_path = get_asset_path("icon.ico", "icon_dev.ico")

    try:
        # アイコン画像を読み込む
        return Image.open(icon_path)
    except Exception as exception:
        # 読み込みに失敗した場合はダミー画像として水色の四角を返す
        notifier.log(f"アイコン画像の読み込みに失敗しました。\n{exception}")
        icon_image = Image.new("RGB", (64, 64), color=(0, 128, 255))
        return icon_image


def _watch_update_event():
    """
    設定画面からの更新通知イベント（settings_update_event）を待機し、
    ホットキーマネージャーに再読み込みを要求する監視ループ
    """
    while True:
        # 設定変更イベントが発火するまで待機
        settings_update_event.wait()
        settings_update_event.clear()

        # 設定変更に伴いホットキーを再登録
        if _hotkey_manager is not None:
            _hotkey_manager.reload()


def _close_application(tray_icon_instance, menu_item_instance):
    """
    通知領域への常駐とキーボード監視を終了する

    Args:
        tray_icon_instance (pystray.Icon): 制御対象のトレイアイコンオブジェクト
        menu_item_instance (pystray.MenuItem): クリックされたメニュー項目オブジェクト
    """
    # ホットキー監視を停止
    global _hotkey_manager
    if _hotkey_manager is not None:
        _hotkey_manager.stop()

    # 通知領域からアイコンを削除し、アプリケーションの実行を終了する
    notifier.notify("終了します。", "")
    tray_icon_instance.stop()


def _open_save_directory(icon, item):
    """保存先フォルダをエクスプローラーで開く"""
    save_directory = settings.get("save.directory")
    if os.path.exists(save_directory):
        os.startfile(save_directory)
    else:
        notifier.notify("保存先フォルダが存在しません。", save_directory, buttons=[BUTTON_OPEN_SETTINGS])


def _open_log_file(icon, item):
    """ログファイルを規定のテキストエディタで開く"""
    log_file_path = os.path.join(get_app_path("logs"), "app.log")
    if os.path.exists(log_file_path):
        os.startfile(log_file_path)
    else:
        notifier.notify("ログファイルが存在しません。", log_file_path)


def _launch_application():
    """
    通知領域への常駐とキーボード監視を開始する
    """
    # ホットキー管理クラスをインスタンス化して監視を開始
    global _hotkey_manager
    _hotkey_manager = HotkeyManager(callback_function=capture_screenshot)
    _hotkey_manager.start()
    # TODO: ホットキー登録に失敗した場合のエラーハンドリングを追加する

    # 設定変更通知を監視するスレッドを起動
    update_watcher_thread = threading.Thread(target=_watch_update_event, daemon=True)
    update_watcher_thread.start()

    # 通知領域に常駐させるアイコンと右クリックメニューを設定する
    tray_menu = pystray.Menu(
        pystray.MenuItem("設定を開く", open_settings_window, default=True),
        pystray.MenuItem("保存先フォルダを開く", _open_save_directory),
        pystray.MenuItem("ログファイルを開く", _open_log_file),
        pystray.MenuItem("終了", _close_application),
    )
    tray_icon = pystray.Icon(name=APP_NAME, icon=_create_tray_icon_image(), title=APP_NAME, menu=tray_menu)

    # 通知領域での常駐を開始してメインループを起動する
    shortcut_key = settings.get("capture.triggerShortcut")
    notifier.notify(f"起動しました。(v{APP_VERSION})", f"ショートカットキー ({shortcut_key}) を押すとスクリーンショットを撮影します。")
    tray_icon.run()


# ここから実行
if __name__ == "__main__":
    # PyInstallerでパッケージ化した際、マルチプロセスの問題を回避するために必要
    multiprocessing.freeze_support()

    # アプリケーションを起動
    _launch_application()
