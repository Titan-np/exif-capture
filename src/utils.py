import os
import sys
import datetime


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


def write_log(message: str, only_dev: bool = False):
    """
    コンソールおよびログファイルに日時付きでログを出力する

    Args:
        message (str): 出力するメッセージ
        only_dev (bool): 開発時のみログを出力するかどうか
    """
    # 開発時のみログを出力する場合、exe化後は出力しない
    if only_dev and getattr(sys, "frozen", False):
        return

    # タイムスタンプを取得 (秒まで)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_log = f"[{current_time}] {message}"

    # コンソール（標準出力）に出力
    print(formatted_log)

    try:
        # ログファイルの保存先フォルダを作成
        log_directory = get_app_path("logs")
        if not os.path.exists(log_directory):
            os.makedirs(log_directory, exist_ok=True)

        # 既存のログファイルがあれば追記する
        log_file_path = os.path.join(log_directory, "app.log")
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            log_file.write(formatted_log + "\n")
    except Exception as exception:
        print(f"[{current_time}] ログファイルへの書き込みに失敗しました。\n{exception}")


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
        write_log(f"Windowsのアクセントカラーの取得に失敗しました。デフォルトカラーを使用します。\n{exception}")
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
