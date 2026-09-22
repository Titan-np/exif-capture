import os
import sys
import time
import asyncio
import datetime
import threading
from enum import StrEnum
from win11toast import toast_async

from constants import *
from utils import *

# ログファイル書き込み時のリトライ設定（マルチプロセス環境等でのファイル競合対策）
LOG_WRITE_MAX_RETRY_COUNT = 3
LOG_WRITE_RETRY_INTERVAL_SECONDS = 0.05


# 通知アクションボタンの種別
class NotificationButton(StrEnum):
    """通知に表示するアクションボタンの種別。StrEnum のため文字列としてそのまま使用可能。"""

    OPEN_IMAGE = "キャプチャした画像を開く"
    OPEN_FOLDER = "保存先フォルダを開く"
    OPEN_LOG = "ログファイルを開く"
    OPEN_SETTINGS = "設定画面を開く"


class Notifier:
    """
    Windowsのトースト通知の送信およびログ出力を管理するクラス
    """

    def __init__(self):
        """
        コンストラクタ
        """
        # アプリアイコン付きで通知表示させるため、スタートメニューショートカットを登録・更新
        self._ensure_start_menu_shortcut()

    def _ensure_start_menu_shortcut(self):
        """
        トースト通知のヘッダー（app_idの左）にアプリアイコンを表示させるため、
        スタートメニューに AUMID (System.AppUserModel.ID) 付きのショートカットを作成・更新する
        """
        try:
            import ctypes
            import pythoncom
            from win32com.shell import shell, shellcon
            from win32com.propsys import propsys, pscon

            # 現在のプロセスに AUMID を明示的に設定する
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
            except Exception:
                pass

            # スタートメニューのプログラムフォルダのパスを取得
            programs_directory = shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, None, 0)
            shortcut_path = os.path.join(programs_directory, f"{APP_NAME}.lnk")

            # 起動対象（exeまたはpythonスクリプト）と引数を設定
            if getattr(sys, "frozen", False):
                target_path = sys.executable
                arguments = ""
            else:
                # 開発時は pythonw.exe が存在すれば優先して使用し、コンソールウィンドウの表示を防ぐ
                target_path = sys.executable
                pythonw_candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if os.path.exists(pythonw_candidate):
                    target_path = pythonw_candidate
                main_script = get_app_path(os.path.join("src", "main.pyw"))
                arguments = f'"{main_script}"'

            icon_path = get_asset_path("icon.ico", "icon_dev.ico")

            # COMライブラリを初期化
            pythoncom.CoInitialize()
            try:
                # ショートカット（IShellLink）を作成
                shell_link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
                shell_link.SetPath(target_path)
                if arguments:
                    shell_link.SetArguments(arguments)
                shell_link.SetWorkingDirectory(get_app_path())
                shell_link.SetIconLocation(icon_path, 0)
                shell_link.SetDescription(APP_NAME)

                # ファイルに保存
                persist_file = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
                persist_file.Save(shortcut_path, True)

                # ショートカットのプロパティに System.AppUserModel.ID を設定する
                # Windows はこの ID をもとにトースト通知上部のヘッダーにアイコンを表示する
                property_store = propsys.SHGetPropertyStoreFromParsingName(shortcut_path, None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
                property_key = pscon.PKEY_AppUserModel_ID
                property_value = propsys.PROPVARIANTType(APP_NAME)
                property_store.SetValue(property_key, property_value)
                property_store.Commit()
            finally:
                pythoncom.CoUninitialize()

        except Exception as exception:
            self.log(f"スタートメニューショートカットの登録・更新に失敗しました。\n{exception}")

    def _send(self, title, body=None, image=None, buttons=None, on_click=None):
        """
        バックグラウンドスレッドでWindowsのトースト通知を送信・表示する内部関数

        Args:
            title (str): 通知のタイトル
            body (str, optional): 通知の本文
            image (str or dict, optional): 通知に表示する画像のパス
            buttons (list, optional): アクションボタンのリスト
            on_click (callable or str, optional): 通知本体やボタンクリック時に呼び出す関数、または開くURI
        """

        def _worker():
            try:
                # トースト通知の引数を設定する
                # app_id を指定することで、スタートメニューのショートカットと紐づきヘッダー左にアプリアイコンが表示される
                toast_kwargs = {
                    "app_id": APP_NAME,
                }

                # 通知本文・画像パス・ボタン・クリックイベントが指定された場合、引数に追加する
                if body:
                    toast_kwargs["body"] = body
                if image:
                    toast_kwargs["image"] = {"src": image}
                if buttons:
                    toast_kwargs["buttons"] = buttons
                if on_click:
                    toast_kwargs["on_click"] = on_click

                # win11toast は通知が消えた後も Windows 側からコールバックが届くことがあり、
                # 既に完了した処理に対して結果を書き込もうとしてエラーになる。
                # この無害なエラーだけを無視し、それ以外はデフォルト処理に委譲する例外ハンドラを設定する
                def _suppress_late_callback_error(event_loop, context):
                    if isinstance(context.get("exception"), asyncio.InvalidStateError):
                        return
                    event_loop.default_exception_handler(context)

                loop = asyncio.new_event_loop()
                loop.set_exception_handler(_suppress_late_callback_error)
                try:
                    loop.run_until_complete(toast_async(title, **toast_kwargs))
                finally:
                    loop.close()

            except Exception as exception:
                self.log(f"通知の表示に失敗しました。\n{exception}")

        # 呼び出し元をブロックしないよう別スレッドで通知処理を実行する
        threading.Thread(target=_worker, daemon=True).start()

    def log(self, message: str):
        """
        コンソールおよびログファイルに日時付きでログを出力する
        マルチプロセス等での競合によるファイルアクセスエラー時は短時間待機して再試行する

        Args:
            message (str): 出力するメッセージ
        """

        def _format(text):
            """複数行テキストにタイムスタンプとインデントを付加する"""
            # プレフィックスを作成 （1行目はタイムスタンプ・2行目以降は同幅のインデント）
            timestamp = f"[{(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}] "
            indent = " " * len(timestamp)

            # プレフィックスを付加して出力メッセージを作成
            lines = text.split("\n")
            formatted_lines = [timestamp + lines[0]] + [indent + line for line in lines[1:]]
            return "\n".join(formatted_lines)

        # コンソール（標準出力）に出力
        print(_format(message))

        try:
            # ログファイルの保存先フォルダを作成
            log_directory = get_app_path("logs")
            if not os.path.exists(log_directory):
                os.makedirs(log_directory, exist_ok=True)

            log_file_path = os.path.join(log_directory, "app.log")

            # 書き込みの競合を防ぐためリトライしつつ書き込む
            for attempt_count in range(1, LOG_WRITE_MAX_RETRY_COUNT + 1):
                try:
                    # 既存のログファイルがあれば追記する
                    with open(log_file_path, "a", encoding="utf-8") as log_file:
                        log_file.write(_format(message) + "\n")
                    # 正常に書き込めたらループを終了
                    break
                except (PermissionError, OSError) as exception:
                    # 最終試行でも失敗した場合はエラーを出力
                    if attempt_count == LOG_WRITE_MAX_RETRY_COUNT:
                        print(_format(f"ログファイルへの書き込みに失敗しました。\n{exception}"))
                        break
                    # 他プロセスのファイル解放を待つため待機
                    time.sleep(LOG_WRITE_RETRY_INTERVAL_SECONDS)

        except Exception as exception:
            print(_format(f"ログファイルへの書き込み処理で予期せぬエラーが発生しました。\n{exception}"))

    def notify(
        self,
        title: str,
        message: str = None,
        log_message: str = None,
        buttons: list = None,
        image_path: str = None,
    ):
        """
        Windowsトースト通知とログ出力を同時に行う

        Args:
            title (str): 通知のタイトル
            message (str, optional): 通知本文（log_message未指定時はログ本文としても使用）
            log_message (str, optional): ログ専用のメッセージ。指定時はmessageの代わりにログファイルへ出力する
            buttons (list[NotificationButton], optional): 表示するボタンのリスト
            image_path (str, optional): キャプチャ画像などの絶対パス
        """
        # 1. ログを出力
        log_message = log_message if log_message is not None else message
        formatted_log_text = f"{title}\n{log_message}" if log_message is not None else title
        self.log(formatted_log_text)

        # 2. 設定を確認し、Windows通知がオフであれば以降の処理を行わない
        # 循環参照防止のためメソッド内でインポート
        # 多重読み込みを防ぐため、ここではファイル再読み込み（settings.load()）を行わずメモリ上の設定を参照する
        from settings_manager import settings

        if not settings.get("capture.enableSystemNotification"):
            return

        # 3. ボタンとクリックイベントを設定
        toast_buttons = []
        on_click = None

        if buttons:
            # NotificationButton に定義されたボタンのみを抽出
            toast_buttons = [button for button in buttons if button in NotificationButton]

            def _handle_click(click_event_arguments=None):
                # win11toastの仕様で、押したボタンは「http:ボタン文言」で引数に渡される
                clicked_action = click_event_arguments.get("arguments", "").removeprefix("http:")

                try:
                    # 「キャプチャした画像を開く」または通知本体クリック（画像パスがある場合）
                    if clicked_action == NotificationButton.OPEN_IMAGE or (clicked_action == "" and image_path):
                        if image_path and os.path.exists(image_path):
                            safe_open_path(image_path, resource_name="キャプチャした画像")
                    # 「保存先フォルダを開く」
                    elif clicked_action == NotificationButton.OPEN_FOLDER:
                        open_save_directory()
                    # 「ログファイルを開く」
                    elif clicked_action == NotificationButton.OPEN_LOG:
                        open_log_file()
                    # 「設定画面を開く」
                    elif clicked_action == NotificationButton.OPEN_SETTINGS:
                        from settings_ui import open_settings_window

                        open_settings_window()
                except OSError as exception:
                    self.log(f"通知ボタンのアクション実行に失敗しました。\n{exception}")

            on_click = _handle_click

        elif image_path:
            # ボタン指定がない場合でも、画像があれば通知クリックで画像を開く
            def _handle_click(click_event_arguments=None):
                try:
                    if os.path.exists(image_path):
                        safe_open_path(image_path, resource_name="キャプチャした画像")
                except OSError as exception:
                    self.log(f"画像を開けませんでした。\n{exception}")

            on_click = _handle_click

        # 4. Windows通知を送信
        self._send(
            title=title,
            body=message,
            image=image_path,
            buttons=toast_buttons if toast_buttons else None,
            on_click=on_click,
        )

    def error(self, title, log_message: str):
        """
        エラー通知を行う（notify()のラッパー）

        Args:
            title (str): 通知のタイトル
            log_message (str): エラーメッセージ（ログにのみ出力）
        """
        self.notify(
            title=title,
            message="エラーが発生しました。詳細はログファイルを参照してください。",
            log_message=log_message,
            buttons=[NotificationButton.OPEN_LOG],
        )


# 初呼び出し時、あるいはインポート時にインスタンスを作成する
notifier = Notifier()
