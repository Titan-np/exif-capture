import os
import sys
import ctypes
import ctypes.wintypes
import threading

from settings_manager import settings
from notifier import notifier


class HotkeyManager:
    """
    WindowsのRegisterHotKey APIを使用して、
    グローバルホットキーの登録・監視・再設定を一元管理するクラス
    """

    # Windows API 定数
    _MOD_ALT = 0x0001
    _MOD_CONTROL = 0x0002
    _MOD_SHIFT = 0x0004
    _MOD_WIN = 0x0008
    _MOD_NOREPEAT = 0x4000  # キーリピートによる連続発火を防止するフラグ

    _WM_HOTKEY = 0x0312
    _WM_QUIT = 0x0012
    _WM_USER_RELOAD_HOTKEY = 0x0400 + 1  # ホットキー再読み込み用のカスタムウィンドウメッセージ
    _HOTKEY_IDENTIFIER = 1  # 登録するホットキーの識別ID

    # 特殊キーの仮想キーコード（VKコード）対応マップ
    _SPECIAL_VIRTUAL_KEY_MAP = {
        "print_screen": 0x2C,
        "printscreen": 0x2C,
        "print screen": 0x2C,
        "prntscrn": 0x2C,
        "prtscn": 0x2C,
        "snapshot": 0x2C,
        "space": 0x20,
        "spacebar": 0x20,
        "enter": 0x0D,
        "return": 0x0D,
        "tab": 0x09,
        "backspace": 0x08,
        "esc": 0x1B,
        "escape": 0x1B,
        "insert": 0x2D,
        "delete": 0x2E,
        "del": 0x2E,
        "home": 0x24,
        "end": 0x23,
        "page_up": 0x21,
        "pageup": 0x21,
        "pgup": 0x21,
        "page_down": 0x22,
        "pagedown": 0x22,
        "pgdn": 0x22,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
        "caps_lock": 0x14,
        "capslock": 0x14,
        "num_lock": 0x90,
        "numlock": 0x90,
        "scroll_lock": 0x91,
        "scrolllock": 0x91,
        "pause": 0x13,
    }

    # ファンクションキー（F1〜F24）をマップに追加
    for function_index in range(1, 25):
        _SPECIAL_VIRTUAL_KEY_MAP[f"f{function_index}"] = 0x70 + (function_index - 1)

    # テンキー（Numpad 0〜9）をマップに追加
    for numpad_index in range(10):
        _SPECIAL_VIRTUAL_KEY_MAP[f"numpad_{numpad_index}"] = 0x60 + numpad_index
        _SPECIAL_VIRTUAL_KEY_MAP[f"num_{numpad_index}"] = 0x60 + numpad_index
        _SPECIAL_VIRTUAL_KEY_MAP[f"numpad{numpad_index}"] = 0x60 + numpad_index

    def __init__(self, callback_function):
        """
        HotkeyManagerの初期化

        Args:
            callback_function (callable): ホットキー押下時に呼び出すコールバック関数
        """
        self._callback_function = callback_function
        self._hotkey_thread = None
        self._hotkey_thread_id = None
        self._is_hotkey_registered = False

    @classmethod
    def _parse_shortcut_string(cls, shortcut_string):
        """
        ショートカット文字列（例: 'shift+print_screen', 'ctrl+alt+s'）を
        Windows API用の修飾キーフラグと仮想キーコードに変換する

        Args:
            shortcut_string (str): パース対象のショートカットキー文字列

        Returns:
            tuple: (修飾キーフラグ, 仮想キーコード) のタプル。パース失敗時は (None, None)
        """
        if not shortcut_string or not isinstance(shortcut_string, str):
            return None, None

        # '+' で分割して各キー名を正規化
        key_parts = [part.strip().lower() for part in shortcut_string.split("+") if part.strip()]
        if not key_parts:
            return None, None

        # 末尾が '+' で終わっている（例: 'ctrl+'）など、入力途中の形式は無効とする
        if shortcut_string.strip().endswith("+"):
            return None, None

        # キー長押し時のリピート発火を抑制するフラグを付与
        modifiers = cls._MOD_NOREPEAT
        virtual_key_code = None
        non_modifier_count = 0

        for part in key_parts:
            if part in ("ctrl", "control"):
                modifiers |= cls._MOD_CONTROL
            elif part in ("alt", "option"):
                modifiers |= cls._MOD_ALT
            elif part in ("shift",):
                modifiers |= cls._MOD_SHIFT
            elif part in ("windows", "win", "super"):
                modifiers |= cls._MOD_WIN
            else:
                # 修飾キー以外の主キー
                non_modifier_count += 1
                if part in cls._SPECIAL_VIRTUAL_KEY_MAP:
                    virtual_key_code = cls._SPECIAL_VIRTUAL_KEY_MAP[part]
                elif len(part) == 1:
                    # 1文字のアルファベットまたは数字
                    character = part.upper()
                    if "A" <= character <= "Z" or "0" <= character <= "9":
                        virtual_key_code = ord(character)
                    else:
                        # 記号などの場合は VkKeyScanW で仮想キーコードを取得
                        scanned_code = ctypes.windll.user32.VkKeyScanW(ord(part)) & 0xFF
                        if scanned_code != 0xFF:
                            virtual_key_code = scanned_code
                        else:
                            virtual_key_code = ord(character)
                else:
                    # 未知のキー名が含まれている場合は無効
                    return None, None

        # 主キーがちょうど1つ指定されており、かつ仮想キーコードが特定できた場合のみ有効
        if non_modifier_count != 1 or virtual_key_code is None:
            return None, None

        return modifiers, virtual_key_code

    @classmethod
    def is_valid_shortcut(cls, shortcut_string):
        """
        指定されたショートカットキー文字列が有効なキーの組み合わせかを判定する
        UI向けのエラーメッセージ生成は呼び出し元で行い、ここでは純粋な真偽値のみを返す

        Args:
            shortcut_string (str): 判定対象のショートカットキー文字列

        Returns:
            bool: 有効なキーの組み合わせであれば True、無効なら False
        """
        if not shortcut_string or not str(shortcut_string).strip():
            return False

        modifiers, virtual_key_code = cls._parse_shortcut_string(shortcut_string)
        return modifiers is not None and virtual_key_code is not None

    def _register_hotkey(self, shortcut_string):
        """
        Windows OS にグローバルホットキーを登録する

        Args:
            shortcut_string (str): 登録するショートカットキー文字列

        Returns:
            bool: 登録に成功したかどうか
        """
        modifiers, virtual_key_code = self._parse_shortcut_string(shortcut_string)
        if modifiers is None or virtual_key_code is None:
            notifier.log(f"無効なショートカット形式です: '{shortcut_string}'")
            return False

        # OSのRegisterHotKey APIを呼び出す
        success = ctypes.windll.user32.RegisterHotKey(None, self._HOTKEY_IDENTIFIER, modifiers, virtual_key_code)

        if success:
            self._is_hotkey_registered = True
            notifier.log(f"ショートカットキーを登録しました: {shortcut_string} (MOD: 0x{modifiers:X}, VK: 0x{virtual_key_code:X})")
            return True
        else:
            error_code = ctypes.windll.kernel32.GetLastError()
            notifier.log(f"ショートカットキーの登録に失敗しました: {shortcut_string} (エラーコード: {error_code})")
            return False

    def _unregister_hotkey(self):
        """
        登録済みのグローバルホットキーを解除する
        """
        if self._is_hotkey_registered:
            ctypes.windll.user32.UnregisterHotKey(None, self._HOTKEY_IDENTIFIER)
            self._is_hotkey_registered = False
            notifier.log("ショートカットキーの登録を解除しました。")

    def _message_loop(self):
        """
        Windowsのメッセージループ（GetMessage）を回してグローバルホットキーを常時監視する内部処理
        """
        self._hotkey_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        # 初期設定のショートカットキーを登録
        current_shortcut = settings.get("capture.triggerShortcut")
        self._register_hotkey(current_shortcut)

        message_structure = ctypes.wintypes.MSG()

        # Windows メッセージキューからメッセージを取得するループ（WM_QUITを受信すると0が返り終了する）
        while ctypes.windll.user32.GetMessageW(ctypes.byref(message_structure), None, 0, 0) > 0:
            # ホットキー押下イベントを受信
            if message_structure.message == self._WM_HOTKEY and message_structure.wParam == self._HOTKEY_IDENTIFIER:
                notifier.log("ショートカットキー入力を検知しました。")
                if self._callback_function:
                    # コールバック（撮影処理）を別スレッドで非同期実行
                    threading.Thread(target=self._callback_function, daemon=True).start()

            # 設定変更に伴うホットキー再設定メッセージを受信
            elif message_structure.message == self._WM_USER_RELOAD_HOTKEY:
                notifier.log("ホットキーの再読み込み要求を受信しました。")
                self._unregister_hotkey()
                settings.load()
                new_shortcut = settings.get("capture.triggerShortcut")
                self._register_hotkey(new_shortcut)

            ctypes.windll.user32.TranslateMessage(ctypes.byref(message_structure))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(message_structure))

        # ループ終了時にホットキーを解除
        self._unregister_hotkey()

    def start(self):
        """
        ホットキー監視スレッドを起動する
        """
        if self._hotkey_thread is None or not self._hotkey_thread.is_alive():
            self._hotkey_thread = threading.Thread(target=self._message_loop, daemon=True)
            self._hotkey_thread.start()

    def reload(self):
        """
        設定ファイルを再読み込みし、最新のショートカットキーで再登録する
        """
        if self._hotkey_thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, self._WM_USER_RELOAD_HOTKEY, 0, 0)

    def stop(self):
        """
        ホットキー監視スレッドを終了し、登録を解除する
        """
        if self._hotkey_thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, self._WM_QUIT, 0, 0)
