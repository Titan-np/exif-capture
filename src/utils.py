import os
import sys


def get_app_path(relative_path: str = ""):
    """
    アプリケーションのルートフォルダを基準に、相対パスを絶対パスに変換する

    exe実行時はexeの配置フォルダ、開発時はリポジトリルートを基準とする。
    PyInstallerのバンドルリソース（_MEIPASS）には対応しないため、
    assetsの取得には get_asset_path() を使用すること。

    Args:
        relative_path (str): ルートからの相対パス（省略時はルートフォルダ自体を返す）

    Returns:
        str: 絶対パス
    """
    if getattr(sys, "frozen", False):
        # PyInstaller実行時は、exe本体と同じ階層のフォルダを基準にする
        base_directory = os.path.dirname(sys.executable)
    else:
        # 通常のPython実行時は、スクリプトがある場所(src)の親(リポジトリルート)を基準にする
        script_directory = os.path.dirname(os.path.abspath(__file__))
        base_directory = os.path.dirname(script_directory)

    return os.path.join(base_directory, relative_path) if relative_path else base_directory


def get_asset_path(filename: str, dev_filename: str = None):
    """
    assets内のファイルパスを取得する

    PyInstaller実行時はバンドルされた一時フォルダ(_MEIPASS)を参照するため、
    get_app_path() とは異なるベースパスを使用する。

    Args:
        filename (str): 実行時（exe化後）のファイル名
        dev_filename (str): 開発時（py実行）のファイル名（省略時はfilenameと同じ）

    Returns:
        str: assetsフォルダ内のファイルの絶対パス
    """
    if getattr(sys, "frozen", False):
        # PyInstaller実行時は一時フォルダ(_MEIPASS)に展開されたassetsを参照する
        return os.path.join(sys._MEIPASS, "assets", filename)
    else:
        # 開発時用のファイル名が指定されていれば、そちらを参照する
        target_filename = dev_filename if dev_filename is not None else filename
        # 開発時はリポジトリルート直下のassetsを参照する
        return os.path.join(get_app_path(), "assets", target_filename)


def expand_path(path: str) -> str:
    """
    チルダ（~）や環境変数を含むパス文字列を展開し、絶対パス相当の正規化されたパス文字列に変換する

    Args:
        path (str): 展開対象のパス文字列

    Returns:
        str: 展開・正規化後のパス文字列（空文字列の場合は空文字列）
    """
    if not path:
        return ""
    # チルダ（ユーザーホーム）と環境変数（%VAR%）を順次展開してパスを正規化
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))


def get_windows_accent_colors(fallback_color: str = "#228B22"):
    """
    Windowsの個人用設定からアクセントカラーとホバー用のカラーコードを取得する

    Args:
        fallback_color (str): 取得できなかった場合のフォールバックカラーコード (HEX)

    Returns:
        tuple[str, str]: (アクセントカラーのHEXコード, ホバー用カラーのHEXコード)
    """
    # ホバー時の明度を落とす倍率
    _HOVER_DIM_RATE = 0.8

    try:
        # レジストリからWindowsのアクセントカラー(0xAABBGGRR)を取得
        import winreg

        registry_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM")
        accent_color_dword, _ = winreg.QueryValueEx(registry_key, "AccentColor")
        winreg.CloseKey(registry_key)

        # ABGR形式(0xAABBGGRR)の数値からR,G,Bの値を取得
        red = accent_color_dword & 0xFF
        green = (accent_color_dword >> 8) & 0xFF
        blue = (accent_color_dword >> 16) & 0xFF
    except Exception as exception:
        from notifier import notifier

        notifier.log(f"Windowsのアクセントカラーの取得に失敗しました。デフォルトカラーを使用します。\n{exception}")
        # 取得失敗時はフォールバック文字列からRGBを抽出
        red = int(fallback_color[1:3], 16)
        green = int(fallback_color[3:5], 16)
        blue = int(fallback_color[5:7], 16)

    # HEX文字列に変換
    accent_color = f"#{red:02X}{green:02X}{blue:02X}"

    # ホバー時のカラーを計算（明度を落とした色）
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
    # 循環インポートを回避するため関数内でインポート
    from notifier import notifier

    # パスが空または存在しない場合はユーザーに通知して終了
    if not target_path or not os.path.exists(target_path):
        notifier.error(
            f"{resource_name}を開けませんでした。",
            f"対象のパスが存在しません。\n{target_path}",
        )
        return False

    try:
        # OSの既定アプリケーションでファイルまたはディレクトリを起動
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
    # ログファイルの絶対パスを取得
    log_file_path = get_app_path(os.path.join("logs", "app.log"))

    try:
        # ログフォルダおよびログファイルが存在しない場合は自動作成
        log_directory = os.path.dirname(log_file_path)
        if not os.path.exists(log_directory):
            os.makedirs(log_directory, exist_ok=True)

        if not os.path.exists(log_file_path):
            with open(log_file_path, "w", encoding="utf-8"):
                pass
    except OSError as exception:
        # フォルダ作成やファイル作成失敗時のエラーハンドリング
        from notifier import notifier

        notifier.error("ログファイルを作成できませんでした。", str(exception))
        return False

    # 規定のエディタでログファイルを開く
    return safe_open_path(log_file_path, resource_name="ログファイル")


def ensure_save_directory() -> str | None:
    """
    設定から保存先フォルダのパスを取得・展開し、存在しない場合は作成する
    パスが未設定の場合やフォルダ作成に失敗した場合はログを出力し、Noneを返す

    Returns:
        str | None: 有効な保存先フォルダの絶対パス。失敗した場合はNone
    """
    # 保存先フォルダを設定から取得
    from settings_manager import settings

    configured_directory = settings.get("save.directory")
    target_directory = expand_path(configured_directory) if configured_directory else ""

    if not target_directory:
        # パスが未設定または無効な場合はログに記録
        from notifier import notifier

        notifier.log("保存先フォルダのパスが指定されていません。")
        return None

    try:
        # 保存先フォルダが存在しない場合は作成
        if not os.path.exists(target_directory):
            os.makedirs(target_directory, exist_ok=True)
    except OSError as exception:
        # フォルダ作成失敗時のエラーログ出力
        from notifier import notifier

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
    # 保存先フォルダの確認・作成
    target_directory = ensure_save_directory()
    if not target_directory:
        # フォルダ準備失敗時は設定やログ確認を促す通知を表示
        from notifier import notifier, NotificationButton

        notifier.notify(
            title="保存先フォルダを開けませんでした。",
            message="保存先フォルダを準備できませんでした。詳細はログファイルを参照してください。",
            buttons=[NotificationButton.OPEN_LOG, NotificationButton.OPEN_SETTINGS],
        )
        return False

    # エクスプローラーでフォルダを開く
    return safe_open_path(target_directory, resource_name="保存先フォルダ")
