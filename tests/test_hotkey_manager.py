"""
hotkey_manager モジュールの単体テスト
ショートカットキー文字列の構文解析および妥当性判定ロジックを検証する
"""

import pytest
from hotkey_manager import HotkeyManager


class TestParseShortcutString:
    """
    ショートカットキー文字列の解析（_parse_shortcut_string）に関するテストクラス
    """

    def test_parse_valid_modifier_and_normal_key(self):
        """修飾キーと英数字キーの組み合わせが正しく修飾フラグと仮想キーコードに変換されることを検証する"""
        modifiers, virtual_key_code = HotkeyManager._parse_shortcut_string("ctrl+s")

        assert modifiers is not None
        assert virtual_key_code is not None
        # Ctrlフラグが含まれていることを確認
        assert bool(modifiers & HotkeyManager._MOD_CONTROL)
        # オートリピート防止フラグが含まれていることを確認
        assert bool(modifiers & HotkeyManager._MOD_NOREPEAT)
        # 'S' のASCIIコードと一致することを確認
        assert virtual_key_code == ord("S")

    def test_parse_multiple_modifiers(self):
        """複数の修飾キー（Ctrl + Alt + Shift）が正しく論理和で合成されることを検証する"""
        modifiers, virtual_key_code = HotkeyManager._parse_shortcut_string("ctrl+alt+shift+a")

        assert modifiers is not None
        assert bool(modifiers & HotkeyManager._MOD_CONTROL)
        assert bool(modifiers & HotkeyManager._MOD_ALT)
        assert bool(modifiers & HotkeyManager._MOD_SHIFT)
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
            modifiers, virtual_key_code = HotkeyManager._parse_shortcut_string(alias)
            assert modifiers is not None, f"エイリアス '{alias}' の解析に失敗しました"
            assert bool(modifiers & HotkeyManager._MOD_SHIFT)
            assert virtual_key_code == expected_virtual_key_code

    def test_parse_function_keys(self):
        """ファンクションキー（F1〜F24）が正しい仮想キーコードに解決されることを検証する"""
        for function_index in range(1, 25):
            shortcut_string = f"ctrl+f{function_index}"
            modifiers, virtual_key_code = HotkeyManager._parse_shortcut_string(shortcut_string)

            expected_virtual_key_code = 0x70 + (function_index - 1)
            assert modifiers is not None
            assert virtual_key_code == expected_virtual_key_code

    def test_parse_numpad_keys(self):
        """テンキー（numpad_0〜9）が正しい仮想キーコードに解決されることを検証する"""
        for numpad_index in range(10):
            shortcut_string = f"alt+numpad_{numpad_index}"
            modifiers, virtual_key_code = HotkeyManager._parse_shortcut_string(shortcut_string)

            expected_virtual_key_code = 0x60 + numpad_index
            assert modifiers is not None
            assert virtual_key_code == expected_virtual_key_code

    def test_parse_rejects_empty_and_whitespace(self):
        """空文字や空白のみの入力に対して (None, None) が返却されることを検証する"""
        assert HotkeyManager._parse_shortcut_string("") == (None, None)
        assert HotkeyManager._parse_shortcut_string("   ") == (None, None)
        assert HotkeyManager._parse_shortcut_string(None) == (None, None)

    def test_parse_rejects_trailing_plus(self):
        """入力途中を示す末尾プラス記号の文字列が拒否されることを検証する"""
        assert HotkeyManager._parse_shortcut_string("ctrl+") == (None, None)
        assert HotkeyManager._parse_shortcut_string("shift+alt+") == (None, None)

    def test_parse_rejects_modifier_only(self):
        """修飾キーのみでメインキーが存在しない組み合わせが拒否されることを検証する"""
        assert HotkeyManager._parse_shortcut_string("ctrl") == (None, None)
        assert HotkeyManager._parse_shortcut_string("ctrl+shift") == (None, None)
        assert HotkeyManager._parse_shortcut_string("alt+win") == (None, None)

    def test_parse_rejects_multiple_main_keys(self):
        """メインキーが2つ以上指定されている不正な組み合わせが拒否されることを検証する"""
        assert HotkeyManager._parse_shortcut_string("ctrl+a+b") == (None, None)
        assert HotkeyManager._parse_shortcut_string("shift+f1+f2") == (None, None)

    def test_parse_rejects_unknown_key_name(self):
        """未定義のキー名が含まれている場合に拒否されることを検証する"""
        assert HotkeyManager._parse_shortcut_string("ctrl+invalid_key_name") == (None, None)


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
            assert HotkeyManager.is_valid_shortcut(valid_shortcut) is True

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
            assert HotkeyManager.is_valid_shortcut(invalid_shortcut) is False
