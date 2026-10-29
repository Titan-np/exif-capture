"""
Windows・シェルと連携する操作（ショートカット作成、アクセントカラー取得、ファイル・フォルダを開く）をまとめる

notifier / settings はこのモジュールを import しているため、循環importを避けて関数内で読み込む。
"""

import os
import sys

import lib.constants as constants
import lib.paths as paths
import lib.version as version


def get_app_launch_target_path() -> str:
    """
    アプリを起動するショートカットのリンク先（exe、開発時は Python 実行ファイル）の絶対パスを取得する

    Returns:
        str: リンク先の絶対パス
    """
    # 開発時は pythonw.exe が存在すれば優先して使用し、コンソールウィンドウの表示を防ぐ
    if not paths.is_executable():
        pythonw_candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(pythonw_candidate):
            return pythonw_candidate
    return sys.executable


def create_app_shortcut(shortcut_path: str, app_user_model_id: str | None = None):
    """
    アプリを起動するショートカット（.lnk）を作成・上書きする

    スタートメニュー・スタートアップの両方から使うため、失敗時の扱いは呼び出し元に任せ、例外はそのまま送出する。

    Args:
        shortcut_path (str): 作成するショートカットの絶対パス
        app_user_model_id (str, optional): ショートカットに設定する AUMID（System.AppUserModel.ID）。未指定時は設定しない
    """
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell, shellcon

    # 1. 起動対象（exeまたはpythonスクリプト）・引数・アイコンを決定
    # exe はアイコン未指定でも埋め込みアイコンが使われるため、開発時のみアイコンを指定する
    # （assets のアイコンは exe 終了時に削除される一時フォルダ(_MEIPASS)にあり、ショートカットからは参照できない）
    target_path = get_app_launch_target_path()
    arguments = ""
    icon_path = None
    if not paths.is_executable():
        main_script = paths.resolve_app_relative_path(os.path.join("src", "main.pyw"))
        arguments = f'"{main_script}"'
        icon_path = paths.get_icon_path(version.APP_VERSION, is_development=True)

    # 2. COMライブラリを初期化
    pythoncom.CoInitialize()
    try:
        # 3. ショートカット（IShellLink）を作成
        shell_link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        shell_link.SetPath(target_path)
        if arguments:
            shell_link.SetArguments(arguments)
        shell_link.SetWorkingDirectory(paths.resolve_app_relative_path())
        if icon_path:
            shell_link.SetIconLocation(icon_path, 0)
        shell_link.SetDescription(constants.APP_NAME)

        # 4. ファイルに保存
        persist_file = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
        persist_file.Save(shortcut_path, True)

        # 5. AUMIDが指定された場合、ショートカットのプロパティに System.AppUserModel.ID を設定する
        # Windows はこの ID をもとにトースト通知上部のヘッダーにアイコンを表示する
        if app_user_model_id:
            property_store = propsys.SHGetPropertyStoreFromParsingName(shortcut_path, None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
            property_key = pscon.PKEY_AppUserModel_ID
            property_value = propsys.PROPVARIANTType(app_user_model_id)
            property_store.SetValue(property_key, property_value)
            property_store.Commit()
    finally:
        pythoncom.CoUninitialize()


def get_shortcut_target_path(shortcut_path: str) -> str:
    """
    ショートカット（.lnk）のリンク先パスを取得する

    失敗時の扱いは呼び出し元に任せ、例外はそのまま送出する。

    Args:
        shortcut_path (str): 読み取るショートカットの絶対パス

    Returns:
        str: リンク先の絶対パス
    """
    import pythoncom
    from win32com.shell import shell

    # 1. COMライブラリを初期化
    pythoncom.CoInitialize()
    try:
        # 2. ショートカット（IShellLink）をファイルから読み込み、リンク先パスを取り出す
        shell_link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        persist_file = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
        persist_file.Load(shortcut_path)
        target_path, _ = shell_link.GetPath(0)
        return target_path
    finally:
        pythoncom.CoUninitialize()


def get_windows_accent_colors(fallback_color: str):
    """
    Windowsの個人用設定からアクセントカラーとホバー用のカラーコードを取得する

    Args:
        fallback_color (str): 取得できなかった場合に使うカラーコード (HEX。例: "#228B22")

    Returns:
        tuple[str, str]: (アクセントカラーのHEXコード, ホバー用カラーのHEXコード)
    """
    # ホバー時の明度を落とす倍率
    _HOVER_DIM_RATE = 0.8

    try:
        # 1. レジストリからWindowsのアクセントカラー(0xAABBGGRR)を取得（with で読み取り失敗時もキーを閉じる）
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as registry_key:
            accent_color_dword, _ = winreg.QueryValueEx(registry_key, "AccentColor")

        # 2. ABGR形式(0xAABBGGRR)の数値からR,G,Bの値を取得
        red = accent_color_dword & 0xFF
        green = (accent_color_dword >> 8) & 0xFF
        blue = (accent_color_dword >> 16) & 0xFF
    except Exception as exception:
        import lib.notifier as notifier

        notifier.log(f"Windowsのアクセントカラーの取得に失敗しました。デフォルトカラーを使用します。\n{exception}")
        # 取得失敗時は代替色のカラーコードからRGBを抽出
        red = int(fallback_color[1:3], 16)
        green = int(fallback_color[3:5], 16)
        blue = int(fallback_color[5:7], 16)

    # 3. HEX文字列に変換
    accent_color = f"#{red:02X}{green:02X}{blue:02X}"

    # 4. ホバー時のカラーを計算（明度を落とした色）
    hover_red = int(red * _HOVER_DIM_RATE)
    hover_green = int(green * _HOVER_DIM_RATE)
    hover_blue = int(blue * _HOVER_DIM_RATE)
    hover_color = f"#{hover_red:02X}{hover_green:02X}{hover_blue:02X}"

    return accent_color, hover_color


def safe_open_path(target_path: str, resource_name: str = "対象") -> bool:
    """
    指定されたファイルやフォルダを関連付けられた既定アプリで安全に開く
    対象が存在しない場合や関連付けアプリがない場合でも例外を外に逃がさず通知する

    Args:
        target_path (str): 開く対象のファイルまたはディレクトリのパス
        resource_name (str): 通知やログに表示する対象の名称（例: 'ログファイル', '保存先フォルダ'）

    Returns:
        bool: 正常に開けた場合はTrue、失敗した場合はFalse
    """
    import lib.notifier as notifier

    # 1. パスが空または存在しない場合はユーザーに通知して終了
    if not target_path or not os.path.exists(target_path):
        notifier.error(
            f"{resource_name}を開けませんでした。",
            f"対象のパスが存在しません。\n{target_path}",
        )
        return False

    try:
        # 2. OSの既定アプリケーションでファイルまたはディレクトリを起動（失敗時は原因に応じて通知）
        os.startfile(target_path)
        return True

    except OSError as error:
        # Windowsエラーコード 1155: ERROR_NO_ASSOCIATION（関連付けアプリ未設定）
        if getattr(error, "winerror", None) == 1155:
            detail_message = "ファイルを開くための既定のアプリケーションが設定されていません。"
        else:
            detail_message = str(error)

        # 起動失敗を通知
        notifier.error(f"{resource_name}を開けませんでした。", detail_message)
        return False

    except Exception as error:
        # 予期せぬ例外が発生してもアプリ全体が落ちないよう保護
        notifier.error(f"{resource_name}の起動中に予期しないエラーが発生しました。", str(error))
        return False


def open_log_file(icon=None, item=None) -> bool:
    """
    アプリケーションのログファイルを規定のテキストエディタで開く
    ファイルが存在しない場合は新規作成して開く

    Args:
        icon (pystray.Icon, optional): pystrayのメニューコールバック用引数（使用しない）
        item (pystray.MenuItem, optional): pystrayのメニューコールバック用引数（使用しない）

    Returns:
        bool: ファイルを開く処理に成功した場合はTrue、失敗した場合はFalse
    """
    import lib.notifier as notifier

    # 1. ログファイルの絶対パスを取得
    log_file_path = notifier.get_log_file_path()

    try:
        # 2. ログフォルダおよびログファイルが存在しない場合は自動作成
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

        if not os.path.exists(log_file_path):
            with open(log_file_path, "w", encoding="utf-8"):
                pass
    except OSError as exception:
        # フォルダ作成やファイル作成失敗時のエラーハンドリング
        notifier.error("ログファイルを作成できませんでした。", str(exception))
        return False

    # 3. 既定のエディタでログファイルを開く
    return safe_open_path(log_file_path, resource_name="ログファイル")


def ensure_save_directory() -> str | None:
    """
    設定から保存先フォルダのパスを取得・展開し、存在しない場合は作成する
    パスが未設定の場合やフォルダ作成に失敗した場合はログを出力し、Noneを返す

    Returns:
        str | None: 有効な保存先フォルダの絶対パス。失敗した場合はNone
    """
    import lib.notifier as notifier
    import lib.settings as settings

    # 1. 保存先フォルダを設定から取得し、チルダや環境変数を展開する
    configured_directory = settings.get("save.directory")
    target_directory = paths.expand_path(configured_directory) if configured_directory else ""

    # 2. パスが未設定または無効な場合はログに記録して終了
    if not target_directory:
        notifier.log("保存先フォルダのパスが指定されていません。")
        return None

    try:
        # 3. 保存先フォルダが存在しない場合は作成（exist_ok により既存の場合は何もしない）
        os.makedirs(target_directory, exist_ok=True)
    except OSError as exception:
        # フォルダ作成失敗時のエラーログ出力
        notifier.log(f"保存先フォルダを作成できませんでした。\n{exception}")
        return None

    return target_directory


def open_save_directory(icon=None, item=None) -> bool:
    """
    設定に登録された保存先フォルダをエクスプローラーで開く
    フォルダが存在しない場合は新規作成して開く

    Args:
        icon (pystray.Icon, optional): pystrayのメニューコールバック用引数（使用しない）
        item (pystray.MenuItem, optional): pystrayのメニューコールバック用引数（使用しない）

    Returns:
        bool: フォルダを開く処理に成功した場合はTrue、失敗した場合はFalse
    """
    # 1. 保存先フォルダの確認・作成（失敗時は設定やログの確認を促す通知を表示）
    target_directory = ensure_save_directory()
    if not target_directory:
        import lib.notifier as notifier

        notifier.notify(
            category=notifier.NotificationCategory.ERROR,
            title="保存先フォルダを開けませんでした。",
            message="保存先フォルダを準備できませんでした。詳細はログファイルを参照してください。",
            buttons=[notifier.NotificationButton.OPEN_LOG, notifier.NotificationButton.OPEN_SETTINGS],
        )
        return False

    # 2. エクスプローラーでフォルダを開く
    return safe_open_path(target_directory, resource_name="保存先フォルダ")
