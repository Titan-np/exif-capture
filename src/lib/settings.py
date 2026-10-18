import json
import os
import re
import shutil
import string
from datetime import datetime
from enum import StrEnum
from typing import NamedTuple

import lib.constants as constants
import lib.filename_preset as filename_preset
import lib.notifier as notifier
import lib.paths as paths

# 設定ファイルのファイル名
_SETTINGS_FILE_NAME = "settings.json"
# 一時設定ファイルのファイル名（破損防止保存用）
_SETTINGS_TEMPORARY_NAME = "settings.json.tmp"

# 設定のデフォルト値
_DEFAULT_SETTINGS = {
    "capture.triggerShortcut": "shift+print screen",
    "capture.soundVolume": 100,
    "save.directory": "~\\Pictures\\Screenshots",
    "save.filenamePreset": "{timestamp}_{title}{dup}.png",
    "save.embedDatetimeMetadata": True,
    "notify.onCapture": True,
    "notify.onAppEvent": True,
    "notify.onError": True,
    "notify.updateCheck": "stable",
}

# 現キー名に対する旧キー名リスト（設定ファイル読み込み時に旧キー名があれば移行する）
_MIGRATION_MAP = {
    "capture.triggerShortcut": ["trigger_shortcut"],
    "save.directory": ["save_directory"],
    "save.filenamePreset": ["filename_preset"],
    "save.embedDatetimeMetadata": ["embed_datetime_metadata"],
    "notify.onCapture": ["capture.enableSystemNotification"],
    "notify.onAppEvent": ["capture.enableSystemNotification"],
    "notify.onError": ["capture.enableSystemNotification"],
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
        "_validate_overwrite_risk",
    ],
    "notify.updateCheck": [
        "_validate_update_check_mode",
    ],
}

# 旧デフォルトのファイル名プリセット（この値のままの設定は、上書きを防ぐ現デフォルトへ自動移行する）
# {dup} は重複時のみ展開されるため、移行しても普段のファイル名は変わらない
_LEGACY_DEFAULT_FILENAME_PRESET = "{timestamp}_{title}.png"

# ファイル名の {title} に使える残り文字数がこの値未満の場合に警告する
_TITLE_LENGTH_WARNING_THRESHOLD = 30

# メモリ上の設定データ
_data = {}


class ValidationLevel(StrEnum):
    """バリデーション結果の区分。エラーは保存不可、警告は保存可能だが注意が必要"""

    ERROR = "error"
    WARNING = "warning"


class ValidationResult(NamedTuple):
    """バリデーション結果（区分とメッセージの組）"""

    level: ValidationLevel  # 結果の区分
    message: str  # 入力欄の下に表示するメッセージ

    @classmethod
    def error(cls, message):
        """区分がエラーの結果を生成する"""
        return cls(ValidationLevel.ERROR, message)

    @classmethod
    def warning(cls, message):
        """区分が警告の結果を生成する"""
        return cls(ValidationLevel.WARNING, message)

    @property
    def is_error(self):
        """区分がエラー（保存不可）かを判定する"""
        return self.level is ValidationLevel.ERROR


def _get_settings_path():
    """
    設定ファイルの絶対パスを取得する
    """
    return paths.get_app_path(_SETTINGS_FILE_NAME)


def _get_temporary_settings_path():
    """
    一時設定ファイルの絶対パスを取得する
    """
    return paths.get_app_path(_SETTINGS_TEMPORARY_NAME)


def _backup_corrupted_file():
    """
    現在の設定ファイルを日時付きファイル名で退避（バックアップ）する

    Returns:
        str | None: 退避先のファイル名（失敗時やファイル不在時は None）
    """
    settings_file_path = _get_settings_path()
    if not os.path.exists(settings_file_path):
        return None

    corrupted_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    corrupted_filename = f"{_SETTINGS_FILE_NAME}.corrupted_{corrupted_timestamp}"
    corrupted_path = paths.get_app_path(corrupted_filename)

    try:
        shutil.copy2(settings_file_path, corrupted_path)
        notifier.log(f"読み込みに失敗した設定ファイルを退避しました: {corrupted_path}")
        return corrupted_filename
    except OSError as exception:
        notifier.log(f"設定ファイルの退避に失敗しました。\n{exception}")
        return None


def load():
    """
    設定ファイルから設定情報を読み込む
    ファイルが存在しない場合は設定ファイルを新規作成する
    ファイル破損時や一部項目の値が不正な場合は退避して通知し、初期設定を適用する
    """
    global _data
    settings_file_path = _get_settings_path()

    # 1. 設定ファイルが存在しない場合は設定ファイルを新規作成する
    if not os.path.exists(settings_file_path):
        _data.clear()
        _data.update(_DEFAULT_SETTINGS)
        notifier.log(f"設定ファイルを新規作成します。({settings_file_path})")
        save()
        return

    # 2. 設定ファイルを読み込む
    try:
        with open(settings_file_path, "r", encoding="utf-8") as file:
            loaded_data = json.load(file)

    except Exception as exception:
        # 2-1. JSON構文エラーなど設定ファイル全体が壊れていた場合、上書き前に設定ファイルを退避する
        corrupted_filename = _backup_corrupted_file()
        message = f"元の設定ファイルを「{corrupted_filename}」に退避し、デフォルト設定を適用しました。"

        notifier.notify(
            title="設定ファイルの読み込みに失敗しました。",
            message=f"{message}\n詳細はログファイルを参照してください。",
            log_message=f"{message}\n{exception}",
            buttons=[notifier.NotificationButton.OPEN_SETTINGS, notifier.NotificationButton.OPEN_LOG],
            category=notifier.NotificationCategory.ERROR,
        )

        # 2-2. デフォルト設定を適用し、新規設定ファイルとして保存する
        _data.clear()
        _data.update(_DEFAULT_SETTINGS)
        save()
        return

    # 3. 設定項目読み込みのベースとして、デフォルト設定をコピー
    new_data = _DEFAULT_SETTINGS.copy()
    needs_save = False
    invalid_keys = {}  # バリデーションエラー情報: {key: (raw_value, error_message)}

    # 4. デフォルト設定にある設定項目ごとに設定値を取得
    for key, default_value in _DEFAULT_SETTINGS.items():
        loaded_value = None

        # 4-1. 現キー名の設定値が存在する場合は、読み込む
        if key in loaded_data:
            loaded_value = loaded_data.pop(key)
        else:
            # 4-2. 旧キー名の設定値が存在する場合は、現キーの値として読み込み、上書き保存対象とする
            # 1つの旧キーを複数の現キーへ引き継げるよう、ここでは取り除かずに参照のみ行う（手順8でまとめて取り除く）
            for old_key in _MIGRATION_MAP.get(key, []):
                if old_key in loaded_data:
                    loaded_value = loaded_data[old_key]
                    needs_save = True
                    break

        # 4-3. 旧デフォルトのファイル名プリセットのままであれば、上書きを防ぐ現デフォルトに置き換え、上書き保存対象とする
        if key == "save.filenamePreset" and loaded_value == _LEGACY_DEFAULT_FILENAME_PRESET:
            loaded_value = default_value
            needs_save = True

        # 5. 設定値を読み込めた場合、バリデーションを実行し正常値であれば使用
        if loaded_value is not None:
            validation_result = validate(key, loaded_value)
            # 5-1. エラーが無ければ正常値として採用（警告は保存可能な値のため、そのまま採用する）
            if validation_result is None or not validation_result.is_error:
                new_data[key] = loaded_value
            # 5-2. エラーがあればデフォルト値を使用し、設定ファイルを退避・保存対象とする
            else:
                new_data[key] = default_value
                invalid_keys[key] = (loaded_value, validation_result.message)
                needs_save = True

        # 6. 設定ファイル内に現キー名・旧キー名ともに存在しない場合、デフォルト値を使用し、設定ファイルを保存対象とする
        else:
            new_data[key] = default_value
            needs_save = True

    # 7. {title} が空でも保存先パスが最大長を超える場合、ファイル名プリセットをデフォルト値に戻し、設定ファイルを退避・保存対象とする
    # フォルダとファイル名の組み合わせで決まるため、項目単位の検証（手順5）とは別に行う
    output_path_result = _validate_output_path_length(new_data)
    if output_path_result and output_path_result.is_error:
        invalid_keys["save.filenamePreset"] = (new_data["save.filenamePreset"], output_path_result.message)
        new_data["save.filenamePreset"] = _DEFAULT_SETTINGS["save.filenamePreset"]
        needs_save = True

    _data.clear()
    _data.update(new_data)
    notifier.log(f"設定ファイルを読み込みました。({settings_file_path})")

    # 8. 旧キーをまとめて取り除く（現キーと旧キーが両方ある場合の旧キーも含む）
    for old_keys in _MIGRATION_MAP.values():
        for old_key in old_keys:
            if old_key in loaded_data:
                del loaded_data[old_key]
                needs_save = True

    # 9. 旧キーや未知のキーが残っていれば、ファイルから取り除くため保存対象とする
    if loaded_data:
        needs_save = True

    # 10. 設定ファイル内に壊れている設定値が含まれていた場合、上書き前に設定ファイルを退避する
    if invalid_keys:
        corrupted_filename = _backup_corrupted_file()
        message = f"元の設定ファイルを「{corrupted_filename}」に退避し、デフォルト設定を適用しました。"
        log_details = "\n".join([f"キー '{key}' の値 ({item[0]!r}) が不正です: {item[1]}" for key, item in invalid_keys.items()])

        notifier.notify(
            title="設定ファイルの読み込みに失敗しました。",
            message=f"{message}\n詳細はログファイルを参照してください。",
            log_message=f"{message}\n{log_details}",
            buttons=[notifier.NotificationButton.OPEN_SETTINGS, notifier.NotificationButton.OPEN_LOG],
            category=notifier.NotificationCategory.ERROR,
        )

    # 11. 設定ファイルの更新が必要な場合、ファイルを保存する
    if needs_save:
        save()


def get(key):
    """
    指定されたキーの設定値を取得する
    設定ファイルに値が存在しない場合は、_DEFAULT_SETTINGSから取得する
    """
    if key in _data:
        return _data[key]
    return _DEFAULT_SETTINGS.get(key)


def set(key, value):
    """
    設定値を一時的に更新する
    """
    _data[key] = value


def save():
    """
    現在の設定内容をsettings.json に書き込む（破損防止保存）
    """
    settings_file_path = _get_settings_path()
    temporary_path = _get_temporary_settings_path()

    try:
        # 1. 一時ファイルに書き出し、ディスクへ確実にフラッシュする
        with open(temporary_path, "w", encoding="utf-8") as file:
            # JSONとして書き込む
            json.dump(_data, file, indent=4, ensure_ascii=False)
            # 書き込んだデータをPythonからOSのキャッシュへ強制的に流す
            file.flush()
            # OSのキャッシュをディスクへ強制的に書き込む
            os.fsync(file.fileno())

        # 2. 一時ファイルを本来の設定ファイルパスへ安全に置き換える
        os.replace(temporary_path, settings_file_path)
        notifier.log(f"設定ファイルを保存しました。({settings_file_path})")

    except Exception as exception:
        notifier.log(f"設定ファイルの保存に失敗しました。\n{exception}")
        # 保存に失敗した一時ファイルが残っていれば削除する
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass


def has_validation_rule(key):
    """
    指定された設定キーにバリデーションルールが定義されているかを判定する
    UI側でバリデーション有無を意識せずに自動制御できるようにするために使用する

    Args:
        key (str): 設定キー

    Returns:
        bool: バリデーションルールが存在する場合は True、なければ False
    """
    return key in _VALIDATION_RULES and bool(_VALIDATION_RULES[key])


def validate(key, value):
    """
    指定された設定キーに対して定義されているバリデーションルールを順次実行する

    Args:
        key (str): 設定キー
        value: 検証する値

    Returns:
        ValidationResult | None: 最初に発生したエラー。エラーが無ければ最初の警告（問題なければ None）
    """
    # 先に警告が出ても後ろのルールのエラーを隠さないよう、警告は保留して全ルールを確認する
    first_warning = None
    for method_name in _VALIDATION_RULES.get(key, []):
        method = globals().get(method_name)
        if method:
            result = method(value)
            if result is None:
                continue
            if result.is_error:
                return result
            first_warning = first_warning or result
    return first_warning


def validate_all(data):
    """
    全設定項目のバリデーションを一括実行する

    Args:
        data (dict): {設定キー: 値} の辞書

    Returns:
        dict: {設定キー: ValidationResult} の辞書（エラーまたは警告がある項目のみ）
    """
    # 1. 項目ごとのバリデーションを実行
    results = {}
    for key, value in data.items():
        result = validate(key, value)
        if result:
            results[key] = result

    # 2. 保存先フォルダとファイル名プリセットの組み合わせでパス長を検証
    # 項目単体のエラーがある場合はパス長を検証できていないため、そちらの表示を優先する
    output_path_result = _validate_output_path_length(data)
    existing_result = results.get("save.filenamePreset")
    if output_path_result and not (existing_result and existing_result.is_error):
        results["save.filenamePreset"] = output_path_result

    return results


def _validate_output_path_length(data):
    """
    保存先フォルダとファイル名プリセットの組み合わせで、保存先フルパスが最大パス長に収まるかを検証する
    {title} を空とした最短フルパスで判定し、超過はエラー、{title} に使える残り文字数が少なければ警告とする
    項目単位では判定できないため、設定値の辞書を受け取る

    Args:
        data (dict): {設定キー: 値} の辞書

    Returns:
        ValidationResult | None: 超過時はエラー、残り文字数が少ない場合は警告（問題なければ None）
    """
    # 1. 書式エラーや禁止文字があるとパスを組み立てられないため、両項目がそろい項目単位のエラーが無い場合のみ対象とする
    directory = data.get("save.directory")
    preset_string = data.get("save.filenamePreset")
    if directory is None or preset_string is None:
        return None
    for key, value in (("save.directory", directory), ("save.filenamePreset", preset_string)):
        item_result = validate(key, value)
        if item_result and item_result.is_error:
            return None

    # 2. 撮影時と同じ組み立て処理で {title} を空としたフルパスを組み立て、最大パス長までの残り文字数を求める
    shortest_path = filename_preset.format_output_path(directory, preset_string, title="")
    output_path_margin = constants.WINDOWS_MAX_PATH_LENGTH - len(shortest_path)

    # 3. {title} が空でも超える場合は、どう撮影しても失敗するためエラー
    if output_path_margin < 0:
        return ValidationResult.error(
            f"保存先パスが最大長を超えます。（{len(shortest_path)}/{constants.WINDOWS_MAX_PATH_LENGTH}文字）\nフォルダパスかファイル名を短くしてください。"
        )

    # 4. {title} を含み残り文字数が少ない場合は、長いタイトルのウィンドウで失敗しうるため警告
    # 書式文字列を解析し、置換フィールド名に title があるかを判定（固定文字列中の "title" は対象外）
    has_title_placeholder = any(field_name == "title" for _, field_name, _, _ in string.Formatter().parse(preset_string))
    if has_title_placeholder and output_path_margin < _TITLE_LENGTH_WARNING_THRESHOLD:
        return ValidationResult.warning(
            f"タイトルに使える残り文字数は{output_path_margin}文字です。\n長いタイトルのウィンドウは保存に失敗する可能性があります。"
        )

    return None


def _validate_not_empty(value):
    """
    設定値が未入力（空文字または空白のみ）でないかを検証する

    Args:
        value: 検証する値

    Returns:
        ValidationResult | None: エラー（未入力の場合はメッセージ、問題なければ None）
    """
    if value is None or not str(value).strip():
        return ValidationResult.error("必須項目です。")
    return None


def _validate_path_chars(value):
    """
    フォルダパス文字列にWindowsで使用できない不正文字が含まれていないかを検証する

    Args:
        value: 検証する値

    Returns:
        ValidationResult | None: エラー（不正文字が含まれる場合はメッセージ、問題なければ None）
    """
    path_string = str(value).strip()

    # チルダ（~）や環境変数を展開して検証対象の絶対パスを取得
    expanded_path = paths.expand_path(path_string)

    # パス全体で使用できない禁止文字（< > " | ? *）をチェック
    for char in expanded_path:
        if char in '<>"|?*':
            return ValidationResult.error(f"フォルダパスに使用できない文字が含まれています: {char}")

    # ドライブレターコロン（例: 'C:\' のコロン）以外の不正なコロンをチェック
    drive, rest_path = os.path.splitdrive(expanded_path)
    if ":" in rest_path:
        return ValidationResult.error("フォルダパスに使用できない文字が含まれています: :")

    # ドライブレターの形式チェック（1文字の英字 + コロン以外ならエラー）
    if drive and (len(drive) != 2 or not drive[0].isalpha() or drive[1] != ":"):
        return ValidationResult.error(f"ドライブ指定が不正です: {drive}")

    return None


def _validate_filename_chars(value):
    """
    ファイル名（プレースホルダ部分を除く固定文字列）にWindowsで使用できない禁止文字が含まれていないかを検証する

    Args:
        value: 検証する値

    Returns:
        ValidationResult | None: エラー（禁止文字が含まれる場合はメッセージ、問題なければ None）
    """
    preset_string = str(value).strip()

    # 波括弧部分（{...}）を除去した固定文字列を取得
    fixed_text = re.sub(r"\{[^{}]*\}", "", preset_string)

    # Windowsのファイル名で使用できない禁止文字をチェック
    for char in fixed_text:
        if char in '<>:"/\\|?*':
            return ValidationResult.error(f"ファイル名に使用できない文字が含まれています: {char}")

    return None


def _validate_shortcut_format(value):
    """
    ショートカットキー文字列が有効なキーの組み合わせかを検証する

    Args:
        value: 検証する値

    Returns:
        ValidationResult | None: エラー（無効な形式の場合はメッセージ、問題なければ None）
    """
    # 循環インポートを防ぐため関数内でインポート
    import lib.hotkey as hotkey

    if not hotkey.Manager.is_valid_shortcut(str(value)):
        return ValidationResult.error("有効なショートカットキーを入力してください。")
    return None


def _validate_preset_placeholders(value):
    """
    ファイル名プリセットの波括弧書式とプレースホルダを検証する
    撮影時に置換される timestamp・title・index・dup 以外のキーや構文エラーを検出する

    Args:
        value: 検証する値

    Returns:
        ValidationResult | None: エラー（書式が不正な場合はメッセージ、問題なければ None）
    """
    preset_string = str(value).strip()

    try:
        # 撮影時と同じ組み立て処理でダミー値を渡してフォーマットを試行
        filename_preset.format_output_path("", preset_string, title="TestTitle")
    except KeyError as exception:
        # 許可されていないプレースホルダ名
        return ValidationResult.error(f"使用できないプレースホルダです: {{{exception.args[0]}}}")
    except (ValueError, IndexError):
        # 波括弧の対応ミスや不正な書式指定子（{dup} のテンプレート不備を含む）
        return ValidationResult.error("書式が不正です。波括弧 { } の対応や書式指定を確認してください。")

    return None


def _validate_overwrite_risk(value):
    """
    ファイル名プリセットで、同名の既存ファイルを上書きする恐れがないかを検証する
    {index} / {dup} があれば連番で重複を避けられ、{timestamp} にマイクロ秒（%f）があれば実質重複しないため対象外とする

    Args:
        value: 検証する値

    Returns:
        ValidationResult | None: 警告（上書きの恐れがある場合はメッセージ、問題なければ None）
    """
    # 書式文字列を解析し、置換フィールドの (名前, 書式指定) を取り出す（固定文字列中の同名の語は対象外）
    fields = [(field_name, format_spec) for _, field_name, format_spec, _ in string.Formatter().parse(str(value)) if field_name]

    # 連番で重複を避けられるプレースホルダがあるか
    if any(field_name in ("index", "dup") for field_name, _ in fields):
        return None
    # マイクロ秒単位の日時で、撮影ごとに異なるファイル名になるか
    if any(field_name == "timestamp" and "%f" in (format_spec or "") for field_name, format_spec in fields):
        return None

    return ValidationResult.warning("同名のファイルがある場合は上書きされます。\n{dup} か {index} を含めると上書きを防げます。")


def _validate_update_check_mode(value):
    """
    アップデート確認の対象範囲が、定義済みの値（disabled / stable / prerelease）のいずれかであるかを検証する

    Args:
        value: 検証する値

    Returns:
        ValidationResult | None: エラー（未定義の値の場合はメッセージ、問題なければ None）
    """
    # 循環インポートを防ぐため関数内でインポート
    import lib.updater as updater

    if value not in [mode.value for mode in updater.UpdateCheckMode]:
        return ValidationResult.error("選択肢から選んでください。")
    return None


# モジュール読み込み時に自動で load() を実行する
load()
