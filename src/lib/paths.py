"""
実行形態（exe / Python実行）の判定と、アプリケーション内のパス解決を行う

他モジュールから最も多く参照される土台のため、標準ライブラリ以外には依存しない。
関数名は、相対パスやファイル名を絶対パスにする関数を resolve_、条件から値を決める関数を get_ で始める。
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


def resolve_app_relative_path(relative_path: str = ""):
    """
    アプリケーションのフォルダを基準に、相対パスを絶対パスに変換する

    exe実行時はexeの配置フォルダ、開発時はリポジトリルートを基準とする。
    settings.json やログなど、アプリの終了後も残すファイルに使う。
    exe に同梱した assets はこのフォルダには無いため、resolve_asset_path() を使うこと。

    Args:
        relative_path (str): 基準フォルダからの相対パス（省略時は基準フォルダ自体を返す）

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


def resolve_asset_path(filename: str):
    """
    assets フォルダ内のファイル名を絶対パスに変換する

    exe実行時は、exe に同梱した assets が展開される一時フォルダ（_MEIPASS）を、開発時はリポジトリの assets フォルダを参照する。
    _MEIPASS は exe 終了時に削除されるため、実行中に読むファイル（音・アイコン）にのみ使い、
    アプリ終了後も参照されるパス（ショートカットのアイコン等）には使わないこと。

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
        return os.path.join(resolve_app_relative_path(), "assets", filename)


# アプリアイコンのファイル名（正式版・beta版・開発時）
_ICON_FILE_NAME = "icon.ico"
_BETA_ICON_FILE_NAME = "icon_beta.ico"
_DEV_ICON_FILE_NAME = "icon_dev.ico"


def get_icon_path(version_string: str, is_development: bool) -> str:
    """
    バージョンと実行形態に対応するアプリアイコンの絶対パスを取得する

    実行中のアプリと、ビルド対象のバージョンで判定する tools/build.py の双方から使うため、判定に使う値は引数で受け取る。

    Args:
        version_string (str): バージョン文字列（例: "v1.2.0"、"v1.2.0-beta.1"）
        is_development (bool): 開発時（Python実行）のアイコンを使う場合は True

    Returns:
        str: assetsフォルダ内のアイコンファイルの絶対パス
    """
    # 1. 開発時は、exe と見分けられるよう開発用アイコンを使う
    if is_development:
        return resolve_asset_path(_DEV_ICON_FILE_NAME)

    # 2. beta版は beta 版アイコンを使う（release.yml の Pre-release 判定と揃え、タグ名に 'beta' を含むかで判定する）
    if "beta" in version_string:
        return resolve_asset_path(_BETA_ICON_FILE_NAME)

    # 3. それ以外は正式版アイコンを使う
    return resolve_asset_path(_ICON_FILE_NAME)


# Windows の最大パス長（MAX_PATH 260 から終端文字分を引いた値）
# アプリ固有の値ではなく Windows のパスの制約のため、パスを扱う本モジュールに置く
WINDOWS_MAX_PATH_LENGTH = 259


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
