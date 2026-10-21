"""
lib.hotkey モジュールの単体テスト
ショートカットキー文字列の構文解析、妥当性判定、設定変更時の再登録要否判定を検証する
"""

from unittest.mock import MagicMock

import pytest

import lib.hotkey as hotkey


class TestParseShortcutString:
    """
    ショートカットキー文字列の解析（_parse_shortcut_string）に関するテストクラス
    """

    def test_parse_valid_modifier_and_normal_key(self):
        """修飾キーと英数字キーの組み合わせが正しく修飾フラグと仮想キーコードに変換されることを検証する"""
        modifiers, virtual_key_code = hotkey.Manager._parse_shortcut_string("ctrl+s")

        assert modifiers is not None
        assert virtual_key_code is not None
        # Ctrlフラグが含まれていることを確認
        assert bool(modifiers & hotkey.Manager._MOD_CONTROL)
        # オートリピート防止フラグが含まれていることを確認
        assert bool(modifiers & hotkey.Manager._MOD_NOREPEAT)
        # 'S' のASCIIコードと一致することを確認
        assert virtual_key_code == ord("S")

    def test_parse_multiple_modifiers(self):
        """複数の修飾キー（Ctrl + Alt + Shift）が正しく論理和で合成されることを検証する"""
        modifiers, virtual_key_code = hotkey.Manager._parse_shortcut_string("ctrl+alt+shift+a")

        assert modifiers is not None
        assert bool(modifiers & hotkey.Manager._MOD_CONTROL)
        assert bool(modifiers & hotkey.Manager._MOD_ALT)
        assert bool(modifiers & hotkey.Manager._MOD_SHIFT)
        assert virtual_key_code == ord("A")

    def test_parse_special_keys_print_screen(self):
        """PrintScreen の各エイリアス表記（print screen, prtscn, snapshot 等）が同一の仮想キーコードに解決されることを検証する"""
        print_screen_alias_list = [
            "shift+print screen",
            "shift+print_screen",
            "shift+prtscn",
            "shift+snapshot",
        ]

        expected_virtual_key_code = 0x2C  # VK_SNAPSHOT

        for alias in print_screen_alias_list:
            modifiers, virtual_key_code = hotkey.Manager._parse_shortcut_string(alias)
            assert modifiers is not None, f"エイリアス '{alias}' の解析に失敗しました"
            assert bool(modifiers & hotkey.Manager._MOD_SHIFT)
            assert virtual_key_code == expected_virtual_key_code

    def test_parse_function_keys(self):
        """ファンクションキー（F1〜F24）が正しい仮想キーコードに解決されることを検証する"""
        for function_index in range(1, 25):
            shortcut_string = f"ctrl+f{function_index}"
            modifiers, virtual_key_code = hotkey.Manager._parse_shortcut_string(shortcut_string)

            expected_virtual_key_code = 0x70 + (function_index - 1)
            assert modifiers is not None
            assert virtual_key_code == expected_virtual_key_code

    def test_parse_numpad_keys(self):
        """テンキー（numpad_0〜9）が正しい仮想キーコードに解決されることを検証する"""
        for numpad_index in range(10):
            shortcut_string = f"alt+numpad_{numpad_index}"
            modifiers, virtual_key_code = hotkey.Manager._parse_shortcut_string(shortcut_string)

            expected_virtual_key_code = 0x60 + numpad_index
            assert modifiers is not None
            assert virtual_key_code == expected_virtual_key_code

    def test_parse_rejects_empty_and_whitespace(self):
        """空文字や空白のみの入力に対して (None, None) が返却されることを検証する"""
        assert hotkey.Manager._parse_shortcut_string("") == (None, None)
        assert hotkey.Manager._parse_shortcut_string("   ") == (None, None)
        assert hotkey.Manager._parse_shortcut_string(None) == (None, None)

    def test_parse_rejects_trailing_plus(self):
        """入力途中を示す末尾プラス記号の文字列が拒否されることを検証する"""
        assert hotkey.Manager._parse_shortcut_string("ctrl+") == (None, None)
        assert hotkey.Manager._parse_shortcut_string("shift+alt+") == (None, None)

    def test_parse_rejects_modifier_only(self):
        """修飾キーのみでメインキーが存在しない組み合わせが拒否されることを検証する"""
        assert hotkey.Manager._parse_shortcut_string("ctrl") == (None, None)
        assert hotkey.Manager._parse_shortcut_string("ctrl+shift") == (None, None)
        assert hotkey.Manager._parse_shortcut_string("alt+win") == (None, None)

    def test_parse_rejects_multiple_main_keys(self):
        """メインキーが2つ以上指定されている不正な組み合わせが拒否されることを検証する"""
        assert hotkey.Manager._parse_shortcut_string("ctrl+a+b") == (None, None)
        assert hotkey.Manager._parse_shortcut_string("shift+f1+f2") == (None, None)

    def test_parse_rejects_unknown_key_name(self):
        """未定義のキー名が含まれている場合に拒否されることを検証する"""
        assert hotkey.Manager._parse_shortcut_string("ctrl+invalid_key_name") == (None, None)

    def test_parse_symbol_key_uses_keyboard_layout(self, monkeypatch):
        """記号キーが、現在のキーボード配列から取得した仮想キーコードに変換されることを検証する"""
        # VkKeyScanW は下位バイトに仮想キーコード（0xBA: VK_OEM_1）、上位バイトにシフト状態を返す
        monkeypatch.setattr(hotkey, "user32", MagicMock(VkKeyScanW=MagicMock(return_value=0x01BA)))

        assert hotkey.Manager._parse_shortcut_string("ctrl+;")[1] == 0xBA

    def test_parse_rejects_symbol_key_missing_in_keyboard_layout(self, monkeypatch):
        """現在のキーボード配列に無い記号キーが、文字コードで代用されず拒否されることを検証する"""
        # VkKeyScanW は該当キーが無い場合に -1 を返す
        monkeypatch.setattr(hotkey, "user32", MagicMock(VkKeyScanW=MagicMock(return_value=-1)))

        assert hotkey.Manager._parse_shortcut_string("ctrl+;") == (None, None)


class TestIsValidShortcut:
    """
    ショートカットキー妥当性判定（is_valid_shortcut）に関するテストクラス
    """

    def test_is_valid_shortcut_returns_true_for_valid(self):
        """有効なショートカットキー文字列に対して True を返すことを検証する"""
        valid_shortcut_list = [
            "shift+print screen",
            "ctrl+s",
            "ctrl+alt+delete",
            "f12",
            "alt+space",
        ]
        for valid_shortcut in valid_shortcut_list:
            assert hotkey.Manager.is_valid_shortcut(valid_shortcut) is True

    def test_is_valid_shortcut_returns_false_for_invalid(self):
        """無効なショートカットキー文字列に対して False を返すことを検証する"""
        invalid_shortcut_list = [
            "",
            "   ",
            None,
            "ctrl+",
            "ctrl+shift",
            "ctrl+a+b",
            "unknown_key",
        ]
        for invalid_shortcut in invalid_shortcut_list:
            assert hotkey.Manager.is_valid_shortcut(invalid_shortcut) is False


class TestConflictsWithTyping:
    """
    文字入力と衝突するショートカットキーの判定（conflicts_with_typing）に関するテストクラス
    """

    def test_returns_true_for_typing_keys_without_ctrl_alt_win(self):
        """文字入力に使うキーを、修飾キーなし・Shift のみで押す組み合わせで True を返すことを検証する"""
        conflicting_shortcut_list = ["a", "1", "shift+a", "space"]
        for conflicting_shortcut in conflicting_shortcut_list:
            assert hotkey.Manager.conflicts_with_typing(conflicting_shortcut) is True, conflicting_shortcut

    def test_returns_false_for_safe_shortcuts(self):
        """Ctrl / Alt / Win を含む組み合わせや、文字入力に使わないキーで False を返すことを検証する"""
        safe_shortcut_list = ["ctrl+a", "alt+1", "win+shift+s", "f12", "print screen", "shift+print screen", ""]
        for safe_shortcut in safe_shortcut_list:
            assert hotkey.Manager.conflicts_with_typing(safe_shortcut) is False, safe_shortcut


class TestConflictsWithStandardShortcut:
    """
    他のアプリの標準的なショートカットとの衝突判定（conflicts_with_standard_shortcut）に関するテストクラス
    """

    def test_returns_true_for_standard_shortcuts(self):
        """コピー・貼り付け・終了などの標準的なショートカット（表記揺れを含む）で True を返すことを検証する"""
        for standard_shortcut in ["ctrl+c", "Ctrl+V", "control+z", "alt+f4"]:
            assert hotkey.Manager.conflicts_with_standard_shortcut(standard_shortcut) is True, standard_shortcut

    def test_returns_false_for_other_shortcuts(self):
        """修飾キーが異なる組み合わせや、標準的でないショートカット、不正な形式で False を返すことを検証する"""
        for other_shortcut in ["ctrl+shift+c", "shift+print screen", "alt+c", ""]:
            assert hotkey.Manager.conflicts_with_standard_shortcut(other_shortcut) is False, other_shortcut


class TestRegisterHotkey:
    """
    ホットキーの登録（_register_hotkey）に関するテストクラス
    """

    def test_passes_last_error_code_on_registration_failure(self, monkeypatch):
        """登録失敗時に、ctypes が保持した Windows のエラーコードを失敗コールバックへ渡すことを検証する"""
        # RegisterHotKey を失敗させ、エラーコード 1409（ERROR_HOTKEY_ALREADY_REGISTERED）を返すようにする
        monkeypatch.setattr(hotkey, "user32", MagicMock(RegisterHotKey=MagicMock(return_value=0)))
        monkeypatch.setattr(hotkey.ctypes, "get_last_error", lambda: 1409)
        on_registration_failure = MagicMock()

        manager = hotkey.Manager(callback_function=None, on_registration_failure=on_registration_failure)
        assert manager._register_hotkey("ctrl+s") is False

        on_registration_failure.assert_called_once_with("ctrl+s", 1409)


class TestReloadHotkey:
    """
    設定変更時のホットキー再登録要否判定（_reload_hotkey）に関するテストクラス
    """

    @pytest.fixture
    def manager_with_registered_key(self, monkeypatch):
        """
        「shift+print screen」が登録済みの状態の Manager を生成し、OSへの登録・解除をモック化する fixture

        Args:
            monkeypatch (pytest.MonkeyPatch): pytest のモンキーパッチ用オブジェクト

        Returns:
            hotkey.Manager: 登録・解除処理がモックに差し替えられた Manager
        """
        monkeypatch.setattr("lib.settings.load", MagicMock())

        manager = hotkey.Manager(callback_function=None)
        manager._is_hotkey_registered = True
        manager._registered_key_combination = hotkey.Manager._parse_shortcut_string("shift+print screen")

        # 実際の RegisterHotKey / UnregisterHotKey を呼ばないようモックに差し替え
        manager._register_hotkey = MagicMock()
        manager._unregister_hotkey = MagicMock()
        return manager

    def test_skips_reregistration_when_shortcut_unchanged(self, monkeypatch, manager_with_registered_key):
        """登録中と同じ組み合わせ（表記揺れを含む）であれば、解除・再登録を行わないことを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: "shift+print_screen")

        manager_with_registered_key._reload_hotkey()

        manager_with_registered_key._unregister_hotkey.assert_not_called()
        manager_with_registered_key._register_hotkey.assert_not_called()

    def test_reregisters_when_shortcut_changed(self, monkeypatch, manager_with_registered_key):
        """異なる組み合わせに変更された場合、旧キーを解除して新キーを登録することを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: "ctrl+shift+s")

        manager_with_registered_key._reload_hotkey()

        manager_with_registered_key._unregister_hotkey.assert_called_once()
        manager_with_registered_key._register_hotkey.assert_called_once_with("ctrl+shift+s")

    def test_reregisters_when_previous_registration_failed(self, monkeypatch, manager_with_registered_key):
        """前回の登録に失敗している場合、同じ組み合わせでも再登録を試みることを検証する"""
        monkeypatch.setattr("lib.settings.get", lambda key: "shift+print screen")
        manager_with_registered_key._is_hotkey_registered = False

        manager_with_registered_key._reload_hotkey()

        manager_with_registered_key._register_hotkey.assert_called_once_with("shift+print screen")
