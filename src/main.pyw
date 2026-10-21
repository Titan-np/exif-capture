import multiprocessing
import threading

import pystray
from PIL import Image

import capture
import lib.constants as constants
import lib.hotkey as hotkey
import lib.notifier as notifier
import lib.paths as paths
import lib.startup as startup
import lib.updater as updater
import lib.version as version
import lib.windows_shell as windows_shell
import settings_window

# 起動後、アップデートチェックを行うまでの待機秒数（起動通知との重なりや、PC起動直後のネットワーク未接続を避けるため）
STARTUP_CHECK_DELAY_SECONDS = 15


def _launch_application():
    """
    通知領域への常駐とキーボード監視を開始する
    """
    # 初回起動フラグ（起動時通知と設定変更時通知の出し分けに使用）
    is_initial_launch = True

    def _create_tray_icon_image():
        """
        通知領域に表示するためのアイコン画像を読み込む

        Returns:
            PIL.Image.Image: 生成されたアイコン画像
        """
        try:
            # 実行形態とバージョンに対応するアイコン画像を読み込む
            return Image.open(paths.get_icon_path(version.APP_VERSION, is_development=not paths.is_executable()))
        except Exception as exception:
            # 読み込みに失敗した場合はダミー画像として水色の四角を返す
            notifier.log(f"アイコン画像の読み込みに失敗しました。\n{exception}")
            return Image.new("RGB", (64, 64), color=(0, 128, 255))

    def _close_application(tray_icon_instance, menu_item_instance):
        """
        通知領域への常駐とキーボード監視を終了する（トレイメニュー「終了」のコールバック）

        Args:
            tray_icon_instance (pystray.Icon): 制御対象のトレイアイコンオブジェクト
            menu_item_instance (pystray.MenuItem): クリックされたメニュー項目オブジェクト
        """
        # 1. ホットキー監視を停止
        hotkey_manager.stop()

        # 2. 通知領域からアイコンを削除し、アプリケーションの実行を終了する
        # 終了処理時は確実に終了させるため、設定ファイルの再読み込みは行わずメモリ上の設定を用いて通知する
        notifier.notify(category=notifier.NotificationCategory.APP_EVENT, title="終了します。")
        tray_icon_instance.stop()

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
            hotkey_manager.reload()

    def _handle_hotkey_success(shortcut_key):
        """
        ホットキー登録成功時のコールバック処理
        初回起動時であれば起動完了通知を表示し、トレイアイコンのツールチップを通常状態に更新する

        Args:
            shortcut_key (str): 登録に成功したショートカットキー文字列
        """
        nonlocal is_initial_launch

        # 1. 「起動しました」または「ショートカットキーを変更しました」の通知を表示
        if is_initial_launch:
            title = f"起動しました。({version.APP_VERSION})"
        else:
            title = "ショートカットキーを変更しました。"
        notifier.notify(
            category=notifier.NotificationCategory.APP_EVENT,
            title=title,
            message=f"ショートカットキー ({shortcut_key}) を押すとスクリーンショットを撮影します。",
        )

        # 2. ホットキー登録が完了した段階で、初回起動フラグを解除
        is_initial_launch = False

        # 3. トレイアイコンのツールチップを通常表示に復帰
        tray_icon.title = constants.APP_NAME

    def _handle_hotkey_failure(shortcut_key, error_code):
        """
        ホットキー登録失敗時のコールバック処理
        起動完了通知の代わりに設定画面への誘導通知を表示し、トレイアイコンのツールチップを警告表示に更新する

        Args:
            shortcut_key (str): 登録に失敗したショートカットキー文字列
            error_code (int): Windows APIのエラーコード
        """
        nonlocal is_initial_launch

        # 1. 他アプリとの競合等でホットキーが使えない旨を通知し、設定変更を案内する
        notifier.notify(
            category=notifier.NotificationCategory.ERROR,
            title="ショートカットキーの登録に失敗しました",
            message=f"'{shortcut_key}' は他のアプリと競合している可能性があります。設定画面から別のキーに変更してください。",
            log_message=f"ショートカットキーの登録に失敗しました: {shortcut_key} (エラーコード: {error_code})",
            buttons=[notifier.NotificationButton.OPEN_SETTINGS, notifier.NotificationButton.OPEN_LOG],
        )

        # 2. ホットキー登録が完了した段階で、初回起動フラグを解除
        is_initial_launch = False

        # 3. トレイアイコンのツールチップに未登録状態を表示し、視覚的に警告する
        tray_icon.title = f"{constants.APP_NAME} (ホットキー未登録)"

    # 1. 起動時の最初のログ出力より前に、肥大化したログファイルを旧世代へ切り替える
    notifier.rotate_log_file()

    # 2. 最初の通知（起動通知）より前に、通知にアプリアイコンを表示するためのスタートメニューのショートカットを作成・更新する
    notifier.ensure_start_menu_shortcut()

    # 3. 通知領域に常駐させるアイコンと右クリックメニューを設定する
    # ホットキー登録の成否コールバックでツールチップを更新するため、ホットキー監視の開始より前に作成する
    tray_menu = pystray.Menu(
        pystray.MenuItem("設定を開く", settings_window.open_settings_window, default=True),
        pystray.MenuItem("保存先フォルダを開く", windows_shell.open_save_directory),
        pystray.MenuItem("ログファイルを開く", windows_shell.open_log_file),
        pystray.MenuItem("終了", _close_application),
    )
    tray_icon = pystray.Icon(name=constants.APP_NAME, icon=_create_tray_icon_image(), title=constants.APP_NAME, menu=tray_menu)

    # 4. ホットキー管理クラスをインスタンス化して監視を開始
    # 登録成否コールバックを渡し、状態に応じた通知とトレイアイコン更新を行う
    hotkey_manager = hotkey.Manager(
        callback_function=capture.capture_screenshot,
        on_registration_failure=_handle_hotkey_failure,
        on_registration_success=_handle_hotkey_success,
    )
    hotkey_manager.start()

    # 5. 設定変更通知を監視するスレッドを起動
    threading.Thread(target=_watch_update_event, daemon=True).start()

    # 6. 新しいバージョンが公開されていないかを、起動から一定時間後に確認して通知する
    # 起動通知との重なりや、PC起動直後のネットワーク未接続を避けるため、すぐには確認しない
    updater.notify_update(delay_seconds=STARTUP_CHECK_DELAY_SECONDS)

    # 7. スタートアップに登録済みの場合、exeの移動に追従するようショートカットのリンク先を現在のexeに更新する
    startup.refresh_shortcut()

    # 8. 通知領域での常駐を開始してメインループを起動する（起動通知は登録成否コールバック内で行う）
    tray_icon.run()


# ここから実行
if __name__ == "__main__":
    # PyInstallerでパッケージ化した際、マルチプロセスの問題を回避するために必要
    multiprocessing.freeze_support()

    # アプリケーションを起動
    _launch_application()
