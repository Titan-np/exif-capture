import os
import sys
import ctypes
import multiprocessing
import customtkinter as ctk
import tkinter.filedialog as filedialog
import threading
import keyboard

from settings_manager import *
from capture import *
from utils import *
from constants import *

# UIフォント
_SYS_FONT = ("Meiryo UI", 13)
_HINT_FONT = ("Meiryo UI", 11)

# 開いている設定画面のプロセス
_settings_process = None


class _SettingRowBuilder:
    """
    1つの設定項目行（領域・見出し・入力部品・補足テキスト）を構築するビルダー
    """

    def __init__(self, parent, label_text=None, hint_text=None, accent_color=None, hover_color=None):
        """
        設定項目行の領域を初期化する

        Args:
            parent: 行を配置する親領域
            label_text (str, optional): 画面に表示する見出しテキスト
            hint_text (str, optional): 項目下部に表示する補足テキスト
            accent_color (str, optional): アクセントカラー
            hover_color (str, optional): ホバー時のアクセントカラー
        """
        self._accent_color = accent_color
        self._hover_color = hover_color

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

    def add_entry(self, initial_value=""):
        """
        入力欄を追加する

        Args:
            initial_value (str, optional): 初期入力テキスト

        Returns:
            ctk.CTkEntry: 生成された入力欄ウィジェット
        """
        entry = ctk.CTkEntry(self._content_area, font=_SYS_FONT)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        if initial_value is not None:
            entry.insert(0, str(initial_value))
        return entry

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

    def add_button(self, text, command, width=100, is_primary=True):
        """
        ボタンを追加する

        Args:
            text (str): ボタンに表示するテキスト
            command (callable): クリック時に実行される関数
            width (int, optional): ボタンの幅
            is_primary (bool, optional): プライマリカラーを適用するかどうか

        Returns:
            ctk.CTkButton: 生成されたボタンウィジェット
        """
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
        return button

    def add_switch(self, text, is_selected=False):
        """
        トグルスイッチを追加する

        Args:
            text (str): スイッチのラベル
            is_selected (bool, optional): 初期の選択状態

        Returns:
            ctk.CTkSwitch: 生成されたスイッチウィジェット
        """
        switch = ctk.CTkSwitch(
            self._content_area,
            text=text,
            font=_SYS_FONT,
            progress_color=self._accent_color,
            button_hover_color=self._hover_color,
        )
        switch.pack(anchor="w")
        if is_selected:
            switch.select()
        else:
            switch.deselect()
        return switch

    def add_option_menu(self, values, initial_value=None):
        """
        ドロップダウンメニューを追加する

        Args:
            values (list): 選択肢のリスト
            initial_value (str, optional): 初期選択値

        Returns:
            ctk.CTkOptionMenu: 生成されたドロップダウンメニューウィジェット
        """
        option_menu = ctk.CTkOptionMenu(
            self._content_area,
            values=values,
            font=_SYS_FONT,
            dropdown_font=_SYS_FONT,
            fg_color=self._accent_color,
            button_color=self._accent_color,
            button_hover_color=self._hover_color,
        )
        if initial_value:
            option_menu.set(initial_value)
        option_menu.pack(side="left", fill="x", expand=True, padx=(0, 10))
        return option_menu


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

        # ウィンドウのタイトル・サイズを設定
        self.title(f"{APP_NAME} 設定")
        self.geometry("500x560")
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

        # 各設定項目を持たせるDictionary
        self._setting_items = {}

        # 画面全体を覆う領域（余白を持たせる）
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.pack(fill="both", expand=True, padx=20, pady=20)

        # 各設定項目を追加
        self._add_shortcut_field()
        self._add_windows_notification_toggle_field()
        self._add_volume_field()
        self._add_directory_field()
        self._add_filename_preset_field()
        self._add_metadata_toggle_field()

        # 操作ボタンを追加
        self._build_button_area()

    def _create_row_builder(self, label_text=None, hint_text=None):
        """
        設定項目ビルダーを生成するヘルパー関数

        Args:
            label_text (str, optional): 画面に表示する見出しテキスト
            hint_text (str, optional): 項目下部に表示する補足テキスト

        Returns:
            _SettingRowBuilder: 行ビルダーのインスタンス
        """
        return _SettingRowBuilder(
            parent=self.main_area,
            label_text=label_text,
            hint_text=hint_text,
            accent_color=self._accent_color,
            hover_color=self._hover_color,
        )

    def _add_shortcut_field(self):
        """ショートカットキー設定項目を追加する"""
        key = "capture.triggerShortcut"
        row = self._create_row_builder(
            label_text="ショートカットキー:",
            hint_text="記録ボタン押下後、設定したいキーを押してください。\nEscキーでキャンセル",
        )
        entry = row.add_entry(settings.get(key))

        def record_shortcut():
            # 記録開始時の表示変更
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

        button = row.add_button(text="キーを記録", width=100, command=record_shortcut)
        self._setting_items[key] = entry

    def _add_windows_notification_toggle_field(self):
        """Windowsの通知設定スイッチを追加する"""
        key = "capture.enableSystemNotification"
        row = self._create_row_builder()
        switch = row.add_switch(
            text="撮影完了時にWindowsの通知を表示する",
            is_selected=bool(settings.get(key)),
        )
        self._setting_items[key] = switch

    def _add_volume_field(self):
        """音量設定項目を追加する"""
        key = "capture.soundVolume"
        row = self._create_row_builder(label_text="撮影時の通知音量:")

        # 音量の選択肢（0%から100%まで10%刻み）
        volume_options = [f"{volume}%" if volume > 0 else "0% (無音)" for volume in range(0, 101, 10)]

        # 現在の設定値（0〜100）を取得し、選択肢の初期値を決定
        current_volume = settings.get(key)
        if current_volume is None:
            current_volume = 100
        initial_option = f"{current_volume}%" if current_volume > 0 else "0% (無音)"
        if initial_option not in volume_options:
            initial_option = "100%"

        # ドロップダウン
        option_menu = row.add_option_menu(values=volume_options, initial_value=initial_option)

        # テスト再生ボタン
        def test_sound():
            selected_text = option_menu.get()
            # "0% (無音)" や "50%" から数値を抽出して再生
            try:
                volume = int(selected_text.split("%")[0])
            except ValueError:
                volume = 100
            play_capture_sound(volume=volume)

        row.add_button(text="テスト再生", width=100, command=test_sound)
        self._setting_items[key] = option_menu

    def _add_directory_field(self):
        """保存先フォルダ設定項目を追加する"""
        key = "save.directory"
        row = self._create_row_builder(label_text="保存先フォルダ:")
        entry = row.add_entry(settings.get(key))

        def browse_directory():
            # 初期表示フォルダ：入力があればそのフォルダ、無ければユーザーフォルダを表示
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

        row.add_button(text="参照...", width=80, command=browse_directory)
        self._setting_items[key] = entry

    def _add_filename_preset_field(self):
        """ファイル名プリセット設定項目を追加する"""
        key = "save.filenamePreset"
        row = self._create_row_builder(
            label_text="ファイル名プリセット:",
            hint_text="{timestamp}: 撮影日時\n{title}: ウィンドウタイトル",
        )
        entry = row.add_entry(settings.get(key))
        self._setting_items[key] = entry

    def _add_metadata_toggle_field(self):
        """撮影日時のEXIFメタデータ埋め込み設定スイッチを追加する"""
        key = "save.embedDatetimeMetadata"
        row = self._create_row_builder()
        switch = row.add_switch(
            text="撮影日時のEXIFメタデータを埋め込む",
            is_selected=bool(settings.get(key)),
        )
        self._setting_items[key] = switch

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

        button_apply = _SettingRowBuilder.create_button(
            inner_area,
            text="適用",
            width=100,
            accent_color=self._accent_color,
            hover_color=self._hover_color,
            command=self._apply_settings,
        )
        button_apply.pack(side="left", padx=10)

        button_save = _SettingRowBuilder.create_button(
            inner_area,
            text="保存",
            width=100,
            accent_color=self._accent_color,
            hover_color=self._hover_color,
            command=self._save_settings,
        )
        button_save.pack(side="left", padx=10)

        button_cancel = _SettingRowBuilder.create_button(
            inner_area,
            text="キャンセル",
            width=100,
            is_primary=False,
            command=self.destroy,
        )
        button_cancel.pack(side="left", padx=10)

    def _apply_settings(self):
        """
        現在の入力を設定ファイルに保存する。画面はそのまま維持される
        """
        # UI上の全ての入力値を settings オブジェクトに反映させる
        for key, widget in self._setting_items.items():
            value = widget.get()
            # CTkSwitch の場合は 0/1 が返るため bool に変換する
            if isinstance(widget, ctk.CTkSwitch):
                value = bool(value)
            # CTkOptionMenu（音量設定）の場合はパーセント文字列から整数に変換する
            elif isinstance(widget, ctk.CTkOptionMenu) and key == "capture.soundVolume":
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

        write_log("設定を適用しました。")

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


def open_settings_window(icon=None, item=None, update_event=None):
    """
    右クリックメニューから呼び出され、設定画面を別プロセスで起動する

    Args:
        icon (pystray.Icon, optional): 呼び出し元のトレイアイコン
        item (pystray.MenuItem, optional): 呼び出し元のメニューアイテム
        update_event (multiprocessing.Event, optional): メインプロセスに設定変更を通知するためのイベント
    """
    global _settings_process
    try:
        # すでに設定画面が開いている場合は多重起動しない
        if _settings_process is not None and _settings_process.is_alive():
            return

        _settings_process = multiprocessing.Process(target=_run_settings_window_process, args=(update_event,), daemon=True)
        _settings_process.start()
    except Exception as exception:
        write_log(f"設定画面の起動に失敗しました。\n{exception}")


# このファイルを直接起動した際に設定画面を表示する
if __name__ == "__main__":
    _run_settings_window_process()
