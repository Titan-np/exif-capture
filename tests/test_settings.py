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
        assert "必須項目です" in empty_result.message

        # 空白のみの文字列の検証
        whitespace_result = settings._validate_not_empty("   ")
        assert whitespace_result is not None
        assert "必須項目です" in whitespace_result.message

        # None の検証
        none_result = settings._validate_not_empty(None)
        assert none_result is not None
        assert "必須項目です" in none_result.message

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
            assert "フォルダパスに使用できない文字が含まれています" in validation_error.message

    def test_validate_path_chars_rejects_invalid_colon(self):
        """ドライブレター以外にコロンが含まれている場合に拒否されることを検証する"""
        invalid_path = "C:\\Screenshots:extra\\folder"
        validation_error = settings._validate_path_chars(invalid_path)
        assert validation_error is not None
        assert "フォルダパスに使用できない文字が含まれています: :" in validation_error.message

    def test_validate_path_chars_rejects_invalid_drive_format(self):
        """不正なドライブ名（英字以外など）が指定された場合に拒否されることを検証する"""
        invalid_drive_path = "1:\\Screenshots"
        validation_error = settings._validate_path_chars(invalid_drive_path)
        assert validation_error is not None
        assert "ドライブ指定が不正です" in validation_error.message

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

    def test_validate_path_chars_accepts_unc_path(self):
        """サーバー名と共有名がそろったUNCパス（ネットワーク共有）が承認されることを検証する"""
        assert settings._validate_path_chars("\\\\server\\share") is None
        assert settings._validate_path_chars("\\\\server\\share\\Screenshots") is None

    def test_validate_path_chars_rejects_incomplete_unc_path(self):
        """共有名が無い、または共有名にコロンを含むUNCパスが拒否されることを検証する"""
        invalid_unc_path_list = [
            "\\\\server",
            "\\\\server\\",
            "\\\\server\\share:x",
        ]
        for invalid_unc_path in invalid_unc_path_list:
            validation_error = settings._validate_path_chars(invalid_unc_path)
            assert validation_error is not None, invalid_unc_path
            assert "ネットワークパスの指定が不正です" in validation_error.message

    def test_validate_filename_chars_rejects_forbidden_chars(self):
        """ファイル名として使用できない禁止文字が固定文字列に含まれる場合に拒否されることを検証する"""
        # Windowsファイル名の禁止文字
        forbidden_filename_character_list = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
        for character in forbidden_filename_character_list:
            test_preset = f"shot_{character}_{{timestamp}}.png"
            validation_error = settings._validate_filename_chars(test_preset)
            assert validation_error is not None
            assert "ファイル名に使用できない文字が含まれています" in validation_error.message

    def test_validate_filename_chars_ignores_placeholder_brackets(self):
        """プレースホルダ内部の書式指定子に含まれる記号（コロンなど）が誤検知されないことを検証する"""
        # プレースホルダ内にコロンなどの記号が含まれていても固定文字列側でなければ許容
        safe_preset = "{timestamp:%Y%m%d_%H%M%S}_{title}.png"
        validation_error = settings._validate_filename_chars(safe_preset)
        assert validation_error is None

    def test_validate_filename_chars_rejects_forbidden_chars_in_placeholder_output(self):
        """書式指定の展開結果に禁止文字が含まれる場合に拒否されることを検証する"""
        # {timestamp} の書式の「:」「/」、{dup} のテンプレートの「/」は展開後のファイル名に現れる
        forbidden_output_preset_list = [
            "{timestamp:%H:%M}.png",
            "{timestamp:%Y/%m}.png",
            "{title}{dup:/%d}.png",
        ]
        for forbidden_output_preset in forbidden_output_preset_list:
            validation_error = settings._validate_filename_chars(forbidden_output_preset)
            assert validation_error is not None
            assert "ファイル名に使用できない文字が含まれています" in validation_error.message

    def test_validate_shortcut_format_delegates_to_hotkey_manager(self):
        """ショートカットキー検証が lib.hotkey と連動して正常・異常を判定することを検証する"""
        # 有効なショートカット
        assert settings._validate_shortcut_format("shift+print screen") is None
        assert settings._validate_shortcut_format("ctrl+alt+s") is None

        # 無効なショートカット（空文字・末尾プラスなど）
        assert settings._validate_shortcut_format("") is not None
        assert settings._validate_shortcut_format("ctrl+") is not None

    def test_validate_warns_shortcut_conflicting_with_typing(self):
        """文字入力と衝突するショートカットキーで、保存可能な警告が返ることを検証する"""
        validation_result = settings.validate("capture.triggerShortcut", "a")
        assert validation_result.level == settings.ValidationLevel.WARNING

        # デフォルトのショートカットキーでは警告しない
        assert settings.validate("capture.triggerShortcut", settings._DEFAULT_SETTINGS["capture.triggerShortcut"]) is None

    def test_validate_warns_shortcut_conflicting_with_standard_shortcut(self):
        """他のアプリの標準的なショートカット（Ctrl+C など）で、保存可能な警告が返ることを検証する"""
        validation_result = settings.validate("capture.triggerShortcut", "ctrl+c")
        assert validation_result.level == settings.ValidationLevel.WARNING
        assert "他のアプリのショートカット" in validation_result.message

    def test_validate_preset_placeholders_accepts_allowed_keys(self):
        """許可されているプレースホルダ（timestamp, title, index, dup）が承認されることを検証する"""
        valid_preset_list = [
            "{timestamp}_{title}.png",
            "{timestamp:%Y-%m-%d}_{title}.png",
            "capture_{title}.png",
            "screenshot_{timestamp}.png",
            "shot_{index:03}.png",
            "{title}{dup}.png",
            "{title}{dup:_%02d:1}.png",
        ]
        for valid_preset in valid_preset_list:
            validation_error = settings._validate_preset_placeholders(valid_preset)
            assert validation_error is None

    def test_validate_preset_placeholders_rejects_unknown_keys(self):
        """未定義のプレースホルダキーが指定された場合に拒否されることを検証する"""
        unknown_key_preset = "{unknown_key}_{title}.png"
        validation_error = settings._validate_preset_placeholders(unknown_key_preset)
        assert validation_error is not None
        assert "使用できないプレースホルダです: {unknown_key}" in validation_error.message

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
            assert "書式が不正です" in validation_error.message or "使用できないプレースホルダ" in validation_error.message

    def test_validate_preset_placeholders_rejects_invalid_duplicate_format(self):
        """{dup} のテンプレートに番号の変換指定が無い場合や、開始番号が整数でない場合に拒否されることを検証する"""
        invalid_preset_list = [
            "{title}{dup:_copy}.png",
            "{title}{dup:_%d:one}.png",
        ]
        for invalid_preset in invalid_preset_list:
            validation_error = settings._validate_preset_placeholders(invalid_preset)
            assert validation_error is not None
            assert "書式が不正です" in validation_error.message

    def test_validate_overwrite_risk_warns_without_unique_placeholder(self):
        """{index} / {dup} / %f 付き {timestamp} のいずれも無いプリセットで警告が返ることを検証する"""
        risky_preset_list = [
            "{timestamp}_{title}.png",
            "{timestamp:%Y%m%d_%H%M%S}_{title}.png",
            "index_dup_%f.png",  # 固定文字列中の語や記号は対象外
        ]
        for risky_preset in risky_preset_list:
            validation_result = settings._validate_overwrite_risk(risky_preset)
            assert validation_result.level == settings.ValidationLevel.WARNING

    def test_validate_overwrite_risk_accepts_unique_placeholder(self):
        """{index} / {dup} / %f 付き {timestamp} のいずれかがあるプリセットでは警告しないことを検証する"""
        safe_preset_list = [
            "{timestamp}_{title}{dup}.png",
            "{title}_{index:03}.png",
            "{timestamp:%Y%m%d_%H%M%S_%f}_{title}.png",
        ]
        for safe_preset in safe_preset_list:
            assert settings._validate_overwrite_risk(safe_preset) is None

    def test_default_preset_has_no_validation_result(self):
        """デフォルトのファイル名プリセットでエラー・警告が出ないことを検証する"""
        assert settings.validate("save.filenamePreset", settings._DEFAULT_SETTINGS["save.filenamePreset"]) is None

    def test_validate_all_returns_errors_for_invalid_entries(self):
        """複数の設定項目に対して一括検証を実行し、エラー項目のみ辞書として返却されることを検証する"""
        test_settings_data = {
            "capture.triggerShortcut": "",  # 空文字のためエラー
            "save.directory": "C:\\Screenshots",  # 正常
            "save.filenamePreset": "test<{title}>.png",  # 禁止文字を含むためエラー
        }
        validation_results = settings.validate_all(test_settings_data)

        assert validation_results["capture.triggerShortcut"].is_error
        assert validation_results["save.filenamePreset"].is_error
        assert "save.directory" not in validation_results

    def test_validate_prefers_error_over_preceding_warning(self, monkeypatch):
        """先のルールが警告を返しても、後のルールのエラーが優先して返ることを検証する"""
        monkeypatch.setattr(settings, "_VALIDATION_RULES", {"test.key": ["_validate_dummy_warning", "_validate_dummy_error"]})
        monkeypatch.setattr(settings, "_validate_dummy_warning", lambda value: settings.ValidationResult.warning("警告"), raising=False)
        monkeypatch.setattr(settings, "_validate_dummy_error", lambda value: settings.ValidationResult.error("エラー"), raising=False)

        validation_result = settings.validate("test.key", "value")

        assert validation_result.is_error
        assert validation_result.message == "エラー"

    def test_validate_type_rejects_mismatched_type(self):
        """設定値の型がデフォルト値の型と異なる場合に、後続のルールより先にエラーが返ることを検証する"""
        # (設定キー, 型の異なる値) の組（bool は int の派生型だが、整数項目では拒否する）
        mismatched_value_list = [
            ("capture.soundVolume", "50"),
            ("capture.soundVolume", True),
            ("capture.soundVolume", 50.0),
            ("notify.onCapture", "false"),
            ("notify.onCapture", 0),
            ("capture.triggerShortcut", 5),
            ("save.directory", 1),
        ]
        for key, value in mismatched_value_list:
            validation_result = settings.validate(key, value)
            assert validation_result is not None and validation_result.is_error

        # 型が一致する場合はエラーにならない
        assert settings.validate("capture.soundVolume", 50) is None
        assert settings.validate("notify.onCapture", False) is None

    def test_can_fail_input_validation_ignores_file_only_rules(self):
        """設定ファイルの手編集でのみ失敗しうるルール（型チェック・選択肢の確認）だけの項目は False、それ以外の検証ルールがある項目は True が返ることを検証する"""
        assert settings.can_fail_input_validation("capture.soundVolume") is False
        assert settings.can_fail_input_validation("notify.onCapture") is False
        assert settings.can_fail_input_validation("update.checkMode") is False
        assert settings.can_fail_input_validation("save.directory") is True
        assert settings.can_fail_input_validation("unknown.key") is False


class TestOutputPathLength:
    """
    保存先フォルダとファイル名プリセットの組み合わせによるパス長の検証に関するテストクラス
    プリセット "{title}{dup}.png" の場合、最短フルパスは "C:\\" + フォルダ名 + "\\.png" でフォルダ名の長さ + 8 文字になる
    上書き警告がパス長の検証結果に混ざらないよう、プリセットには {dup} を含める
    """

    @staticmethod
    def _build_settings_data(directory_name_length, filename_preset="{title}{dup}.png"):
        """指定した長さのフォルダ名を持つ保存先フォルダとプリセットの辞書を生成する"""
        return {
            "save.directory": "C:\\" + "a" * directory_name_length,
            "save.filenamePreset": filename_preset,
        }

    def test_validate_all_warns_path_exceeding_max_length(self):
        """{title} が空でも最短フルパスが260文字になる場合にプリセット側へ警告が返ることを検証する"""
        validation_results = settings.validate_all(self._build_settings_data(252))

        assert validation_results["save.filenamePreset"].level == settings.ValidationLevel.WARNING
        assert "最大長" in validation_results["save.filenamePreset"].message
        assert "save.directory" not in validation_results

    def test_validate_all_accepts_path_within_max_length(self):
        """最短フルパスがちょうど259文字の場合はエラーにならない（残り0文字の警告になる）ことを検証する"""
        validation_results = settings.validate_all(self._build_settings_data(251))
        assert validation_results["save.filenamePreset"].level == settings.ValidationLevel.WARNING

    def test_validate_all_uses_expanded_directory_length(self, monkeypatch):
        """環境変数を含むフォルダは展開後の長さで判定されることを検証する"""
        monkeypatch.setenv("TEST_LONG_DIRECTORY", "C:\\" + "a" * 252)
        validation_results = settings.validate_all({"save.directory": "%TEST_LONG_DIRECTORY%", "save.filenamePreset": "{title}.png"})

        assert "最大長" in validation_results["save.filenamePreset"].message

    def test_validate_all_skips_path_length_check_on_format_error(self):
        """プリセットに書式エラーがある場合はパス長ではなく書式のエラーが返ることを検証する"""
        validation_results = settings.validate_all(self._build_settings_data(252, filename_preset="{invalid_key}.png"))
        assert "使用できないプレースホルダ" in validation_results["save.filenamePreset"].message

    def test_warning_when_title_margin_below_threshold(self):
        """タイトルに使える残り文字数が閾値未満（閾値 - 1 文字）の場合に警告が返ることを検証する"""
        # 閾値を変更してもテストを直さずに済むよう、閾値から残り文字数とフォルダ名の長さを求める（最短フルパスはフォルダ名の長さ + 8 文字）
        title_margin = settings._TITLE_LENGTH_WARNING_THRESHOLD - 1
        validation_results = settings.validate_all(self._build_settings_data(251 - title_margin))

        assert validation_results["save.filenamePreset"].level == settings.ValidationLevel.WARNING
        assert f"残り文字数は{title_margin}文字" in validation_results["save.filenamePreset"].message

    def test_no_warning_when_title_margin_at_threshold(self):
        """タイトルに使える残り文字数が閾値ちょうどの場合は警告しないことを検証する"""
        title_margin = settings._TITLE_LENGTH_WARNING_THRESHOLD
        assert settings.validate_all(self._build_settings_data(251 - title_margin)) == {}

    def test_no_warning_when_preset_has_no_title(self):
        """プリセットに {title} が無い場合は残り文字数が少なくても警告しないことを検証する"""
        assert settings.validate_all(self._build_settings_data(240, filename_preset="fixed{dup}.png")) == {}


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
            "capture.soundVolume": 50,
            "save.directory": "D:\\CustomScreenshots",
            "save.filenamePreset": "custom_{timestamp}.png",
            "save.embedDatetimeMetadata": False,
            "notify.onCapture": False,
            "notify.onAppEvent": True,
            "notify.onError": False,
            "update.checkMode": "prerelease",
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
        assert settings.get("notify.onCapture") is False
        assert settings.get("notify.onAppEvent") is True
        assert settings.get("notify.onError") is False
        assert settings.get("update.checkMode") == "prerelease"

    def test_load_migrates_old_key_names(self, isolated_settings_manager):
        """旧バージョンのキー名が設定ファイルに含まれている場合、新キー名へ自動移行されることを検証する"""
        legacy_settings = {
            "trigger_shortcut": "ctrl+alt+a",
            "save_directory": "D:\\LegacyDirectory",
            "filename_preset": "{title}_{timestamp}.png",
            "embed_datetime_metadata": False,
            "notify.updateCheck": "prerelease",
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
        assert settings.get("update.checkMode") == "prerelease"

        # ファイルへ保存され、旧キーが除去されていることを確認
        with open(settings._get_settings_path(), "r", encoding="utf-8") as file:
            migrated_content = json.load(file)
            assert "trigger_shortcut" not in migrated_content
            assert "capture.triggerShortcut" in migrated_content
            assert "notify.updateCheck" not in migrated_content

    def test_load_splits_old_notification_key_into_categories(self, isolated_settings_manager):
        """旧キー capture.enableSystemNotification の値が、種別ごとの通知設定3項目すべてへ引き継がれることを検証する"""
        legacy_settings = {
            "capture.triggerShortcut": "ctrl+alt+a",
            "capture.enableSystemNotification": False,
        }

        # 旧形式の設定ファイルを作成
        with open(settings._get_settings_path(), "w", encoding="utf-8") as file:
            json.dump(legacy_settings, file, indent=4)

        # 読み込みを実行（マイグレーションが自動実行される）
        settings.load()

        # 1つの旧キーの値が、分割先の3項目すべてに引き継がれていることを確認
        assert settings.get("notify.onCapture") is False
        assert settings.get("notify.onAppEvent") is False
        assert settings.get("notify.onError") is False

        # ファイルへ保存され、旧キーが除去されていることを確認
        with open(settings._get_settings_path(), "r", encoding="utf-8") as file:
            migrated_content = json.load(file)
            assert "capture.enableSystemNotification" not in migrated_content
            assert migrated_content["notify.onCapture"] is False

    def test_load_removes_old_key_when_new_key_exists(self, isolated_settings_manager):
        """現キーと旧キーが両方存在する場合、現キーの値を優先し、旧キーはファイルから除去されることを検証する"""
        mixed_settings = {
            "notify.onCapture": True,
            "capture.enableSystemNotification": False,
        }

        # 現キーと旧キーが混在した設定ファイルを作成
        with open(settings._get_settings_path(), "w", encoding="utf-8") as file:
            json.dump(mixed_settings, file, indent=4)

        settings.load()

        # 現キーがある項目は現キーの値、無い項目は旧キーの値になっていることを確認
        assert settings.get("notify.onCapture") is True
        assert settings.get("notify.onAppEvent") is False

        # 旧キーがファイルから除去されていることを確認
        with open(settings._get_settings_path(), "r", encoding="utf-8") as file:
            assert "capture.enableSystemNotification" not in json.load(file)

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

    def test_load_replaces_mismatched_type_with_default(self, isolated_settings_manager):
        """型の異なる設定値がデフォルト値へ差し替えられ、元の設定ファイルが退避されることを検証する"""
        mismatched_type_settings = {
            "capture.soundVolume": "50",  # 整数項目に文字列
            "notify.onCapture": "false",  # 真偽値項目に文字列
        }

        with open(settings._get_settings_path(), "w", encoding="utf-8") as file:
            json.dump(mismatched_type_settings, file, indent=4)

        settings.load()

        # 両項目ともデフォルト値に差し替えられていることを確認
        assert settings.get("capture.soundVolume") == settings._DEFAULT_SETTINGS["capture.soundVolume"]
        assert settings.get("notify.onCapture") is settings._DEFAULT_SETTINGS["notify.onCapture"]

        # 元の設定ファイルが退避されていることを確認
        backup_files = [filename for filename in os.listdir(os.path.dirname(settings._get_settings_path())) if "settings.json.corrupted_" in filename]
        assert len(backup_files) == 1

    def test_load_keeps_preset_when_path_exceeds_max_length(self, isolated_settings_manager):
        """フォルダとプリセットの組み合わせで最大パス長を超えても、両項目が維持され元ファイルが退避されないことを検証する"""
        long_directory = "C:\\" + "a" * 252
        too_long_settings = {
            "save.directory": long_directory,
            "save.filenamePreset": "{title}.png",
        }

        with open(settings._get_settings_path(), "w", encoding="utf-8") as file:
            json.dump(too_long_settings, file, indent=4)

        settings.load()

        # フォルダ・プリセットともに読み込んだ値が維持されることを確認
        assert settings.get("save.directory") == long_directory
        assert settings.get("save.filenamePreset") == "{title}.png"

        # 設定ファイルが退避されていないことを確認
        backup_files = [filename for filename in os.listdir(os.path.dirname(settings._get_settings_path())) if "settings.json.corrupted_" in filename]
        assert len(backup_files) == 0

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
