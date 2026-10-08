"""
lib.settings モジュールの単体テスト
設定のバリデーション、読み込み、保存、旧キー移行、破損時リカバリを網羅的に検証する
"""

import json
import os

import lib.settings as settings


class TestValidation:
    """
    設定項目の入力値バリデーションに関するテストクラス
    """

    def test_validate_not_empty_rejects_empty(self):
        """空文字やNoneが必須チェックで正しく拒否されることを検証する"""
        # 空文字列の検証
        empty_result = settings._validate_not_empty("")
        assert empty_result is not None
        assert "必須項目です" in empty_result

        # 空白のみの文字列の検証
        whitespace_result = settings._validate_not_empty("   ")
        assert whitespace_result is not None
        assert "必須項目です" in whitespace_result

        # None の検証
        none_result = settings._validate_not_empty(None)
        assert none_result is not None
        assert "必須項目です" in none_result

    def test_validate_not_empty_accepts_valid_string(self):
        """値が入力されている場合に正常終了（None返却）することを検証する"""
        valid_result = settings._validate_not_empty("valid_value")
        assert valid_result is None

    def test_validate_path_chars_rejects_forbidden_chars(self):
        """Windows の禁止文字が含まれるパスが拒否されることを検証する"""
        # 禁止文字を含むパスのリスト
        forbidden_character_list = ["<", ">", '"', "|", "?", "*"]
        for character in forbidden_character_list:
            test_path = f"C:\\Screenshots\\test{character}dir"
            validation_error = settings._validate_path_chars(test_path)
            assert validation_error is not None
            assert "フォルダパスに使用できない文字が含まれています" in validation_error

    def test_validate_path_chars_rejects_invalid_colon(self):
        """ドライブレター以外にコロンが含まれている場合に拒否されることを検証する"""
        invalid_path = "C:\\Screenshots:extra\\folder"
        validation_error = settings._validate_path_chars(invalid_path)
        assert validation_error is not None
        assert "フォルダパスに使用できない文字が含まれています: :" in validation_error

    def test_validate_path_chars_rejects_invalid_drive_format(self):
        """不正なドライブ名（英字以外など）が指定された場合に拒否されることを検証する"""
        invalid_drive_path = "1:\\Screenshots"
        validation_error = settings._validate_path_chars(invalid_drive_path)
        assert validation_error is not None
        assert "ドライブ指定が不正です" in validation_error

    def test_validate_path_chars_accepts_valid_paths(self):
        """正常なフォルダパス（絶対パス・チルダ・環境変数）が承認されることを検証する"""
        valid_path_list = [
            "C:\\Screenshots",
            "D:\\Pictures\\Captures",
            "~\\Pictures\\Screenshots",
        ]
        for valid_path in valid_path_list:
            validation_error = settings._validate_path_chars(valid_path)
            assert validation_error is None

    def test_validate_filename_chars_rejects_forbidden_chars(self):
        """ファイル名として使用できない禁止文字が固定文字列に含まれる場合に拒否されることを検証する"""
        # Windowsファイル名の禁止文字
        forbidden_filename_character_list = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
        for character in forbidden_filename_character_list:
            test_preset = f"shot_{character}_{{timestamp}}.png"
            validation_error = settings._validate_filename_chars(test_preset)
            assert validation_error is not None
            assert "ファイル名に使用できない文字が含まれています" in validation_error

    def test_validate_filename_chars_ignores_placeholder_brackets(self):
        """プレースホルダ内部の書式指定子に含まれる記号（コロンなど）が誤検知されないことを検証する"""
        # プレースホルダ内にコロンなどの記号が含まれていても固定文字列側でなければ許容
        safe_preset = "{timestamp:%Y%m%d_%H%M%S}_{title}.png"
        validation_error = settings._validate_filename_chars(safe_preset)
        assert validation_error is None

    def test_validate_shortcut_format_delegates_to_hotkey_manager(self):
        """ショートカットキー検証が lib.hotkey と連動して正常・異常を判定することを検証する"""
        # 有効なショートカット
        assert settings._validate_shortcut_format("shift+print screen") is None
        assert settings._validate_shortcut_format("ctrl+alt+s") is None

        # 無効なショートカット（空文字・末尾プラスなど）
        assert settings._validate_shortcut_format("") is not None
        assert settings._validate_shortcut_format("ctrl+") is not None

    def test_validate_preset_placeholders_accepts_allowed_keys(self):
        """許可されているプレースホルダ（timestamp, title）が承認されることを検証する"""
        valid_preset_list = [
            "{timestamp}_{title}.png",
            "{timestamp:%Y-%m-%d}_{title}.png",
            "capture_{title}.png",
            "screenshot_{timestamp}.png",
        ]
        for valid_preset in valid_preset_list:
            validation_error = settings._validate_preset_placeholders(valid_preset)
            assert validation_error is None

    def test_validate_preset_placeholders_rejects_unknown_keys(self):
        """未定義のプレースホルダキーが指定された場合に拒否されることを検証する"""
        unknown_key_preset = "{unknown_key}_{title}.png"
        validation_error = settings._validate_preset_placeholders(unknown_key_preset)
        assert validation_error is not None
        assert "使用できないプレースホルダです: {unknown_key}" in validation_error

    def test_validate_preset_placeholders_rejects_unbalanced_braces(self):
        """波括弧の対応が取れていない不正な書式が拒否されることを検証する"""
        unbalanced_preset_list = [
            "{timestamp_{title}.png",
            "timestamp}_{title}.png",
            "{timestamp.png",
            "title}.png",
        ]
        for unbalanced_preset in unbalanced_preset_list:
            validation_error = settings._validate_preset_placeholders(unbalanced_preset)
            assert validation_error is not None
            assert "書式が不正です" in validation_error or "使用できないプレースホルダ" in validation_error

    def test_validate_all_returns_errors_for_invalid_entries(self):
        """複数の設定項目に対して一括検証を実行し、エラー項目のみ辞書として返却されることを検証する"""
        test_settings_data = {
            "capture.triggerShortcut": "",  # 空文字のためエラー
            "save.directory": "C:\\Screenshots",  # 正常
            "save.filenamePreset": "test<{title}>.png",  # 禁止文字を含むためエラー
        }
        validation_error_dictionary = settings.validate_all(test_settings_data)

        assert "capture.triggerShortcut" in validation_error_dictionary
        assert "save.filenamePreset" in validation_error_dictionary
        assert "save.directory" not in validation_error_dictionary


class TestSettingsManagerIO:
    """
    設定ファイルの読み書き・破損退避・マイグレーションに関するテストクラス
    """

    def test_load_creates_default_settings_when_file_not_exists(self, isolated_settings_manager):
        """設定ファイルが存在しない場合に、デフォルト値が適用されて新規作成されることを検証する"""
        # 設定ファイルが存在しない状態で読み込みを実行
        settings.load()

        # デフォルト値が設定されていることを確認
        assert settings.get("capture.triggerShortcut") == "shift+print screen"
        assert settings.get("capture.soundVolume") == 100
        assert settings.get("save.embedDatetimeMetadata") is True

        # 設定ファイルがディスク上に新規生成されていることを確認
        assert os.path.exists(settings._get_settings_path())

    def test_load_reads_existing_valid_settings(self, isolated_settings_manager):
        """既存の有効な設定ファイルから設定値を正しく読み込めることを検証する"""
        custom_settings = {
            "capture.triggerShortcut": "ctrl+shift+f12",
            "capture.enableSystemNotification": False,
            "capture.soundVolume": 50,
            "save.directory": "D:\\CustomScreenshots",
            "save.filenamePreset": "custom_{timestamp}.png",
            "save.embedDatetimeMetadata": False,
        }

        # 設定ファイルを事前作成
        with open(settings._get_settings_path(), "w", encoding="utf-8") as file:
            json.dump(custom_settings, file, indent=4)

        # 読み込みを実行
        settings.load()

        # 読み込んだ値が反映されていることを確認
        assert settings.get("capture.triggerShortcut") == "ctrl+shift+f12"
        assert settings.get("capture.soundVolume") == 50
        assert settings.get("save.directory") == "D:\\CustomScreenshots"
        assert settings.get("save.embedDatetimeMetadata") is False

    def test_load_migrates_old_key_names(self, isolated_settings_manager):
        """旧バージョンのキー名が設定ファイルに含まれている場合、新キー名へ自動移行されることを検証する"""
        legacy_settings = {
            "trigger_shortcut": "ctrl+alt+a",
            "save_directory": "D:\\LegacyDirectory",
            "filename_preset": "{title}_{timestamp}.png",
            "embed_datetime_metadata": False,
        }

        # 旧形式の設定ファイルを作成
        with open(settings._get_settings_path(), "w", encoding="utf-8") as file:
            json.dump(legacy_settings, file, indent=4)

        # 読み込みを実行（マイグレーションが自動実行される）
        settings.load()

        # 新しいキー名で値が取得できることを確認
        assert settings.get("capture.triggerShortcut") == "ctrl+alt+a"
        assert settings.get("save.directory") == "D:\\LegacyDirectory"
        assert settings.get("save.filenamePreset") == "{title}_{timestamp}.png"
        assert settings.get("save.embedDatetimeMetadata") is False

        # ファイルへ保存され、旧キーが除去されていることを確認
        with open(settings._get_settings_path(), "r", encoding="utf-8") as file:
            migrated_content = json.load(file)
            assert "trigger_shortcut" not in migrated_content
            assert "capture.triggerShortcut" in migrated_content

    def test_load_handles_corrupted_json_and_recovers(self, isolated_settings_manager):
        """JSON構文が破壊されている設定ファイルを読み込んだ際、退避してデフォルト値で復旧することを検証する"""
        # 不正なJSONファイルを作成
        with open(settings._get_settings_path(), "w", encoding="utf-8") as file:
            file.write("{ invalid_json: broken content... ")

        # 読み込みを実行
        settings.load()

        # デフォルト値に復帰していることを確認
        assert settings.get("capture.triggerShortcut") == "shift+print screen"

        # 破損ファイルが退避されていることを確認（.corrupted_ プレフィックスのファイルが存在すること）
        backup_files = [filename for filename in os.listdir(os.path.dirname(settings._get_settings_path())) if "settings.json.corrupted_" in filename]
        assert len(backup_files) == 1

    def test_load_replaces_invalid_value_with_default(self, isolated_settings_manager):
        """個別項目の値が不正である場合、その項目のみデフォルト値へ安全に差し替えられることを検証する"""
        semi_broken_settings = {
            "capture.triggerShortcut": "",  # 不正値（空文字）
            "capture.soundVolume": 80,  # 正常値
            "save.directory": "C:\\Screenshots",  # 正常値
        }

        with open(settings._get_settings_path(), "w", encoding="utf-8") as file:
            json.dump(semi_broken_settings, file, indent=4)

        # 読み込みを実行
        settings.load()

        # 不正な項目はデフォルト値に差し替えられ、正常な項目は維持されることを確認
        assert settings.get("capture.triggerShortcut") == "shift+print screen"
        assert settings.get("capture.soundVolume") == 80

    def test_save_atomic_write_creates_valid_json(self, isolated_settings_manager):
        """save() による書き込みで一時ファイルを経由して安全にJSONが保存されることを検証する"""
        settings.set("capture.soundVolume", 30)
        settings.save()

        # 保存先のファイルが存在し、内容が正しく更新されていることを確認
        assert os.path.exists(settings._get_settings_path())
        # 一時ファイルは残存していないことを確認
        assert not os.path.exists(settings._get_temporary_settings_path())

        with open(settings._get_settings_path(), "r", encoding="utf-8") as file:
            saved_content = json.load(file)
            assert saved_content.get("capture.soundVolume") == 30

    def test_get_and_set_in_memory(self, isolated_settings_manager):
        """メモリ上での値の更新（set）と取得（get）が期待通り行われることを検証する"""
        settings.set("custom_key", "temporary_value")
        assert settings.get("custom_key") == "temporary_value"
