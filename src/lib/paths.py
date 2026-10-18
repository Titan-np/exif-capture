"""
実行形態（exe / Python実行）の判定と、アプリケーション内のパス解決を行う

他モジュールから最も多く参照される土台のため、標準ライブラリ以外には依存しない。
"""

import os
import sys


def is_executable() -> bool:
    """
    exe（PyInstallerでビルドした実行ファイル）として起動しているかを判定する

    exe実行か開発時（Python実行）かの判定は、すべてこの関数で行う。

    Returns:
        bool: exe実行時はTrue、Python実行（開発時）はFalse
    """
    # PyInstaller は exe 実行時に sys.frozen を設定する
    return getattr(sys, "frozen", False)


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
    if is_executable():
        # PyInstaller実行時は、exe本体と同じ階層のフォルダを基準にする
        base_directory = os.path.dirname(sys.executable)
    else:
        # 通常のPython実行時は、スクリプトがある場所(src/lib)の親の親(リポジトリルート)を基準にする
        script_directory = os.path.dirname(os.path.abspath(__file__))
        base_directory = os.path.dirname(os.path.dirname(script_directory))

    return os.path.join(base_directory, relative_path) if relative_path else base_directory


def get_asset_path(filename: str):
    """
    assets内のファイルパスを取得する

    PyInstaller実行時はバンドルされた一時フォルダ(_MEIPASS)を参照するため、
    get_app_path() とは異なるベースパスを使用する。
    _MEIPASS は exe 終了時に削除されるため、アプリ終了後も参照されるパス（ショートカット等）には使わないこと。

    Args:
        filename (str): assetsフォルダ内のファイル名

    Returns:
        str: assetsフォルダ内のファイルの絶対パス
    """
    if is_executable():
        # PyInstaller実行時は一時フォルダ(_MEIPASS)に展開されたassetsを参照する
        return os.path.join(sys._MEIPASS, "assets", filename)
    else:
        # 開発時はリポジトリルート直下のassetsを参照する
        return os.path.join(get_app_path(), "assets", filename)


def get_icon_filename(version_string: str) -> str:
    """
    バージョン文字列に対応するアプリアイコンのファイル名を取得する

    ビルド時（tools/build.py）にもビルド対象のバージョンで判定できるよう、バージョン文字列を引数で受け取る。

    Args:
        version_string (str): バージョン文字列（例: "v1.2.0"、"v1.2.0-beta.1"）

    Returns:
        str: beta版は "icon_beta.ico"、それ以外は "icon.ico"
    """
    # release.yml の Pre-release 判定と揃え、タグ名に 'beta' を含むかで判定する
    if "beta" in version_string:
        return "icon_beta.ico"
    return "icon.ico"


def get_app_icon_path() -> str:
    """
    実行形態とバージョンに対応するアプリアイコンの絶対パスを取得する

    開発時（Python実行）は icon_dev.ico、exe実行時はバージョンに応じて icon_beta.ico / icon.ico を返す。

    Returns:
        str: assetsフォルダ内のアイコンファイルの絶対パス
    """
    # 開発時は、exe と見分けられるよう開発用アイコンを使う
    if not is_executable():
        return get_asset_path("icon_dev.ico")

    # exe実行時は、埋め込まれたバージョンに応じて正式版 / beta版のアイコンを使う
    # version は paths を import しているため、循環importを避けて関数内で読み込む
    import lib.version as version

    return get_asset_path(get_icon_filename(version.APP_VERSION))


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
