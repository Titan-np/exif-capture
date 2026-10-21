"""
ファイル名プリセットのプレースホルダ（{timestamp} / {title} / {index} / {dup}）を展開し、保存先フルパスを組み立てる
"""

import datetime
import os

import lib.paths as paths


class FormattableTimestamp(datetime.datetime):
    """
    ファイル名プリセットの {timestamp} に対応する datetime サブクラス
    書式指定がない場合はデフォルト書式を使用する
    """

    _DEFAULT_FORMAT = "%Y%m%d_%H%M%S"

    def __format__(self, spec):
        # 書式指定がない場合はデフォルト書式を使用する
        if not spec:
            return self.strftime(self._DEFAULT_FORMAT)
        return self.strftime(spec)


class DuplicateSuffix:
    """
    ファイル名プリセットの {dup} に対応するクラス
    1件目は空文字、同名ファイルがある2件目以降のみ番号付きの文字列に展開する
    書式指定は「printf形式のテンプレート[:2件目の番号]」（例: {dup:_%d} → "_2"、{dup:_%d:1} → "_1"）
    ファイル名に ":" は使えないため、テンプレートと番号の区切りに使っても衝突しない
    """

    _DEFAULT_TEMPLATE = " (%d)"
    _DEFAULT_START_NUMBER = 2

    def __init__(self, sequence_number: int):
        """
        Args:
            sequence_number (int): 同名ファイルを避けるための連番（1件目が1）
        """
        self.sequence_number = sequence_number

    def __format__(self, spec):
        # 1. 書式指定をテンプレートと2件目の番号に分割（省略時はデフォルト値を使用する）
        template, separator, start_text = spec.rpartition(":")
        if not separator:
            template, start_text = spec, ""
        template = template or self._DEFAULT_TEMPLATE
        try:
            start_number = int(start_text) if start_text else self._DEFAULT_START_NUMBER
        except ValueError:
            raise ValueError(f"{{dup}} の開始番号が整数ではありません: {start_text}")

        # 2. テンプレートに番号を埋め込む（書式エラーは他のプレースホルダと同じく ValueError として扱う）
        try:
            suffix = template % (start_number + self.sequence_number - 2)
        except TypeError as exception:
            raise ValueError(f"{{dup}} のテンプレートが不正です: {template}") from exception

        # 3. 1件目は番号を付けない（書式の検証のため、組み立ては1件目でも行う）
        return "" if self.sequence_number == 1 else suffix


def format_output_path(directory: str, filename_preset: str, title: str, timestamp=None, sequence_number: int = 1) -> str:
    """
    保存先フォルダ・ファイル名プリセット・ウィンドウタイトルから、プレースホルダを埋めた保存先フルパスを1つ組み立てる
    既存ファイルは参照しないため、撮影時の保存先の確定（build_output_path）と設定時の検証の双方から使う

    Args:
        directory (str): 保存先フォルダ（チルダや環境変数を含んでもよい）
        filename_preset (str): ファイル名プリセット（例: "{timestamp}_{title}{dup}.png"）
        title (str): {title} に埋め込む文字列（禁止文字は置換済みであること）
        timestamp (FormattableTimestamp, optional): {timestamp} に埋め込む日時。省略時は現在時刻
        sequence_number (int): {index} と {dup} に埋め込む連番（1件目が1）

    Returns:
        str: 保存先フルパス

    Raises:
        KeyError, ValueError, IndexError: プリセットの書式が不正な場合
    """
    # 1. 日時の指定が無い場合は現在時刻を使う
    if timestamp is None:
        timestamp = FormattableTimestamp.now()

    # 2. プリセットのプレースホルダを展開してファイル名を作る（不正な書式はここで例外になる）
    output_filename = filename_preset.format(
        timestamp=timestamp,
        title=title,
        index=sequence_number,
        dup=DuplicateSuffix(sequence_number),
    )

    # 3. 保存先フォルダ（チルダ・環境変数を展開）とつなげてフルパスにする
    return os.path.join(paths.expand_path(directory), output_filename)


def build_output_path(directory: str, filename_preset: str, title: str, captured_at: datetime.datetime) -> str:
    """
    撮影時の保存先フルパスを、保存先フォルダ内の既存ファイルと被らない連番で確定する
    プリセットに {index} / {dup} が無く連番でパスが変わらない場合は、既存ファイルがあってもそのパスを返す（上書きとなる）

    Args:
        directory (str): 保存先フォルダ（チルダや環境変数を含んでもよい）
        filename_preset (str): ファイル名プリセット（例: "{timestamp}_{title}{dup}.png"）
        title (str): {title} に埋め込む文字列（禁止文字は置換済みであること）
        captured_at (datetime.datetime): {timestamp} に埋め込む撮影日時（EXIF の日時とそろえるため呼び出し元で取得する）

    Returns:
        str: 保存先フルパス

    Raises:
        KeyError, ValueError, IndexError: プリセットの書式が不正な場合
        FileExistsError: 連番が上限に達しても空きが見つからない場合
    """
    # 連番の上限（無限ループ防止用）
    _MAX_SEQUENCE_NUMBER = 9999

    # 1. 撮影日時を、書式指定なしでもデフォルト書式で展開できる FormattableTimestamp に変換する
    timestamp = FormattableTimestamp.combine(captured_at.date(), captured_at.time())
    first_path = format_output_path(directory, filename_preset, title, timestamp=timestamp)

    # 2. 連番を1から増やし、既存ファイルと被らないパスを探す
    # 撮影処理はロックで直列化されているため、存在確認から保存までの間に他の撮影と競合しない
    if not os.path.exists(first_path):
        return first_path
    for sequence_number in range(2, _MAX_SEQUENCE_NUMBER + 1):
        output_path = format_output_path(directory, filename_preset, title, timestamp=timestamp, sequence_number=sequence_number)
        # 連番でパスが変わらないプリセットは重複を避けられないため、1件目のパスで上書きする
        if output_path == first_path:
            return first_path
        if not os.path.exists(output_path):
            return output_path

    raise FileExistsError(f"連番が上限({_MAX_SEQUENCE_NUMBER})に達したため、保存先パスを決められませんでした。({first_path})")
