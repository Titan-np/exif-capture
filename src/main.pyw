import multiprocessing
import threading

import pystray
from PIL import Image

import capture
import lib.constants as constants
import lib.hotkey as hotkey
import lib.notifier as notifier
import lib.utils as utils
import lib.version as version
import settings_window

# ホットキー管理者インスタンス
_hotkey_manager = None

# 通知領域アイコンインスタンス
_tray_icon = None

# 初回起動フラグ（起動時通知と設定変更時通知の出し分けに使用）
_is_initial_launch = True


def _create_tray_icon_image():
    """
    通知領域に表示するためのアイコン画像を読み込む

    Returns:
        PIL.Image.Image: 生成されたアイコン画像
    """
    # アイコン保存先パスを取得
    icon_path = utils.get_asset_path("icon.ico", "icon_dev.ico")

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
        settings_window.settings_update_event.wait()
        settings_window.settings_update_event.clear()

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
    # settings.load() # 終了処理時は確実に終了させるため、設定ファイルの再読み込みは行わずメモリ上の設定を用いて通知する
    notifier.notify("終了します。")
    tray_icon_instance.stop()


def _launch_application():
    """
    通知領域への常駐とキーボード監視を開始する
    """
    global _hotkey_manager, _tray_icon

    # 通知領域に常駐させるアイコンと右クリックメニューを設定する
    tray_menu = pystray.Menu(
        pystray.MenuItem("設定を開く", settings_window.open_settings_window, default=True),
        pystray.MenuItem("保存先フォルダを開く", utils.open_save_directory),
        pystray.MenuItem("ログファイルを開く", utils.open_log_file),
        pystray.MenuItem("終了", _close_application),
    )
    _tray_icon = pystray.Icon(name=constants.APP_NAME, icon=_create_tray_icon_image(), title=constants.APP_NAME, menu=tray_menu)

    # ホットキー登録成功・失敗時に呼び出される関数を定義
    def _handle_hotkey_success(shortcut_key):
        """
        ホットキー登録成功時のコールバック処理
        初回起動時であれば起動完了通知を表示し、トレイアイコンのツールチップを通常状態に更新する

        Args:
            shortcut_key (str): 登録に成功したショートカットキー文字列
        """
        global _is_initial_launch, _tray_icon

        # 「起動しました」または「ショートカットキーを変更しました」の通知を表示
        title = None
        if _is_initial_launch:
            title = f"起動しました。({version.APP_VERSION})"
        else:
            title = f"ショートカットキーを変更しました。"
        notifier.notify(
            title,
            f"ショートカットキー ({shortcut_key}) を押すとスクリーンショットを撮影します。",
        )

        # ホットキー登録が完了した段階で、初回起動フラグを解除
        _is_initial_launch = False

        # トレイアイコンのツールチップを通常表示に復帰
        if _tray_icon is not None:
            _tray_icon.title = constants.APP_NAME

    def _handle_hotkey_failure(shortcut_key, error_code):
        """
        ホットキー登録失敗時のコールバック処理
        起動完了通知の代わりに設定画面への誘導通知を表示し、トレイアイコンのツールチップを警告表示に更新する

        Args:
            shortcut_key (str): 登録に失敗したショートカットキー文字列
            error_code (int): Windows APIのエラーコード
        """
        global _is_initial_launch, _tray_icon

        # 他アプリとの競合等でホットキーが使えない旨を通知し、設定変更を案内する
        notifier.notify(
            title="ショートカットキーの登録に失敗しました",
            message=f"'{shortcut_key}' は他のアプリと競合している可能性があります。設定画面から別のキーに変更してください。",
            log_message=f"ショートカットキーの登録に失敗しました: {shortcut_key} (エラーコード: {error_code})",
            buttons=[notifier.NotificationButton.OPEN_SETTINGS, notifier.NotificationButton.OPEN_LOG],
        )

        # ホットキー登録が完了した段階で、初回起動フラグを解除
        _is_initial_launch = False

        # トレイアイコンのツールチップに未登録状態を表示し、視覚的に警告する
        if _tray_icon is not None:
            _tray_icon.title = f"{constants.APP_NAME} (ホットキー未登録)"

    # ホットキー管理クラスをインスタンス化して監視を開始
    # 登録成否コールバックを渡し、状態に応じた通知とトレイアイコン更新を行う
    _hotkey_manager = hotkey.Manager(
        callback_function=capture.capture_screenshot,
        on_registration_failure=_handle_hotkey_failure,
        on_registration_success=_handle_hotkey_success,
    )
    _hotkey_manager.start()

    # 設定変更通知を監視するスレッドを起動
    update_watcher_thread = threading.Thread(target=_watch_update_event, daemon=True)
    update_watcher_thread.start()

    # 通知領域での常駐を開始してメインループを起動する（起動通知は登録成否コールバック内で行う）
    _tray_icon.run()


# ここから実行
if __name__ == "__main__":
    # PyInstallerでパッケージ化した際、マルチプロセスの問題を回避するために必要
    multiprocessing.freeze_support()

    # アプリケーションを起動
    _launch_application()
