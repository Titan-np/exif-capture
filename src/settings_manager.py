import os
import sys
import json

from utils import *


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

                write_log(f"設定ファイルを読み込みました。({settings_path})")

            else:
                # ファイルが存在しない場合は新規作成する
                needs_save = True
                write_log(f"初期設定ファイルを作成します。({settings_path})")

            # 設定ファイルの更新や新規作成が必要な場合、ファイルを保存する
            if needs_save:
                self.save()

        except Exception as exception:
            # エラーが発生した場合、デフォルト設定を適用して起動を継続する
            write_log(f"設定ファイルの読み込みに失敗したため、デフォルト設定を使用します。\n{exception}")
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
            write_log(f"設定ファイルを保存しました。({settings_path})")
        except Exception as exception:
            write_log(f"設定ファイルの保存に失敗しました。\n{exception}")


# 初呼び出し時、設定ファイルを読み込む
settings = SettingsManager()
