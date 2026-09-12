import os
import sys
import json
import re

from utils import *
from notifier import notifier


class SettingsManager:
    # 設定ファイルのファイル名
    _SETTINGS_FILE_NAME = "settings.json"

    # 設定のデフォルト値
    _DEFAULT_SETTINGS = {
        "capture.triggerShortcut": "shift+print screen",
        "capture.enableSystemNotification": True,
        "capture.soundVolume": 100,
        "save.directory": r"C:\Screenshots",
        "save.filenamePreset": "{timestamp}_{title}.png",
        "save.embedDatetimeMetadata": True,
    }

    # 現キー名に対する旧キー名リスト（設定ファイル読み込み時に旧キー名があれば移行する）
    _MIGRATION_MAP = {
        "capture.triggerShortcut": ["trigger_shortcut"],
        "save.directory": ["save_directory"],
        "save.filenamePreset": ["filename_preset"],
        "save.embedDatetimeMetadata": ["embed_datetime_metadata"],
    }

    # 設定キーに対するバリデーションルール定義（キー → 検証関数名のリスト）
    _VALIDATION_RULES = {
        "capture.triggerShortcut": [
            "_validate_not_empty",
            "_validate_shortcut_format",
        ],
        "save.directory": [
            "_validate_not_empty",
            "_validate_path_chars",
        ],
        "save.filenamePreset": [
            "_validate_not_empty",
            "_validate_preset_placeholders",
            "_validate_filename_chars",
        ],
    }

    def __init__(self):
        self._data = {}
        self.load()

    def _get_settings_path(self):
        """
        設定ファイルの絶対パスを取得する
        """
        return get_app_path(self._SETTINGS_FILE_NAME)

    @property
    def settings_path(self):
        """外部から設定ファイルのパスを参照する"""
        return self._get_settings_path()

    def load(self):
        """
        設定ファイルから設定情報を読み込む
        ファイルが存在しない場合は初期設定を作成する
        """
        # 設定ファイルの絶対パスを取得
        settings_path = self._get_settings_path()

        try:
            # ベースとしてデフォルト設定をコピーする
            self._data = self._DEFAULT_SETTINGS.copy()
            needs_save = False

            # 設定ファイルが存在する場合、読み込む
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as file:
                    loaded_data = json.load(file)

                loaded_old_key = False
                loaded_unnecessary_key = False

                # デフォルト設定の全項目を基準にループして設定値を決定
                for key, default_value in self._DEFAULT_SETTINGS.items():
                    if key in loaded_data:
                        # 1. キーが設定ファイル内に存在する場合は、その値を読み込む
                        self._data[key] = loaded_data.pop(key)
                    else:
                        # 2. 旧キーが設定ファイル内に存在する場合は、現キー名として読み込む
                        old_keys = self._MIGRATION_MAP.get(key, [])
                        loaded_old_key = False
                        for old_key in old_keys:
                            if old_key in loaded_data:
                                self._data[key] = loaded_data.pop(old_key)
                                loaded_old_key = True
                                break

                        if loaded_old_key:
                            # 旧キーを読み込んだ場合、設定ファイル保存対象とする
                            needs_save = True
                        else:
                            # 3. 現キーも旧キーも存在しない場合は、デフォルト値を読み込む
                            self._data[key] = default_value
                            needs_save = True

                # 4. 設定ファイル読み込み後に設定ファイルのキーが残っていれば、不要なキーが含まれていたと判定（設定ファイル更新対象とする）
                if loaded_data:
                    needs_save = True

                notifier.log(f"設定ファイルを読み込みました。({settings_path})")

            else:
                # ファイルが存在しない場合は新規作成する
                needs_save = True
                notifier.log(f"初期設定ファイルを作成します。({settings_path})")

            # 設定ファイルの更新や新規作成が必要な場合、ファイルを保存する
            if needs_save:
                self.save()

        except Exception as exception:
            # エラーが発生した場合、デフォルト設定を適用して起動を継続する
            notifier.log(f"設定ファイルの読み込みに失敗したため、デフォルト設定を使用します。\n{exception}")
            self._data = self._DEFAULT_SETTINGS.copy()

    def get(self, key):
        """
        指定されたキーの設定値を取得する
        設定ファイルに値が存在しない場合は、_DEFAULT_SETTINGSから取得する
        """
        if key in self._data:
            return self._data[key]
        return self._DEFAULT_SETTINGS.get(key)

    def set(self, key, value):
        """
        設定値を一時的に更新する
        """
        self._data[key] = value

    def save(self):
        """
        現在の設定内容を settings.json に書き込む
        """
        settings_path = self._get_settings_path()
        try:
            with open(settings_path, "w", encoding="utf-8") as file:
                json.dump(self._data, file, indent=4, ensure_ascii=False)
            notifier.log(f"設定ファイルを保存しました。({settings_path})")
        except Exception as exception:
            notifier.log(f"設定ファイルの保存に失敗しました。\n{exception}")

    def has_validation_rule(self, key):
        """
        指定された設定キーにバリデーションルールが定義されているかを判定する
        UI側でバリデーション有無を意識せずに自動制御できるようにするために使用する

        Args:
            key (str): 設定キー

        Returns:
            bool: バリデーションルールが存在する場合は True、なければ False
        """
        return key in self._VALIDATION_RULES and bool(self._VALIDATION_RULES[key])

    def validate(self, key, value):
        """
        指定された設定キーに対して定義されているバリデーションルールを順次実行する

        Args:
            key (str): 設定キー
            value: 検証する値

        Returns:
            str | None: 最初に発生したエラーメッセージ（問題なければ None）
        """
        for method_name in self._VALIDATION_RULES.get(key, []):
            method = getattr(self, method_name)
            error = method(value)
            if error:
                return error
        return None

    def validate_all(self, data):
        """
        全設定項目のバリデーションを一括実行する

        Args:
            data (dict): {設定キー: 値} の辞書

        Returns:
            dict: {設定キー: エラーメッセージ} の辞書（エラーがある項目のみ）
        """
        errors = {}
        for key, value in data.items():
            error = self.validate(key, value)
            if error:
                errors[key] = error
        return errors

    def _validate_not_empty(self, value):
        """
        設定値が未入力（空文字または空白のみ）でないかを検証する

        Args:
            value: 検証する値

        Returns:
            str | None: エラーメッセージ（未入力の場合はメッセージ、問題なければ None）
        """
        if value is None or not str(value).strip():
            return "必須項目です。"
        return None

    def _validate_path_chars(self, value):
        """
        フォルダパス文字列にWindowsで使用できない不正文字が含まれていないかを検証する

        Args:
            value: 検証する値

        Returns:
            str | None: エラーメッセージ（不正文字が含まれる場合はメッセージ、問題なければ None）
        """
        path_string = str(value).strip()

        # パス全体で使用できない禁止文字（< > " | ? *）をチェック
        for char in path_string:
            if char in '<>"|?*':
                return f"フォルダパスに使用できない文字が含まれています: {char}"

        # ドライブレターコロン（例: 'C:\' のコロン）以外の不正なコロンをチェック
        drive, rest_path = os.path.splitdrive(path_string)
        if ":" in rest_path:
            return "フォルダパスに使用できない文字が含まれています: :"

        # ドライブレターの形式チェック（1文字の英字 + コロン以外ならエラー）
        if drive and (len(drive) != 2 or not drive[0].isalpha() or drive[1] != ":"):
            return f"ドライブ指定が不正です: {drive}"

        return None

    def _validate_filename_chars(self, value):
        """
        ファイル名（プレースホルダ部分を除く固定文字列）にWindowsで使用できない禁止文字が含まれていないかを検証する

        Args:
            value: 検証する値

        Returns:
            str | None: エラーメッセージ（禁止文字が含まれる場合はメッセージ、問題なければ None）
        """
        preset_string = str(value).strip()

        # 波括弧部分（{...}）を除去した固定文字列を取得
        fixed_text = re.sub(r"\{[^{}]*\}", "", preset_string)

        # Windowsのファイル名で使用できない禁止文字をチェック
        for char in fixed_text:
            if char in '<>:"/\\|?*':
                return f"ファイル名に使用できない文字が含まれています: {char}"

        return None

    def _validate_shortcut_format(self, value):
        """
        ショートカットキー文字列が有効なキーの組み合わせかを検証する

        Args:
            value: 検証する値

        Returns:
            str | None: エラーメッセージ（無効な形式の場合はメッセージ、問題なければ None）
        """
        # 循環インポートを防ぐため関数内でインポート
        from hotkey_manager import HotkeyManager

        if not HotkeyManager.is_valid_shortcut(str(value)):
            return "有効なショートカットキーを入力してください。"
        return None

    def _validate_preset_placeholders(self, value):
        """
        ファイル名プリセットの波括弧書式とプレースホルダを検証する
        capture.py で実際に置換される timestamp と title 以外のキーや構文エラーを検出する

        Args:
            value: 検証する値

        Returns:
            str | None: エラーメッセージ（書式が不正な場合はメッセージ、問題なければ None）
        """
        from datetime import datetime

        preset_string = str(value).strip()

        try:
            # ダミー値を渡してフォーマットを試行
            preset_string.format(timestamp=datetime.now(), title="TestTitle")
        except KeyError as exception:
            # 許可されていないプレースホルダ名
            return f"使用できないプレースホルダです: {{{exception.args[0]}}}"
        except (ValueError, IndexError):
            # 波括弧の対応ミスや不正な書式指定子
            return "書式が不正です。波括弧 { } の対応を確認してください。"

        return None


# 初呼び出し時、設定ファイルを読み込む
settings = SettingsManager()
