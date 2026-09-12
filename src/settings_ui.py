import os
import sys
import ctypes
import multiprocessing
import customtkinter as ctk
import tkinter.filedialog as filedialog
import threading
import keyboard
from typing import NamedTuple

from settings_manager import *
from capture import *
from utils import *
from constants import *
from notifier import notifier

# UIフォント
_SYS_FONT = ("Meiryo UI", 13)
_HINT_FONT = ("Meiryo UI", 11)

# 開いている設定画面のプロセス
_settings_process = None

# メインプロセスへ設定変更（ホットキー再登録など）を通知するためのイベント
settings_update_event = multiprocessing.Event()


class SettingRow(NamedTuple):
    """設定項目行の構成要素をまとめて保持するデータクラス"""

    key: str  # 設定キー
    widget: ctk.CTkBaseClass  # 入力ウィジェット（Entry / Switch / OptionMenu）
    error_label: ctk.CTkLabel | None  # エラーメッセージ表示用ラベル（バリデーション対象外なら None）
    button: ctk.CTkButton | None = None  # 付属ボタンウィジェット（存在しない場合は None）


class _SettingRowBuilder:
    """
    1つの設定項目行（領域・見出し・入力部品・補足テキスト）を構築するビルダー
    """

    @staticmethod
    def create_button(parent, text, command, width=100, accent_color=None, hover_color=None, is_primary=True):
        """
        ボタンを生成する
        ※画面下部のボタン生成にも使用するため、staticにする

        Args:
            parent: ボタンを配置する親領域
            text (str): ボタンに表示するテキスト
            command (callable): クリック時に実行される関数
            width (int, optional): ボタンの幅
            accent_color (str, optional): アクセントカラー
            hover_color (str, optional): ホバー時のアクセントカラー
            is_primary (bool, optional): プライマリカラーを適用するかどうか（Falseの場合はグレー）

        Returns:
            ctk.CTkButton: 生成されたボタンウィジェット
        """
        fg_color = accent_color if is_primary else "gray"
        hover_color = hover_color if is_primary else "darkgray"

        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            font=_SYS_FONT,
            fg_color=fg_color,
            hover_color=hover_color,
            command=command,
        )

    def __init__(self, parent, key, label_text=None, hint_text=None, accent_color=None, hover_color=None):
        """
        設定項目行の領域を初期化する

        Args:
            parent: 行を配置する親領域
            key (str): 設定キー
            label_text (str, optional): 画面に表示する見出しテキスト
            hint_text (str, optional): 項目下部に表示する補足テキスト
            accent_color (str, optional): アクセントカラー
            hover_color (str, optional): ホバー時のアクセントカラー
        """
        self._parent = parent
        self._key = key
        self._accent_color = accent_color
        self._hover_color = hover_color

        # バリデーション設定
        self._has_validation = False
        self._on_validate = None

        # build() で返却するウィジェットとエラーラベル、ボタンの参照
        self._widget = None
        self._button = None
        self._error_label = None

        # 1項目分の領域
        self._row_area = ctk.CTkFrame(parent, fg_color="transparent")
        self._row_area.pack(fill="x", pady=(0, 15))

        # 見出しが存在する場合はラベルと横並び用の内部領域を作成
        if label_text:
            label = ctk.CTkLabel(self._row_area, text=label_text, font=_SYS_FONT)
            label.pack(anchor="w", pady=(0, 5))
            self._content_area = ctk.CTkFrame(self._row_area, fg_color="transparent")
            self._content_area.pack(fill="x")
        else:
            self._content_area = self._row_area

        # 補足テキストが存在する場合は下部に追加
        if hint_text:
            label_hint = ctk.CTkLabel(self._row_area, text=hint_text, text_color="gray", font=_HINT_FONT, justify="left")
            label_hint.pack(anchor="w")

    def add_validate(self, on_validate=None):
        """
        バリデーション機能を有効化し、エラーメッセージ表示用の枠を配置する
        メッセージ表示時に下の要素が押し下げられて画面がガタつく（レイアウトシフト）のを防ぐため、領域を常時確保する

        Args:
            on_validate (callable, optional): フォーカスアウト時に実行するバリデーション関数

        Returns:
            _SettingRowBuilder: self（メソッドチェーン用）
        """
        self._has_validation = True
        self._on_validate = on_validate

        # エラーメッセージ表示用の枠をあらかじめ確保して配置
        self._error_label = ctk.CTkLabel(
            self._row_area,
            text="",
            text_color="#FF6B6B",
            font=_HINT_FONT,
            anchor="w",
            height=18,
        )
        self._error_label.pack(anchor="w")

        return self

    def add_entry(self, initial_value=""):
        """
        入力欄を追加する

        Args:
            initial_value (str, optional): 初期入力テキスト

        Returns:
            _SettingRowBuilder: self（メソッドチェーン用）
        """
        # 入力欄を作成
        entry = ctk.CTkEntry(self._content_area, font=_SYS_FONT)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # 初期値を設定
        if initial_value is not None:
            entry.insert(0, str(initial_value))

        # 入力欄の参照を保持
        self._widget = entry

        # 自身を返す（メソッドチェーン用）
        return self

    def add_button(self, text, command, width=100, is_primary=True):
        """
        ボタンを追加する

        Args:
            text (str): ボタンに表示するテキスト
            command (callable): クリック時に実行される関数
            width (int, optional): ボタンの幅
            is_primary (bool, optional): プライマリカラーを適用するかどうか

        Returns:
            _SettingRowBuilder: self（メソッドチェーン用）
        """
        # ボタンを作成
        button = self.create_button(
            parent=self._content_area,
            text=text,
            command=command,
            width=width,
            accent_color=self._accent_color,
            hover_color=self._hover_color,
            is_primary=is_primary,
        )
        button.pack(side="right")

        # ボタンの参照を保持
        self._button = button

        # 自身を返す（メソッドチェーン用）
        return self

    def add_switch(self, text, is_selected=False):
        """
        トグルスイッチを追加する

        Args:
            text (str): スイッチのラベル
            is_selected (bool, optional): 初期の選択状態

        Returns:
            _SettingRowBuilder: self（メソッドチェーン用）
        """
        # スイッチを作成
        switch = ctk.CTkSwitch(
            self._content_area,
            text=text,
            font=_SYS_FONT,
            progress_color=self._accent_color,
            button_hover_color=self._hover_color,
        )
        switch.pack(anchor="w")

        # 初期値を設定
        if is_selected:
            switch.select()
        else:
            switch.deselect()

        # スイッチの参照を保持
        self._widget = switch

        # 自身を返す（メソッドチェーン用）
        return self

    def add_option_menu(self, values, initial_value=None):
        """
        ドロップダウンメニューを追加する

        Args:
            values (list): 選択肢のリスト
            initial_value (str, optional): 初期選択値

        Returns:
            _SettingRowBuilder: self（メソッドチェーン用）
        """
        # ドロップダウンを作成
        option_menu = ctk.CTkOptionMenu(
            self._content_area,
            values=values,
            font=_SYS_FONT,
            dropdown_font=_SYS_FONT,
            fg_color=self._accent_color,
            button_color=self._accent_color,
            button_hover_color=self._hover_color,
        )
        option_menu.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # 初期値を設定
        if initial_value:
            option_menu.set(initial_value)

        # ドロップダウンの参照を保持
        self._widget = option_menu

        # 自身を返す（メソッドチェーン用）
        return self

    def build(self):
        """
        設定項目行を完成させ、構成要素をまとめて返す
        バリデーション対象の入力欄が存在する場合はフォーカスアウト時の検証イベントを自動バインドする

        Returns:
            SettingRow: 設定キー・入力ウィジェット・エラーラベル・ボタンの組
        """
        # バリデーション対象かつコールバックと入力欄が存在する場合、フォーカスアウト時に検証を自動実行
        if self._has_validation and self._on_validate and isinstance(self._widget, ctk.CTkEntry):
            self._widget.bind("<FocusOut>", lambda event: self._on_validate())

        return SettingRow(key=self._key, widget=self._widget, error_label=self._error_label, button=self._button)


class SettingsWindow(ctk.CTk):
    """
    設定画面のGUIを構築・制御するクラス
    """

    # UIの外観
    _APPEARANCE_MODE = "system"

    def __init__(self, update_event=None):
        """
        設定画面を作成する

        Args:
            update_event (multiprocessing.Event, optional): メインプロセスに設定変更を通知するためのイベント
        """
        super().__init__()

        # 設定保存時にショートカットキー即時反映をメインプロセスへ通知するためのイベント
        self.update_event = update_event

        # 各設定項目・UIパーツへの参照を保持
        self._setting_items = {}

        # 適用・保存ボタンの参照を保持（バリデーション結果で活性/非活性を制御するため）
        self._button_apply = None
        self._button_save = None

        # ウィンドウのタイトル・サイズを設定
        self.title(f"{APP_NAME} 設定")
        self.geometry("500x580")
        self.resizable(False, False)

        # ウィンドウアイコン・タスクバーアイコンの設定
        # WindowsのタスクバーでPython標準アイコンになるのを防ぐため、固有AppUserModelID(AUMID)を設定
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_SETTINGS_USER_MODEL_ID)
        # アイコンを取得・設定
        icon_path = get_asset_path("icon.ico", "icon_dev.ico")
        self.iconbitmap(icon_path)

        # 外観を設定
        ctk.set_appearance_mode(self._APPEARANCE_MODE)

        # Windowsのアクセントカラーとホバー色を取得
        self._accent_color, self._hover_color = get_windows_accent_colors()
        # 下部の操作ボタン領域を先に配置する
        # （上部のコンテンツの高さが増減しても、下部ボタン領域が押しつぶされて縮小するのを防ぐため）
        self._build_button_area()

        # 画面全体を覆う領域（余白を持たせる）
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.pack(fill="both", expand=True, padx=20, pady=(20, 0))

        # 各設定項目を追加
        self._add_shortcut_field()
        self._add_volume_field()
        self._add_directory_field()
        self._add_filename_preset_field()
        self._add_metadata_toggle_field()
        self._add_windows_notification_toggle_field()

        # 初期表示時にバリデーションを実行する
        self._run_validation()

    def _create_row_builder(self, key, label_text=None, hint_text=None):
        """
        設定項目ビルダーを生成するヘルパー関数
        バリデーションルールの有無を settings_manager から判定し、対象項目の場合は自動でバリデーションを有効化する

        Args:
            key (str): 設定キー
            label_text (str, optional): 画面に表示する見出しテキスト
            hint_text (str, optional): 項目下部に表示する補足テキスト

        Returns:
            _SettingRowBuilder: 行ビルダーのインスタンス
        """
        builder = _SettingRowBuilder(
            parent=self.main_area,
            key=key,
            label_text=label_text,
            hint_text=hint_text,
            accent_color=self._accent_color,
            hover_color=self._hover_color,
        )
        # settings_manager にバリデーションルールが定義されている場合はバリデーションを有効化
        if settings.has_validation_rule(key):
            builder.add_validate(on_validate=self._run_validation)

        return builder

    def _add_shortcut_field(self):
        """ショートカットキー設定項目を追加する"""
        key = "capture.triggerShortcut"

        def record_shortcut():
            # 記録開始時の表示変更
            entry = setting_row.widget
            button = setting_row.button
            previous_value = entry.get()
            button.configure(state="disabled", text="入力待ち...")
            entry.delete(0, "end")
            entry.insert(0, "キーを押してください...")
            entry.configure(state="disabled")

            def _record_thread():
                # キーボード入力を待機（ブロッキング）
                hotkey = keyboard.read_hotkey(suppress=False)

                # メインプロセスで表示を更新する関数
                def _update_display():
                    entry.configure(state="normal")
                    entry.delete(0, "end")
                    # Escキーの場合はキャンセル扱いとして元の値に戻す
                    if hotkey.lower() == "esc":
                        entry.insert(0, previous_value)
                    else:
                        entry.insert(0, hotkey)
                    button.configure(state="normal", text="キーを記録")

                self.after(0, _update_display)

            # 画面が固まらないよう別処理で待機
            threading.Thread(target=_record_thread, daemon=True).start()

        setting_row = (
            self._create_row_builder(
                key=key,
                label_text="ショートカットキー:",
                hint_text="記録ボタン押下後、設定したいキーを押してください。\nEscキーでキャンセル",
            )
            .add_entry(initial_value=settings.get(key))
            .add_button(text="キーを記録", width=100, command=record_shortcut)
            .build()
        )
        self._setting_items[key] = setting_row

    def _add_volume_field(self):
        """音量設定項目を追加する"""
        key = "capture.soundVolume"

        # 音量の選択肢（0%から100%まで10%刻み）
        volume_options = [f"{volume}%" if volume > 0 else "0% (無音)" for volume in range(0, 101, 10)]

        # 現在の設定値（0〜100）を取得し、選択肢の初期値を決定
        current_volume = settings.get(key)
        if current_volume is None:
            current_volume = 100
        initial_option = f"{current_volume}%" if current_volume > 0 else "0% (無音)"
        if initial_option not in volume_options:
            initial_option = "100%"

        # テスト再生ボタン
        def test_sound():
            selected_text = setting_row.widget.get()
            # "0% (無音)" や "50%" から数値を抽出して再生
            try:
                volume = int(selected_text.split("%")[0])
            except ValueError:
                volume = 100
            play_capture_sound(volume=volume)

        setting_row = (
            self._create_row_builder(key=key, label_text="撮影時の通知音量:")
            .add_option_menu(values=volume_options, initial_value=initial_option)
            .add_button(text="テスト再生", width=100, command=test_sound)
            .build()
        )
        self._setting_items[key] = setting_row

    def _add_directory_field(self):
        """保存先フォルダ設定項目を追加する"""
        key = "save.directory"

        def browse_directory():
            # 初期表示フォルダ：入力があればそのフォルダ、無ければユーザーフォルダを表示
            entry = setting_row.widget
            initial_dir = entry.get()
            if not os.path.exists(initial_dir):
                initial_dir = os.path.expanduser("~")
            # フォルダ選択ダイアログを表示
            selected_dir = filedialog.askdirectory(initialdir=initial_dir, title="フォルダを選択")
            # フォルダが選択された場合
            if selected_dir:
                selected_dir = selected_dir.replace("/", "\\")
                entry.delete(0, "end")
                entry.insert(0, selected_dir)

        setting_row = (
            self._create_row_builder(key=key, label_text="保存先フォルダ:")
            .add_entry(initial_value=settings.get(key))
            .add_button(text="参照...", width=80, command=browse_directory)
            .build()
        )
        self._setting_items[key] = setting_row

    def _add_filename_preset_field(self):
        """ファイル名プリセット設定項目を追加する"""
        key = "save.filenamePreset"
        self._setting_items[key] = (
            self._create_row_builder(
                key=key,
                label_text="ファイル名プリセット:",
                hint_text="{timestamp}: 撮影日時 {timestamp:%Y%m%d} などで書式カスタムが可能です\n{title}: ウィンドウタイトル",
            )
            .add_entry(initial_value=settings.get(key))
            .build()
        )

    def _add_metadata_toggle_field(self):
        """撮影日時のEXIFメタデータ埋め込み設定スイッチを追加する"""
        key = "save.embedDatetimeMetadata"
        self._setting_items[key] = (
            self._create_row_builder(key=key)
            .add_switch(
                text="撮影日時のEXIFメタデータを埋め込む",
                is_selected=bool(settings.get(key)),
            )
            .build()
        )

    def _add_windows_notification_toggle_field(self):
        """Windowsの通知設定スイッチを追加する"""
        key = "capture.enableSystemNotification"
        self._setting_items[key] = (
            self._create_row_builder(key=key)
            .add_switch(
                text="Windowsの通知を表示する",
                is_selected=bool(settings.get(key)),
            )
            .build()
        )

    def _build_button_area(self):
        """
        設定画面に適用・保存・キャンセルの各操作ボタンを配置する
        """
        # ボタン用領域（画面下部に配置）
        buttons_area = ctk.CTkFrame(self, fg_color="transparent")
        buttons_area.pack(side="bottom", fill="x", pady=20)

        # 全体を中央揃えにするためのダミー領域を利用しつつ、packで配置
        inner_area = ctk.CTkFrame(buttons_area, fg_color="transparent")
        inner_area.pack(anchor="center")

        self._button_apply = _SettingRowBuilder.create_button(
            inner_area,
            text="適用",
            width=100,
            accent_color=self._accent_color,
            hover_color=self._hover_color,
            command=self._apply_settings,
        )
        self._button_apply.pack(side="left", padx=10)

        self._button_save = _SettingRowBuilder.create_button(
            inner_area,
            text="保存",
            width=100,
            accent_color=self._accent_color,
            hover_color=self._hover_color,
            command=self._save_settings,
        )
        self._button_save.pack(side="left", padx=10)

        button_cancel = _SettingRowBuilder.create_button(
            inner_area,
            text="キャンセル",
            width=100,
            is_primary=False,
            command=self.destroy,
        )
        button_cancel.pack(side="left", padx=10)

    def _run_validation(self):
        """
        全設定項目のバリデーションを実行し、エラー表示とボタン状態を更新する
        エラーラベルはあらかじめ枠を確保して配置されているため、text の更新のみを行いレイアウトのズレを防ぐ
        """
        has_error = False
        for key, setting_row in self._setting_items.items():
            if setting_row.error_label is None:
                continue

            # ウィジェットから現在の値を取得してバリデーション実行
            value = setting_row.widget.get()
            error = settings.validate(key, value)

            if error:
                setting_row.error_label.configure(text=error)
                has_error = True
            else:
                setting_row.error_label.configure(text="")

        # エラーがある場合は適用・保存ボタンを非活性にする
        state = "disabled" if has_error else "normal"
        if self._button_apply:
            self._button_apply.configure(state=state)
        if self._button_save:
            self._button_save.configure(state=state)

    def _apply_settings(self):
        """
        現在の入力を設定ファイルに保存する。画面はそのまま維持される
        """
        # UI上の全ての入力値を settings オブジェクトに反映させる
        for key, setting_row in self._setting_items.items():
            value = setting_row.widget.get()
            # CTkSwitch の場合は 0/1 が返るため bool に変換する
            if isinstance(setting_row.widget, ctk.CTkSwitch):
                value = bool(value)
            # CTkOptionMenu（音量設定）の場合はパーセント文字列から整数に変換する
            elif isinstance(setting_row.widget, ctk.CTkOptionMenu) and key == "capture.soundVolume":
                try:
                    value = int(value.split("%")[0])
                except ValueError:
                    value = 100
            settings.set(key, value)

        # 設定ファイルに保存する
        settings.save()

        # mainプロセスへ設定変更を通知する
        if hasattr(self, "update_event") and self.update_event is not None:
            self.update_event.set()

        notifier.log("設定を適用しました。")

    def _save_settings(self):
        """
        現在の入力を設定ファイルに保存し、画面を閉じる
        """
        self._apply_settings()
        self.destroy()


def _run_settings_window_process(update_event=None):
    """
    別プロセス内で実行されるエントリーポイント
    設定画面のインスタンスを作成し、メインループを開始する
    """
    app = SettingsWindow(update_event=update_event)
    app.mainloop()


def open_settings_window(icon=None, item=None):
    """
    右クリックメニューや通知等から呼び出され、設定画面を別プロセスで起動する

    Args:
        icon (pystray.Icon, optional): 呼び出し元のトレイアイコン
        item (pystray.MenuItem, optional): 呼び出し元のメニューアイテム
    """
    global _settings_process
    try:
        # すでに設定画面が開いている場合は多重起動しない
        if _settings_process is not None and _settings_process.is_alive():
            return

        _settings_process = multiprocessing.Process(target=_run_settings_window_process, args=(settings_update_event,), daemon=True)
        _settings_process.start()
    except Exception as exception:
        # エラー通知・ログ出力
        notifier.notify(
            title="設定画面の起動に失敗しました。",
            message="エラーが発生しました。詳細はログファイルを参照してください。",
            log_message=f"エラーが発生しました。\n{exception}",
            buttons=[BUTTON_OPEN_LOG],
        )


# このファイルを直接起動した際に設定画面を表示する
if __name__ == "__main__":
    _run_settings_window_process()
