import os
import sys
import json
import re
import shutil
from datetime import datetime

from utils import *
from notifier import notifier, NotificationButton


class SettingsManager:
    # 設定ファイルのファイル名
    _SETTINGS_FILE_NAME = "settings.json"
    # 一時設定ファイルのファイル名（破損防止保存用）
    _SETTINGS_TEMPORARY_NAME = "settings.json.tmp"

    # 設定のデフォルト値
    _DEFAULT_SETTINGS = {
        "capture.triggerShortcut": "shift+print screen",
        "capture.enableSystemNotification": True,
        "capture.soundVolume": 100,
        "save.directory": "~\\Pictures\\Screenshots",
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
        # コンストラクタで load() を行うと循環参照が発生するため、インスタンス生成後に明示的に load() を呼び出す運用とする
        # 詳細は本ファイル最下部のコメントを参照
        # self.load()

    @property
    def _settings_path(self):
        """
        設定ファイルの絶対パスを取得する
        """
        return get_app_path(self._SETTINGS_FILE_NAME)

    @property
    def _temporary_settings_path(self):
        """
        一時設定ファイルの絶対パスを取得する
        """
        return get_app_path(self._SETTINGS_TEMPORARY_NAME)

    def _backup_corrupted_file(self):
        """
        現在の設定ファイルを日時付きファイル名で退避（バックアップ）する

        Returns:
            str | None: 退避先のファイル名（失敗時やファイル不在時は None）
        """
        if not os.path.exists(self._settings_path):
            return None

        corrupted_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupted_filename = f"{self._SETTINGS_FILE_NAME}.corrupted_{corrupted_timestamp}"
        corrupted_path = get_app_path(corrupted_filename)

        try:
            shutil.copy2(self._settings_path, corrupted_path)
            notifier.log(f"読み込みに失敗した設定ファイルを退避しました: {corrupted_path}")
            return corrupted_filename
        except OSError as exception:
            notifier.log(f"設定ファイルの退避に失敗しました。\n{exception}")
            return None

    def load(self):
        """
        設定ファイルから設定情報を読み込む
        ファイルが存在しない場合は設定ファイルを新規作成する
        ファイル破損時や一部項目の値が不正な場合は退避して通知し、初期設定を適用する
        """
        # 1. 設定ファイルが存在しない場合は設定ファイルを新規作成する
        if not os.path.exists(self._settings_path):
            self._data = self._DEFAULT_SETTINGS.copy()
            notifier.log(f"設定ファイルを新規作成します。({self._settings_path})")
            self.save()
            return

        # 2. 設定ファイルを読み込む
        try:
            with open(self._settings_path, "r", encoding="utf-8") as file:
                loaded_data = json.load(file)

        except Exception as exception:
            # 2-1. JSON構文エラーなど設定ファイル全体が壊れていた場合、上書き前に設定ファイルを退避する
            corrupted_filename = self._backup_corrupted_file()
            message = f"元の設定ファイルを「{corrupted_filename}」に退避し、デフォルト設定を適用しました。"

            notifier.notify(
                title="設定ファイルの読み込みに失敗しました。",
                message=f"{message}\n詳細はログファイルを参照してください。",
                log_message=f"{message}\n{exception}",
                buttons=[NotificationButton.OPEN_SETTINGS, NotificationButton.OPEN_LOG],
            )

            # 2-2. デフォルト設定を適用し、新規設定ファイルとして保存する
            self._data = self._DEFAULT_SETTINGS.copy()
            self.save()
            return

        # 3. 設定項目読み込みのベースとして、デフォルト設定をコピー
        self._data = self._DEFAULT_SETTINGS.copy()
        needs_save = False
        invalid_keys = {}  # バリデーションエラー情報: {key: (raw_value, error_message)}

        # 4. デフォルト設定にある設定項目ごとに設定値を取得
        for key, default_value in self._DEFAULT_SETTINGS.items():
            loaded_value = None

            # 4-1. 現キー名の設定値が存在する場合は、読み込む
            if key in loaded_data:
                loaded_value = loaded_data.pop(key)
            else:
                # 4-2. 旧キー名の設定値が存在する場合は、現キーの値として読み込み、上書き保存対象とする
                for old_key in self._MIGRATION_MAP.get(key, []):
                    if old_key in loaded_data:
                        loaded_value = loaded_data.pop(old_key)
                        needs_save = True
                        break

            # 5. 設定値を読み込めた場合、バリデーションを実行し正常値であれば使用
            if loaded_value is not None:
                validation_error = self.validate(key, loaded_value)
                # 5-1. エラーが無ければ正常値として採用
                if validation_error is None:
                    self._data[key] = loaded_value
                # 5-2. エラーがあればデフォルト値を使用し、設定ファイルを退避・保存対象とする
                else:
                    self._data[key] = default_value
                    invalid_keys[key] = (loaded_value, validation_error)
                    needs_save = True

            # 6. 設定ファイル内に現キー名・旧キー名ともに存在しない場合、デフォルト値を使用し、設定ファイルを保存対象とする
            else:
                self._data[key] = default_value
                needs_save = True

        notifier.log(f"設定ファイルを読み込みました。({self._settings_path})")

        # 7. 設定ファイル読み込み後に未知のキーが残っていれば、不要なキーが含まれていたと判定し、設定ファイルを保存対象とする
        if loaded_data:
            needs_save = True

        # 8. 設定ファイル内に壊れている設定値が含まれていた場合、上書き前に設定ファイルを退避する
        if invalid_keys:
            corrupted_filename = self._backup_corrupted_file()
            message = f"元の設定ファイルを「{corrupted_filename}」に退避し、デフォルト設定を適用しました。"
            log_details = "\n".join([f"キー '{key}' の値 ({item[0]!r}) が不正です: {item[1]}" for key, item in invalid_keys.items()])

            notifier.notify(
                title="設定ファイルの読み込みに失敗しました。",
                message=f"{message}\n詳細はログファイルを参照してください。",
                log_message=f"{message}\n{log_details}",
                buttons=[NotificationButton.OPEN_SETTINGS, NotificationButton.OPEN_LOG],
            )

        # 9. 設定ファイルの更新が必要な場合、ファイルを保存する
        if needs_save:
            self.save()

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
        現在の設定内容をsettings.json に書き込む（破損防止保存）
        """

        try:
            # 1. 一時ファイルに書き出し、ディスクへ確実にフラッシュする
            with open(self._temporary_settings_path, "w", encoding="utf-8") as file:
                # JSONとして書き込む
                json.dump(self._data, file, indent=4, ensure_ascii=False)
                # 書き込んだデータをPythonからOSのキャッシュへ強制的に流す
                file.flush()
                # OSのキャッシュをディスクへ強制的に書き込む
                os.fsync(file.fileno())

            # 2. 一時ファイルを本来の設定ファイルパスへ安全に置き換える
            os.replace(self._temporary_settings_path, self._settings_path)
            notifier.log(f"設定ファイルを保存しました。({self._settings_path})")

        except Exception as exception:
            notifier.log(f"設定ファイルの保存に失敗しました。\n{exception}")
            # 保存に失敗した一時ファイルが残っていれば削除する
            if os.path.exists(self._temporary_settings_path):
                try:
                    os.remove(self._temporary_settings_path)
                except OSError:
                    pass

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

        # チルダ（~）や環境変数を展開して検証対象の絶対パスを取得
        expanded_path = expand_path(path_string)

        # パス全体で使用できない禁止文字（< > " | ? *）をチェック
        for char in expanded_path:
            if char in '<>"|?*':
                return f"フォルダパスに使用できない文字が含まれています: {char}"

        # ドライブレターコロン（例: 'C:\' のコロン）以外の不正なコロンをチェック
        drive, rest_path = os.path.splitdrive(expanded_path)
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


# __init__()内で self.load() を呼び出さない理由:
# __init__()内に self.load() があると、以下の問題が発生する。
# 1. まず右辺の SettingsManager() を作ろうとして、__init__() の中身を上から順に実行する。
# 2. __init__() の中で self.load() が実行される。
# 3. load() の最中に設定エラーが起きると、notifier.notify() が呼ばれる。
# 4. notifier は通知設定を見るために「from settings_manager import settings（変数 settings の参照）」を要求する。
# 5. だがPythonから見ると、「今まさに右辺の SettingsManager() を作っている最中のため、左辺の settings という変数はまだ存在していない」 という状態。
# 6. その結果、「未完成のモジュールから settings は読み込めない」と ImportError（循環インポートエラー）が発生してしまう。
#
# 上記より、settings 変数へのインスタンス代入を完了させてから load() を呼び出す。
settings = SettingsManager()
settings.load()
