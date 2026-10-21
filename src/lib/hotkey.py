import ctypes
import ctypes.wintypes
import threading

import keyboard

import lib.notifier as notifier

# Windows API（User32, Kernel32）の呼び出し用インスタンス
# User32 は登録失敗時のエラーコードを ctypes.get_last_error() で取得するため、use_last_error を有効にして読み込む
# （後から GetLastError() を呼ぶと、間に挟まる ctypes 内部の処理でエラーコードが上書きされる場合があるため）
user32 = ctypes.WinDLL("user32", use_last_error=True)
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
        # 登録中のキーの組み合わせ (修飾キーフラグ, 仮想キーコード)。再読み込み時に変更有無を判定するために保持する
        self._registered_key_combination = None

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
        # 1. 文字列でない・空の場合は不正な形式とする
        if not shortcut_string or not isinstance(shortcut_string, str):
            return None, None

        # 2. '+' 区切りで分解し、小文字化および前後の空白文字を除去
        key_parts = [part.strip().lower() for part in shortcut_string.split("+") if part.strip()]
        if not key_parts:
            return None, None

        # 3. 末尾が '+' で終わる入力途中の文字列（例: 'ctrl+'）は無効として除外
        if shortcut_string.strip().endswith("+"):
            return None, None

        # 4. キー長押し時の連続発火を防ぐフラグを初期設定し、各キーを修飾キーとメインキーに振り分ける
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
                        # 取得できない（現在の配列に無い）記号は、文字コードを代わりに使うと別のキーが登録されてしまうため不正な形式とする
                        scanned_code = user32.VkKeyScanW(ord(part)) & 0xFF
                        if scanned_code == 0xFF:
                            return None, None
                        virtual_key_code = scanned_code
                else:
                    # 未定義のキー名が含まれている場合は不正な形式として処理中断
                    return None, None

        # 5. メインキーが1つだけ存在し、正常に仮想キーコードが取得できた場合のみ有効
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

    @classmethod
    def conflicts_with_typing(cls, shortcut_string):
        """
        指定された文字列が、文字入力に使うキーを Ctrl / Alt / Win なしで押す組み合わせかを判定する
        登録するとOS全体でそのキー入力が横取りされ、すべてのアプリで入力できなくなるため、設定時の警告に使う

        Args:
            shortcut_string (str): 判定対象のショートカットキー文字列。

        Returns:
            bool: 文字入力と衝突する場合は True。形式が不正な場合や衝突しない場合は False。
        """
        # 1. ショートカット文字列を解析する（形式が不正な場合は衝突しないとみなす）
        modifiers, virtual_key_code = cls._parse_shortcut_string(shortcut_string)
        if virtual_key_code is None:
            return False

        # 2. Ctrl / Alt / Win のいずれかを含む組み合わせは文字入力に使われない（Shift のみは大文字・記号の入力に使われる）
        if modifiers & (cls._MOD_CONTROL | cls._MOD_ALT | cls._MOD_WIN):
            return False

        # 3. 数字（0x30〜0x39）・英字（0x41〜0x5A）・記号（OEMキー 0xBA〜0xE2）・スペース（0x20）は文字入力に使われる
        return 0x30 <= virtual_key_code <= 0x39 or 0x41 <= virtual_key_code <= 0x5A or 0xBA <= virtual_key_code <= 0xE2 or virtual_key_code == 0x20

    @classmethod
    def conflicts_with_standard_shortcut(cls, shortcut_string):
        """
        指定された文字列が、他のアプリで標準的に使われるショートカット（コピーなど）と同じ組み合わせかを判定する
        アプリ内で処理されるショートカットは OS 全体のホットキーとして登録されていないため登録に成功してしまい、
        すべてのアプリでその操作が使えなくなる。設定時の警告に使う

        Args:
            shortcut_string (str): 判定対象のショートカットキー文字列。

        Returns:
            bool: 標準的なショートカットと同じ組み合わせの場合は True。形式が不正な場合や異なる場合は False。
        """
        # 他のアプリで標準的に使われるショートカット（全選択・コピー・貼り付け・切り取り・元に戻す・やり直し・保存・検索・印刷・新規・開く・閉じる・終了）
        STANDARD_SHORTCUTS = ("ctrl+a", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+s", "ctrl+f", "ctrl+p", "ctrl+n", "ctrl+o", "ctrl+w", "alt+f4")

        # 1. ショートカット文字列を解析する（形式が不正な場合は衝突しないとみなす）
        key_combination = cls._parse_shortcut_string(shortcut_string)
        if key_combination[1] is None:
            return False

        # 2. 表記揺れ（例: "Ctrl+C" と "control+c"）を同一とみなすため、解析結果どうしで比較する
        return any(cls._parse_shortcut_string(standard_shortcut) == key_combination for standard_shortcut in STANDARD_SHORTCUTS)

    def _register_hotkey(self, shortcut_string):
        """
        Windows API (RegisterHotKey) を呼び出し、システムにグローバルホットキーを登録する。

        Args:
            shortcut_string (str): 登録対象のショートカットキー文字列。

        Returns:
            bool: 登録に成功した場合は True、失敗した場合は False。
        """
        # 1. ショートカット文字列を解析し、形式が不正な場合は登録せずに失敗とする
        modifiers, virtual_key_code = self._parse_shortcut_string(shortcut_string)
        if modifiers is None or virtual_key_code is None:
            notifier.log(f"無効なショートカット形式です: '{shortcut_string}'")
            # 形式不正による登録失敗を呼び出し元へ通知（エラーコードは0）
            if self._on_registration_failure:
                self._on_registration_failure(shortcut_string, 0)
            return False

        # 2. Windows API を呼び出してスレッドにグローバルホットキーを紐付け登録
        success = user32.RegisterHotKey(None, self._HOTKEY_IDENTIFIER, modifiers, virtual_key_code)

        if success:
            self._is_hotkey_registered = True
            self._registered_key_combination = (modifiers, virtual_key_code)
            notifier.log(f"ショートカットキーを登録しました: {shortcut_string} (MOD: 0x{modifiers:X}, VK: 0x{virtual_key_code:X})")
            # 登録成功を呼び出し元（起動通知やトレイアイコン状態更新など）へ通知
            if self._on_registration_success:
                self._on_registration_success(shortcut_string)
            return True
        else:
            error_code = ctypes.get_last_error()
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
            self._registered_key_combination = None
            notifier.log("ショートカットキーの登録を解除しました。")

    def _message_loop(self):
        """
        Windowsメッセージループをバックグラウンドスレッドで実行し、ホットキー入力を待機する。

        GetMessageW によりスレッドのメッセージキューを監視し、
        WM_HOTKEY メッセージを検知した際にコールバック関数を別スレッドで非同期実行する。
        WM_QUIT を受信するとループを終了する。
        """
        # 1. 再登録・終了のメッセージを送ってもらうため、このスレッドのIDを控える
        self._hotkey_thread_id = kernel32.GetCurrentThreadId()

        # 2. 設定ファイルから現在のショートカットキーを取得して登録
        import lib.settings as settings

        current_shortcut = settings.get("capture.triggerShortcut")
        self._register_hotkey(current_shortcut)

        message_structure = ctypes.wintypes.MSG()

        # 3. メッセージキューからメッセージを取得するループ（WM_QUIT 受信で戻り値 0 となり終了）
        while user32.GetMessageW(ctypes.byref(message_structure), None, 0, 0) > 0:
            # 登録したホットキーの押下イベント（WM_HOTKEY）を検知
            if message_structure.message == self._WM_HOTKEY and message_structure.wParam == self._HOTKEY_IDENTIFIER:
                notifier.log("ショートカットキー入力を検知しました。")
                if self._callback_function:
                    # メッセージループのブロックを防止するため、コールバック関数を別スレッドで非同期実行
                    threading.Thread(target=self._callback_function, daemon=True).start()

            # 設定変更に伴うホットキー再読み込み要求（WM_USER_RELOAD_HOTKEY）を検知
            elif message_structure.message == self._WM_USER_RELOAD_HOTKEY:
                self._reload_hotkey()

            user32.TranslateMessage(ctypes.byref(message_structure))
            user32.DispatchMessageW(ctypes.byref(message_structure))

        # 4. スレッド終了時に登録済みホットキーを確実に解除
        self._unregister_hotkey()

    def _reload_hotkey(self):
        """
        設定ファイルを再読み込みし、ショートカットキーが変わっている場合のみホットキーを再登録する。
        """
        import lib.settings as settings

        notifier.log("ホットキーの再読み込み要求を受信しました。")
        # 1. 他の設定項目の変更もメインプロセスへ反映させるため、キーの変更有無に関わらず設定ファイルは再読み込みする
        settings.load()
        new_shortcut = settings.get("capture.triggerShortcut")

        # 2. 登録中のキーと同じ組み合わせであれば、解除・再登録と変更通知を行わない
        # 表記揺れ（例: "print screen" と "print_screen"）を同一とみなすため、文字列ではなく解析結果で比較する
        # 前回の登録に失敗している場合は、競合が解消されている可能性があるため再登録を試みる
        if self._is_hotkey_registered and self._parse_shortcut_string(new_shortcut) == self._registered_key_combination:
            notifier.log("ショートカットキーに変更がないため、再登録を省略しました。")
            return

        # 3. 変更があれば旧キーを解除して新キーを登録
        self._unregister_hotkey()
        self._register_hotkey(new_shortcut)

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

        # 1. キーを離した時: 修飾キーが離されたら追跡セットから除去
        if event_type == "up":
            if name in self._MODIFIER_MAP:
                modifier = self._MODIFIER_MAP[name]
                self._active_modifiers.discard(modifier)
            return

        # 2. キーを押した時（down）
        if event_type == "down":
            notifier.log(f"[フック受信] key='{name}'")

            # 2-1. 修飾キーが押された場合: 追跡セットに追加し、主キーが押されるのを待つ
            if name in self._MODIFIER_MAP:
                modifier = self._MODIFIER_MAP[name]
                self._active_modifiers.add(modifier)
                notifier.log(f"修飾キー単体のため主キーの入力を待機中: '{name}' (現在の修飾キー: {self._active_modifiers})")
                return

            # 2-2. Escキーによるキャンセル
            if name in ("esc", "escape"):
                notifier.log("Escキーによるキャンセルを検知しました。")
                self._is_finished = True
                if self._on_cancelled:
                    self._on_cancelled()
                return

            # 2-3. 押されている修飾キーを標準的な順序で並べる
            modifiers = [mod for mod in self._MODIFIER_ORDER if mod in self._active_modifiers]

            # 2-4. メインキーの名称を正規化（スペースをアンダースコアに）
            main_key = name.replace(" ", "_")
            candidate_shortcut = "+".join(modifiers + [main_key])

            notifier.log(f"[キー解析] 候補: '{candidate_shortcut}'")

            # 2-5. 登録可能な組み合わせか判定し、登録可能であれば記録を確定する
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
