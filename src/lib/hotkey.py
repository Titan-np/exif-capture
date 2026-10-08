import ctypes
import ctypes.wintypes
import threading

import keyboard

import lib.notifier as notifier

# Windows API（User32, Kernel32）の呼び出し用インスタンス
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class Manager:
    """
    OS全体（グローバル）のショートカットキーを登録・監視するマネージャークラス。

    Windows API の RegisterHotKey を使用し、アプリケーションが非アクティブや
    システムトレイに最小化されている状態でも、指定されたキー入力を検知して
    登録されたコールバック関数（画面キャプチャ処理等）を実行する。
    """

    # RegisterHotKey API に渡す修飾キー（Modifier Keys）フラグ定数
    _MOD_ALT = 0x0001
    _MOD_CONTROL = 0x0002
    _MOD_SHIFT = 0x0004
    _MOD_WIN = 0x0008
    _MOD_NOREPEAT = 0x4000  # キー長押し時の連続発火（オートリピート）を防止するフラグ（Windows 7以降対応）

    # Windowsメッセージ識別子
    _WM_HOTKEY = 0x0312  # 登録されたホットキーが押下された際に送られるメッセージ
    _WM_QUIT = 0x0012  # メッセージループを正常終了させるためのメッセージ
    _WM_USER_RELOAD_HOTKEY = 0x0400 + 1  # 設定変更時にホットキー再登録を促すアプリケーション定義メッセージ
    _HOTKEY_IDENTIFIER = 1  # 登録するホットキーを識別するための一意なID

    # 特殊キー名（文字列）とWindows仮想キーコード（VKコード）の対応定義
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

    # ファンクションキー（F1〜F24）の仮想キーコード（0x70〜0x87）を一括登録
    for function_index in range(1, 25):
        _SPECIAL_VIRTUAL_KEY_MAP[f"f{function_index}"] = 0x70 + (function_index - 1)

    # テンキー（Numpad 0〜9）の仮想キーコード（0x60〜0x69）を一括登録
    for numpad_index in range(10):
        _SPECIAL_VIRTUAL_KEY_MAP[f"numpad_{numpad_index}"] = 0x60 + numpad_index
        _SPECIAL_VIRTUAL_KEY_MAP[f"num_{numpad_index}"] = 0x60 + numpad_index
        _SPECIAL_VIRTUAL_KEY_MAP[f"numpad{numpad_index}"] = 0x60 + numpad_index

    def __init__(self, callback_function, on_registration_failure=None, on_registration_success=None):
        """
        Manager を初期化する。

        Args:
            callback_function (callable): ホットキー押下時に実行するコールバック関数。
            on_registration_failure (callable, optional): ホットキー登録失敗時に呼び出すコールバック関数 (引数: shortcut_string, error_code)。
            on_registration_success (callable, optional): ホットキー登録成功時に呼び出すコールバック関数 (引数: shortcut_string)。
        """
        self._callback_function = callback_function
        self._on_registration_failure = on_registration_failure
        self._on_registration_success = on_registration_success
        self._hotkey_thread = None
        self._hotkey_thread_id = None
        self._is_hotkey_registered = False

    @classmethod
    def _parse_shortcut_string(cls, shortcut_string):
        """
        ショートカットキー文字列（例: 'shift+print_screen'）を解析し、
        Windows API 用の修飾キーフラグと仮想キーコードのタプルに変換する。

        Args:
            shortcut_string (str): 解析対象のショートカットキー文字列。

        Returns:
            tuple: (修飾キーフラグ, 仮想キーコード) のタプル。形式不正時は (None, None)。
        """
        if not shortcut_string or not isinstance(shortcut_string, str):
            return None, None

        # '+' 区切りで分解し、小文字化および前後の空白文字を除去
        key_parts = [part.strip().lower() for part in shortcut_string.split("+") if part.strip()]
        if not key_parts:
            return None, None

        # 末尾が '+' で終わる入力途中の文字列（例: 'ctrl+'）は無効として除外
        if shortcut_string.strip().endswith("+"):
            return None, None

        # キー長押し時の連続発火を防ぐフラグを初期設定
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
                # 修飾キー以外のメインキー（文字・数字・特殊キー）の解析
                non_modifier_count += 1
                if part in cls._SPECIAL_VIRTUAL_KEY_MAP:
                    virtual_key_code = cls._SPECIAL_VIRTUAL_KEY_MAP[part]
                elif len(part) == 1:
                    # 1文字のアルファベットまたは数字
                    character = part.upper()
                    if "A" <= character <= "Z" or "0" <= character <= "9":
                        virtual_key_code = ord(character)
                    else:
                        # 記号文字の場合は VkKeyScanW API を用いて現在のキーボード配列から仮想キーコードを取得
                        scanned_code = user32.VkKeyScanW(ord(part)) & 0xFF
                        if scanned_code != 0xFF:
                            virtual_key_code = scanned_code
                        else:
                            virtual_key_code = ord(character)
                else:
                    # 未定義のキー名が含まれている場合は不正な形式として処理中断
                    return None, None

        # メインキーが1つだけ存在し、正常に仮想キーコードが取得できた場合のみ有効
        if non_modifier_count != 1 or virtual_key_code is None:
            return None, None

        return modifiers, virtual_key_code

    @classmethod
    def is_valid_shortcut(cls, shortcut_string):
        """
        指定された文字列が有効なショートカットキー構成かを検証する。

        Args:
            shortcut_string (str): 検証対象のショートカットキー文字列。

        Returns:
            bool: 有効なショートカットキーとして登録可能な場合は True、それ以外は False。
        """
        if not shortcut_string or not str(shortcut_string).strip():
            return False

        modifiers, virtual_key_code = cls._parse_shortcut_string(shortcut_string)
        return modifiers is not None and virtual_key_code is not None

    def _register_hotkey(self, shortcut_string):
        """
        Windows API (RegisterHotKey) を呼び出し、システムにグローバルホットキーを登録する。

        Args:
            shortcut_string (str): 登録対象のショートカットキー文字列。

        Returns:
            bool: 登録に成功した場合は True、失敗した場合は False。
        """
        modifiers, virtual_key_code = self._parse_shortcut_string(shortcut_string)
        if modifiers is None or virtual_key_code is None:
            notifier.log(f"無効なショートカット形式です: '{shortcut_string}'")
            # 形式不正による登録失敗を呼び出し元へ通知（エラーコードは0）
            if self._on_registration_failure:
                self._on_registration_failure(shortcut_string, 0)
            return False

        # Windows API を呼び出してスレッドにグローバルホットキーを紐付け登録
        success = user32.RegisterHotKey(None, self._HOTKEY_IDENTIFIER, modifiers, virtual_key_code)

        if success:
            self._is_hotkey_registered = True
            notifier.log(f"ショートカットキーを登録しました: {shortcut_string} (MOD: 0x{modifiers:X}, VK: 0x{virtual_key_code:X})")
            # 登録成功を呼び出し元（起動通知やトレイアイコン状態更新など）へ通知
            if self._on_registration_success:
                self._on_registration_success(shortcut_string)
            return True
        else:
            error_code = kernel32.GetLastError()
            notifier.log(f"ショートカットキーの登録に失敗しました: {shortcut_string} (エラーコード: {error_code})")
            # 他アプリとの競合等による登録失敗を呼び出し元へ通知し、ユーザーへの案内を促す
            if self._on_registration_failure:
                self._on_registration_failure(shortcut_string, error_code)
            return False

    def _unregister_hotkey(self):
        """
        登録済みのグローバルホットキーをシステムから解除する。
        """
        if self._is_hotkey_registered:
            user32.UnregisterHotKey(None, self._HOTKEY_IDENTIFIER)
            self._is_hotkey_registered = False
            notifier.log("ショートカットキーの登録を解除しました。")

    def _message_loop(self):
        """
        Windowsメッセージループをバックグラウンドスレッドで実行し、ホットキー入力を待機する。

        GetMessageW によりスレッドのメッセージキューを監視し、
        WM_HOTKEY メッセージを検知した際にコールバック関数を別スレッドで非同期実行する。
        WM_QUIT を受信するとループを終了する。
        """
        self._hotkey_thread_id = kernel32.GetCurrentThreadId()

        # 設定ファイルから現在のショートカットキーを取得して登録
        import lib.settings as settings

        current_shortcut = settings.get("capture.triggerShortcut")
        self._register_hotkey(current_shortcut)

        message_structure = ctypes.wintypes.MSG()

        # メッセージキューからメッセージを取得するループ（WM_QUIT 受信で戻り値 0 となり終了）
        while user32.GetMessageW(ctypes.byref(message_structure), None, 0, 0) > 0:
            # 登録したホットキーの押下イベント（WM_HOTKEY）を検知
            if message_structure.message == self._WM_HOTKEY and message_structure.wParam == self._HOTKEY_IDENTIFIER:
                notifier.log("ショートカットキー入力を検知しました。")
                if self._callback_function:
                    # メッセージループのブロックを防止するため、コールバック関数を別スレッドで非同期実行
                    threading.Thread(target=self._callback_function, daemon=True).start()

            # 設定変更に伴うホットキー再読み込み要求（WM_USER_RELOAD_HOTKEY）を検知
            elif message_structure.message == self._WM_USER_RELOAD_HOTKEY:
                notifier.log("ホットキーの再読み込み要求を受信しました。")
                self._unregister_hotkey()
                settings.load()
                new_shortcut = settings.get("capture.triggerShortcut")
                self._register_hotkey(new_shortcut)

            user32.TranslateMessage(ctypes.byref(message_structure))
            user32.DispatchMessageW(ctypes.byref(message_structure))

        # スレッド終了時に登録済みホットキーを確実に解除
        self._unregister_hotkey()

    def start(self):
        """
        ホットキー監視用のバックグラウンドスレッドを起動する。
        """
        if self._hotkey_thread is None or not self._hotkey_thread.is_alive():
            self._hotkey_thread = threading.Thread(target=self._message_loop, daemon=True)
            self._hotkey_thread.start()

    def reload(self):
        """
        設定ファイルの変更を反映するため、監視スレッドへ再登録メッセージ（WM_USER_RELOAD_HOTKEY）を送信する。
        """
        if self._hotkey_thread_id is not None:
            user32.PostThreadMessageW(self._hotkey_thread_id, self._WM_USER_RELOAD_HOTKEY, 0, 0)

    def stop(self):
        """
        監視スレッドへ終了メッセージ（WM_QUIT）を送信し、ホットキー監視を安全に停止する。
        """
        if self._hotkey_thread_id is not None:
            user32.PostThreadMessageW(self._hotkey_thread_id, self._WM_QUIT, 0, 0)


class Recorder:
    """
    【設定画面用】ユーザーが押したキーの組み合わせを一時的に記録するクラス

    設定画面の「キーを記録」ボタンが押された時だけ動作します。
    keyboardライブラリの非同期フックを用いて、安全かつシンプルにキー入力をキャプチャします。
    """

    # 修飾キーの判定・正規化用マップ
    _MODIFIER_MAP = {
        "ctrl": "ctrl",
        "left ctrl": "ctrl",
        "right ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "left alt": "alt",
        "right alt": "alt",
        "shift": "shift",
        "left shift": "shift",
        "right shift": "shift",
        "windows": "win",
        "left windows": "win",
        "right windows": "win",
        "win": "win",
    }

    # ショートカット文字列を組み立てる際の標準的な修飾キー順序
    _MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]

    def __init__(self, on_captured, on_cancelled):
        """
        HotkeyRecorderの初期化

        Args:
            on_captured (callable): 有効なショートカットキーが確定した時に呼ぶ関数（引数に文字列を渡す）
            on_cancelled (callable): Escキーなどでキャンセルされた時に呼ぶ関数
        """
        self._on_captured = on_captured
        self._on_cancelled = on_cancelled
        self._hook = None
        self._is_finished = False
        # 現在押されている修飾キーの集合を自前で管理
        self._active_modifiers = set()

    def _hook_callback(self, event):
        """
        キーが押された・離された瞬間に非同期で呼び出される処理（コールバック関数）
        """
        if self._is_finished:
            return

        name = (event.name or "").lower()
        event_type = event.event_type

        # キーを離した時: 修飾キーが離されたら追跡セットから除去
        if event_type == "up":
            if name in self._MODIFIER_MAP:
                modifier = self._MODIFIER_MAP[name]
                self._active_modifiers.discard(modifier)
            return

        # キーを押した時（down）
        if event_type == "down":
            notifier.log(f"[フック受信] key='{name}'")

            # 修飾キーが押された場合: 追跡セットに追加し、主キーが押されるのを待つ
            if name in self._MODIFIER_MAP:
                modifier = self._MODIFIER_MAP[name]
                self._active_modifiers.add(modifier)
                notifier.log(f"修飾キー単体のため主キーの入力を待機中: '{name}' (現在の修飾キー: {self._active_modifiers})")
                return

            # Escキーによるキャンセル
            if name in ("esc", "escape"):
                notifier.log("Escキーによるキャンセルを検知しました。")
                self._is_finished = True
                if self._on_cancelled:
                    self._on_cancelled()
                return

            # 押されている修飾キーを標準的な順序で並べる
            modifiers = [mod for mod in self._MODIFIER_ORDER if mod in self._active_modifiers]

            # メインキーの名称を正規化（スペースをアンダースコアに）
            main_key = name.replace(" ", "_")
            candidate_shortcut = "+".join(modifiers + [main_key])

            notifier.log(f"[キー解析] 候補: '{candidate_shortcut}'")

            # 登録可能な組み合わせか判定
            if Manager.is_valid_shortcut(candidate_shortcut):
                notifier.log(f"ショートカットを確定しました: '{candidate_shortcut}'")
                self._is_finished = True
                if self._on_captured:
                    self._on_captured(candidate_shortcut)
            else:
                notifier.log(f"無効なショートカットの組み合わせです: '{candidate_shortcut}'")

    def start(self):
        """
        キーの監視を開始する
        """
        if self._hook is None:
            self._is_finished = False
            self._active_modifiers.clear()
            notifier.log("キー記録フックを開始します。")
            # keyboard.hook により down と up の両方を受け取り、修飾キーの押下状態を正確に追跡
            # suppress=True によってOSや他アプリへのイベント伝播を遮断し、既存ショートカットの暴発を防ぐ
            self._hook = keyboard.hook(self._hook_callback, suppress=True)

    def stop(self):
        """
        キーの監視を終了する
        """
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None
            self._active_modifiers.clear()
            notifier.log("キー記録フックを解除しました。")
