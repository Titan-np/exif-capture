"""
Windows起動時の自動起動（スタートアップフォルダへのショートカット登録）を管理する

登録状態は settings.json に持たず、ショートカットの有無とWindows側の無効化状態をその都度読み取る。
タスクマネージャー等の外部操作で状態が変わっても、表示と実態が食い違わないようにするため。
"""

import os
import winreg
from enum import Enum

import lib.constants as constants
import lib.notifier as notifier
import lib.paths as paths
import lib.utils as utils

# スタートアップフォルダに作成するショートカットのファイル名
_SHORTCUT_FILE_NAME = f"{constants.APP_NAME}.lnk"

# タスクマネージャー等で無効化したスタートアップ項目を、Windowsが記録するレジストリキー（読み取りのみ行う）
_STARTUP_APPROVED_REGISTRY_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"


class StartupStatus(Enum):
    """スタートアップへの登録状態"""

    UNREGISTERED = "unregistered"  # ショートカットが無い
    ENABLED = "enabled"  # ショートカットがあり、Windows起動時に実行される
    DISABLED_BY_WINDOWS = "disabled_by_windows"  # ショートカットはあるが、タスクマネージャー等で無効化されている


def _get_shortcut_path():
    """
    スタートアップフォルダに置くショートカットの絶対パスを取得する

    Returns:
        str: ショートカットの絶対パス
    """
    from win32com.shell import shell, shellcon

    startup_directory = shell.SHGetFolderPath(0, shellcon.CSIDL_STARTUP, None, 0)
    return os.path.join(startup_directory, _SHORTCUT_FILE_NAME)


def _is_disabled_by_windows():
    """
    ショートカットがタスクマネージャー等でWindows側から無効化されているかを判定する

    Returns:
        bool: 無効化されている場合は True。記録が無い・読み取れない場合は False
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_APPROVED_REGISTRY_KEY_PATH) as registry_key:
            approved_value, _ = winreg.QueryValueEx(registry_key, _SHORTCUT_FILE_NAME)
    except OSError:
        # 一度も無効化されていない項目は記録自体が無いため、有効とみなす
        return False

    # 値の先頭バイトが奇数（0x03 等）なら無効、偶数（0x02 / 0x06 等）なら有効
    return bool(approved_value) and approved_value[0] % 2 == 1


def get_status():
    """
    スタートアップへの登録状態を取得する

    Returns:
        StartupStatus: 現在の登録状態
    """
    if not os.path.exists(_get_shortcut_path()):
        return StartupStatus.UNREGISTERED
    if _is_disabled_by_windows():
        return StartupStatus.DISABLED_BY_WINDOWS
    return StartupStatus.ENABLED


def register():
    """
    スタートアップフォルダにショートカットを作成し、Windows起動時に自動で起動するようにする
    開発時（Python実行）は、開発環境が登録されてしまうのを防ぐため何もしない

    Returns:
        bool: 登録に成功した場合は True
    """
    if not paths.is_executable():
        return False

    try:
        utils.create_app_shortcut(_get_shortcut_path())
        notifier.log("スタートアップに登録しました。")
        return True
    except Exception as exception:
        notifier.error("スタートアップへの登録に失敗しました。", f"スタートアップへの登録に失敗しました。\n{exception}")
        return False


def unregister():
    """
    スタートアップフォルダからショートカットを削除し、Windows起動時の自動起動を解除する
    開発時（Python実行）は、register() と揃えて何もしない

    Returns:
        bool: 解除に成功した場合（既に未登録の場合を含む）は True
    """
    if not paths.is_executable():
        return False

    try:
        os.remove(_get_shortcut_path())
        notifier.log("スタートアップの登録を解除しました。")
        return True
    except FileNotFoundError:
        # 既に削除されていれば、解除済みとして扱う
        return True
    except Exception as exception:
        notifier.error("スタートアップの登録解除に失敗しました。", f"スタートアップの登録解除に失敗しました。\n{exception}")
        return False


def refresh_shortcut():
    """
    登録済みの場合のみショートカットを作り直し、リンク先を現在のexeに合わせる
    exeを別フォルダへ移動・上書きした場合に、古いパスのまま起動に失敗するのを防ぐため、アプリ起動時に呼び出す
    """
    if not paths.is_executable():
        return

    try:
        shortcut_path = _get_shortcut_path()
        if os.path.exists(shortcut_path):
            utils.create_app_shortcut(shortcut_path)
    except Exception as exception:
        # 起動時の処理のため通知はせず、調査用にログのみ残す
        notifier.log(f"スタートアップのショートカットの更新に失敗しました。\n{exception}")
