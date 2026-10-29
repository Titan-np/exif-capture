import asyncio
import ctypes
import datetime
import os
import threading
import time
import webbrowser
from enum import StrEnum

from win11toast import toast_async

import lib.constants as constants
import lib.paths as paths
import lib.windows_shell as windows_shell


# 通知アクションボタンの種別
class NotificationButton(StrEnum):
    """通知に表示するアクションボタンの種別。StrEnum のため文字列としてそのまま使用可能。"""

    OPEN_IMAGE = "キャプチャした画像を開く"
    OPEN_FOLDER = "保存先フォルダを開く"
    OPEN_LOG = "ログファイルを開く"
    OPEN_SETTINGS = "設定画面を開く"
    OPEN_RELEASE_PAGE = "リリースページを開く"


# 通知の種別
class NotificationCategory(StrEnum):
    """通知の種別。値は表示可否を決める設定キーで、settings.get() にそのまま渡せる。"""

    CAPTURE = "notify.onCapture"
    APP_EVENT = "notify.onAppEvent"
    ERROR = "notify.onError"
    UPDATE = "update.checkMode"


# COM のマルチスレッド環境をアプリ終了まで維持するための識別子（_keep_winrt_environment で取得し、解放しない）
_apartment_usage_cookie = None


def _keep_winrt_environment():
    """
    通知機能が使う Windows の部品（DLL）群を、アプリ終了まで読み込んだまま維持する

    通知を出すと、Windows の部品が「共有の作業場所（COM のマルチスレッドアパートメント）」に読み込まれる。
    Windows 側の処理などがこの作業場所を一時的に使い終えると、作業場所ごと片付けられて部品も外されてしまう。
    通知ライブラリ（win11toast）は外されたことに気付かず次の通知で使おうとするため、アプリが強制終了してしまう。
    起動時に作業場所の利用を宣言しておき、アプリ終了まで片付けられないようにする。

    常駐プロセスだけでなく、エラー通知を出しうる設定画面のプロセスでも必要になる。
    また、ファイルや設定を変更しない処理のため、main.pyw から呼ぶ他の起動時処理と異なり、モジュール読み込み時に実行する。
    """
    global _apartment_usage_cookie

    # 1. マルチスレッドアパートメントの利用を宣言する
    cookie = ctypes.c_void_p()
    result = ctypes.windll.combase.CoIncrementMTAUsage(ctypes.byref(cookie))
    # 2. 宣言に失敗した場合はログに残して終了する
    if result < 0:
        # 維持できなかった環境では、以降で通知を出そうとした際に強制終了する可能性が残る
        # 撮影・保存には影響しないため、事象再現時の調査用にログ出力のみ行いアプリは続行させる
        log(f"通知用の実行環境の維持に失敗しました。(エラーコード: 0x{result & 0xFFFFFFFF:08X})")
        return

    # 3. アプリ終了まで解放しないよう、識別子をモジュール変数に保持する
    _apartment_usage_cookie = cookie


# ログファイルの保存先（アプリケーションフォルダからの相対パス）
LOG_DIRECTORY_NAME = "logs"
LOG_FILE_NAME = "app.log"


def get_log_file_path():
    """
    ログファイルの絶対パスを取得する

    Returns:
        str: ログファイルの絶対パス
    """
    return paths.resolve_app_relative_path(os.path.join(LOG_DIRECTORY_NAME, LOG_FILE_NAME))


# ログファイルの切り替え基準サイズ（超過時は起動時に旧世代へ退避し、最大でこの約2倍の容量に収める）
# テストで小さな値に差し替えるため、関数内ではなくモジュール直下に置く
LOG_FILE_MAX_BYTES = 1 * 1024 * 1024


def rotate_log_file():
    """
    ログファイルが基準サイズを超えている場合に旧世代ファイルへ切り替える
    書き込みごとの判定は別プロセスがファイルを開いている間にリネームが失敗しやすいため、アプリ起動時に1回だけ呼び出す
    """
    # 旧世代のログファイル名
    OLD_LOG_FILE_NAME = "app.log.old"

    log_file_path = get_log_file_path()
    old_log_file_path = os.path.join(os.path.dirname(log_file_path), OLD_LOG_FILE_NAME)

    # 1. ログファイルが存在しない、または基準サイズ以下なら切り替えない
    if not os.path.exists(log_file_path) or os.path.getsize(log_file_path) <= LOG_FILE_MAX_BYTES:
        return

    # 2. 旧世代ファイルへ置き換える（os.replace は既存の旧世代を上書きするため、2世代のみ保持される）
    try:
        os.replace(log_file_path, old_log_file_path)
    except OSError as exception:
        # 切り替えに失敗しても追記は継続できるため、起動処理は止めない
        log(f"ログファイルの切り替えに失敗しました。\n{exception}")
        return

    # 3. 新しいログファイルの先頭に切り替えた旨を記録
    log(f"ログファイルが {LOG_FILE_MAX_BYTES // 1024}KB を超えたため、旧ログを {os.path.basename(old_log_file_path)} に退避しました。")


def ensure_start_menu_shortcut():
    """
    トースト通知のヘッダー（app_idの左）にアプリアイコンを表示させるため、
    スタートメニューに AUMID (System.AppUserModel.ID) 付きのショートカットを作成・更新する
    設定画面のプロセスでは不要なため、モジュール読み込み時ではなく常駐プロセスの起動処理（main.pyw）から呼び出す

    ショートカットを上書きすると Windows がアイコンの紐づけを作り直し、PC起動直後は直後の起動通知に間に合わず白いアイコンになる。
    そのため、未作成またはリンク先が現在の起動対象と異なる場合のみ作成・更新する。
    """
    try:
        from win32com.shell import shell, shellcon

        # 1. 現在のプロセスに AUMID を明示的に設定する
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(constants.APP_NAME)
        except Exception:
            pass

        # 2. 既存のショートカットのリンク先が現在の起動対象と一致する場合は、上書きせずに終了する
        # （大文字・小文字やパス区切りの表記揺れで不一致と判定しないよう、正規化して比較する）
        programs_directory = shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, None, 0)
        shortcut_path = os.path.join(programs_directory, f"{constants.APP_NAME}.lnk")
        if os.path.exists(shortcut_path):
            current_target_path = os.path.normcase(os.path.normpath(windows_shell.get_shortcut_target_path(shortcut_path)))
            if current_target_path == os.path.normcase(os.path.normpath(windows_shell.get_app_launch_target_path())):
                return

        # 3. スタートメニューのプログラムフォルダに、AUMID付きのショートカットを作成・更新する
        windows_shell.create_app_shortcut(shortcut_path, app_user_model_id=constants.APP_NAME)

    except Exception as exception:
        log(f"スタートメニューショートカットの登録・更新に失敗しました。\n{exception}")


def log(message: str):
    """
    コンソールおよびログファイルに日時付きでログを出力する
    マルチプロセス等での競合によるファイルアクセスエラー時は短時間待機して再試行する

    Args:
        message (str): 出力するメッセージ
    """
    # ログファイル書き込み時のリトライ設定（マルチプロセス環境等でのファイル競合対策）
    LOG_WRITE_MAX_RETRY_COUNT = 3
    LOG_WRITE_RETRY_INTERVAL_SECONDS = 0.05

    def _format(text):
        """複数行テキストにタイムスタンプとインデントを付加する"""
        # プレフィックスを作成 （1行目はタイムスタンプ・2行目以降は同幅のインデント）
        timestamp = f"[{(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}] "
        indent = " " * len(timestamp)

        # プレフィックスを付加して出力メッセージを作成
        lines = text.split("\n")
        formatted_lines = [timestamp + lines[0]] + [indent + line for line in lines[1:]]
        return "\n".join(formatted_lines)

    # 1. コンソール（標準出力）に出力
    print(_format(message))

    try:
        # 2. ログファイルの保存先フォルダを作成
        log_file_path = get_log_file_path()
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

        # 3. 書き込みの競合を防ぐためリトライしつつ書き込む
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


# 通知処理専用のイベントループ（_send の初回呼び出し時に生成し、アプリ終了まで閉じない）
_toast_event_loop = None
_toast_event_loop_lock = threading.Lock()


def _send(title, body=None, image=None, buttons=None, on_click=None):
    """
    通知専用のイベントループ上でWindowsのトースト通知を送信・表示する内部関数

    Args:
        title (str): 通知のタイトル
        body (str, optional): 通知の本文
        image (str or dict, optional): 通知に表示する画像のパス
        buttons (list, optional): アクションボタンのリスト
        on_click (callable or str, optional): 通知本体やボタンクリック時に呼び出す関数、または開くURI
    """
    global _toast_event_loop

    # 1. 通知専用のイベントループを初回のみ生成し、バックグラウンドスレッドで動かし続ける
    # win11toast は通知の処理完了後も Windows 側から閉じた通知のイベント（dismissed 等）を遅れて受け取ることがあり、
    # 通知ごとにループを閉じると、遅れたイベントが閉じたループへ渡され RuntimeError になるため閉じずに使い回す
    with _toast_event_loop_lock:
        if _toast_event_loop is None:
            # 遅れたイベントは完了済みの処理へ結果を書き込もうとして InvalidStateError になる。
            # この無害なエラーだけを無視し、それ以外はデフォルト処理に委譲する例外ハンドラを設定する
            def _suppress_late_callback_error(event_loop, context):
                if isinstance(context.get("exception"), asyncio.InvalidStateError):
                    return
                event_loop.default_exception_handler(context)

            _toast_event_loop = asyncio.new_event_loop()
            _toast_event_loop.set_exception_handler(_suppress_late_callback_error)
            threading.Thread(target=_toast_event_loop.run_forever, daemon=True).start()

    # 2. トースト通知の引数を設定する
    # app_id を指定することで、スタートメニューのショートカットと紐づきヘッダー左にアプリアイコンが表示される
    # on_dismissed は未指定だと win11toast が閉じた理由をコンソールへ print するため、何もしない関数を渡す
    toast_kwargs = {
        "app_id": constants.APP_NAME,
        "on_dismissed": lambda *args: None,
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

    # 3. 呼び出し元をブロックしないよう、通知処理をイベントループへ登録し、失敗時はログに残す
    def _log_failure(future):
        if future.exception() is not None:
            log(f"通知の表示に失敗しました。\n{future.exception()}")

    future = asyncio.run_coroutine_threadsafe(toast_async(title, **toast_kwargs), _toast_event_loop)
    future.add_done_callback(_log_failure)


def notify(
    category: NotificationCategory,
    title: str,
    message: str = None,
    log_message: str = None,
    buttons: list = None,
    image_path: str = None,
    release_page_url: str = None,
):
    """
    Windowsトースト通知とログ出力を同時に行う
    通知の種別に対応する設定がオフの場合は、ログ出力のみ行いトースト通知は表示しない

    Args:
        category (NotificationCategory): 通知の種別。設定で制御できない通知を作らないよう、既定値を設けず必須とする
        title (str): 通知のタイトル
        message (str, optional): 通知本文（log_message未指定時はログ本文としても使用）
        log_message (str, optional): ログ専用のメッセージ。指定時はmessageの代わりにログファイルへ出力する
        buttons (list[NotificationButton], optional): 表示するボタンのリスト
        image_path (str, optional): キャプチャ画像などの絶対パス
        release_page_url (str, optional): 「リリースページを開く」ボタンで開くURL
    """
    # 1. ログを出力
    log_message = log_message if log_message is not None else message
    formatted_log_text = f"{title}\n{log_message}" if log_message is not None else title
    log(formatted_log_text)

    # 2. 通知の種別に対応する設定を確認し、オフであれば以降の処理を行わない
    # 循環参照防止のためメソッド内でインポート
    # 多重読み込みを防ぐため、ここではファイル再読み込み（settings.load()）を行わずメモリ上の設定を参照する
    import lib.settings as settings
    import lib.updater as updater

    # スイッチ項目は False、アップデート確認は「確認しない」をオフとみなす
    setting_value = settings.get(category)
    if setting_value is False or setting_value == updater.UpdateCheckMode.DISABLED:
        return

    # 3. ボタンとクリックイベントを設定
    # NotificationButton に定義されたボタンのみを抽出
    toast_buttons = [button for button in buttons or [] if button in NotificationButton]

    def _handle_click(click_event_arguments=None):
        # win11toastの仕様で、押したボタンは「http:ボタン文言」で引数に渡される（通知本体のクリックでは空文字）
        clicked_action = (click_event_arguments or {}).get("arguments", "").removeprefix("http:")

        try:
            # 「キャプチャした画像を開く」または通知本体クリック（画像パスがある場合）
            if clicked_action == NotificationButton.OPEN_IMAGE or (clicked_action == "" and image_path):
                if image_path and os.path.exists(image_path):
                    windows_shell.safe_open_path(image_path, resource_name="キャプチャした画像")
            # 「保存先フォルダを開く」
            elif clicked_action == NotificationButton.OPEN_FOLDER:
                windows_shell.open_save_directory()
            # 「ログファイルを開く」
            elif clicked_action == NotificationButton.OPEN_LOG:
                windows_shell.open_log_file()
            # 「設定画面を開く」
            elif clicked_action == NotificationButton.OPEN_SETTINGS:
                from settings_window import open_settings_window

                open_settings_window()
            # 「リリースページを開く」
            elif clicked_action == NotificationButton.OPEN_RELEASE_PAGE:
                webbrowser.open(release_page_url)
        except OSError as exception:
            log(f"通知のクリック時の処理に失敗しました。\n{exception}")

    # 4. Windows通知を送信（ボタンも画像も無い通知は、クリックしても何もしないためクリック処理を渡さない）
    _send(
        title=title,
        body=message,
        image=image_path,
        buttons=toast_buttons or None,
        on_click=_handle_click if toast_buttons or image_path else None,
    )


def error(title, log_message: str):
    """
    エラー通知を行う（notify()のラッパー）

    Args:
        title (str): 通知のタイトル
        log_message (str): エラーメッセージ（ログにのみ出力）
    """
    notify(
        category=NotificationCategory.ERROR,
        title=title,
        message="エラーが発生しました。詳細はログファイルを参照してください。",
        log_message=log_message,
        buttons=[NotificationButton.OPEN_LOG],
    )


# 最初の通知（起動通知）より前に、通知用の実行環境を維持しておく
_keep_winrt_environment()
