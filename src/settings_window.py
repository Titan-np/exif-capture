import ctypes
import multiprocessing
import os
import threading
import tkinter.filedialog as filedialog
import webbrowser
from typing import NamedTuple

import customtkinter as ctk

import capture
import lib.constants as constants
import lib.hotkey as hotkey
import lib.notifier as notifier
import lib.paths as paths
import lib.settings as settings
import lib.startup as startup
import lib.updater as updater
import lib.version as version
import lib.windows_shell as windows_shell

# UIフォント
_SYS_FONT = ("Meiryo UI", 13)
_HINT_FONT = ("Meiryo UI", 12)
_HEADING_FONT = ("Meiryo UI", 14, "bold")
_TAB_FONT = ("Meiryo UI", 13, "bold")

# 補足テキストの余白（px）
# 入力部品と補足テキスト・検証メッセージの間
_HINT_TOP_SPACING = 4
# 補足テキストの要素同士の間
_HINT_ITEM_SPACING = 4
# 補足テキスト・検証メッセージの行間。Tkのラベルは行間を指定できないため、1行ずつ分けたラベル間の余白で広げる
_HINT_LINE_SPACING = 2

# 入力欄下のメッセージ色（エラーは保存不可、警告は保存可能だが注意が必要）
_ERROR_TEXT_COLOR = "#FF6B6B"
_WARNING_TEXT_COLOR = "#FFA94D"

# 入力欄下のメッセージ枠の行数
# メッセージ表示時に下の項目がずれないよう常に確保するため、検証メッセージ（settings.py）は2行以内にそろえる
_VALIDATION_MESSAGE_LINES = 2

# リンクの文字色（ライトモード, ダークモード）。アクセントカラーは暗い色の場合に背景と見分けにくいため別に定める
_LINK_TEXT_COLOR = ("#0B63CE", "#6CB4FF")

# Windowsのアクセントカラーを取得できなかった場合に、ボタンやスイッチに使う色
_FALLBACK_ACCENT_COLOR = "#228B22"

# 設定画面のウィンドウサイズ（幅・高さ。サイズ変更は不可）
_WINDOW_WIDTH = 500
_WINDOW_HEIGHT = 640

# UIの外観（"system" / "light" / "dark"）
_APPEARANCE_MODE = "system"


# ============================================================
# 設定項目行の部品
# ============================================================


class SettingRow(NamedTuple):
    """設定項目行の構成要素をまとめて保持するデータクラス"""

    key: str  # 設定キー
    widget: ctk.CTkBaseClass  # 入力ウィジェット（Entry / Switch / OptionMenu）、または状態表示用の Label
    message_labels: list[ctk.CTkLabel] | None  # 検証メッセージを1行ずつ表示するラベル（バリデーション対象外なら None）
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
        # プライマリでないボタン（キャンセルなど）は、アクセントカラーではなくグレーにする
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

    def __init__(self, parent, key, label_text=None, accent_color=None, hover_color=None):
        """
        設定項目行の領域を初期化する

        Args:
            parent: 行を配置する親領域
            key (str): 設定キー
            label_text (str, optional): 画面に表示する見出しテキスト
            accent_color (str, optional): アクセントカラー
            hover_color (str, optional): ホバー時のアクセントカラー
        """
        self._parent = parent
        self._key = key
        self._accent_color = accent_color
        self._hover_color = hover_color

        # 1. バリデーション設定と、build() で返却する部品の参照を初期化
        self._has_validation = False
        self._on_validate = None

        self._widget = None
        self._button = None
        self._message_area = None
        self._message_labels = None
        self._hint_table = None

        # 2. 1項目分の領域を作成
        self._row_area = ctk.CTkFrame(parent, fg_color="transparent")
        self._row_area.pack(fill="x", pady=(0, 15))

        # 3. 見出しが存在する場合はラベルを作成
        if label_text:
            label = ctk.CTkLabel(self._row_area, text=label_text, font=_SYS_FONT)
            label.pack(anchor="w", pady=(0, 5))

        # 4. 入力部品を横並びにする内部領域を作成
        # 見出しが無い場合も作成しておくことで、後から追加する入力部品が補足テキストより上に配置される
        self._content_area = ctk.CTkFrame(self._row_area, fg_color="transparent")
        self._content_area.pack(fill="x")

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

    def add_label(self, text=""):
        """
        状態などを表示するラベルを追加する

        Args:
            text (str, optional): 表示するテキスト

        Returns:
            _SettingRowBuilder: self（メソッドチェーン用）
        """
        # ラベルを作成し、右側に追加するボタンと横並びにするため左寄せで配置
        label = ctk.CTkLabel(self._content_area, text=text, font=_SYS_FONT, anchor="w")
        label.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # ラベルの参照を保持
        self._widget = label

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

    def add_hint(self, description, term=None):
        """
        項目下部に補足テキストを1件追加する
        用語を指定した場合は用語を左列にそろえ、どの説明がどの用語に対するものかを見分けやすくする

        Args:
            description (str): 補足テキスト（改行区切りで複数行にできる）
            term (str, optional): 説明対象の用語

        Returns:
            _SettingRowBuilder: self（メソッドチェーン用）
        """

        def create_multiline_label(parent, text):
            """
            複数行のテキストを、行間を空けて表示する領域を生成する

            Args:
                parent: 領域を配置する親領域
                text (str): 改行区切りのテキスト

            Returns:
                ctk.CTkFrame: 1行ずつのラベルを縦に並べた領域
            """
            text_area = ctk.CTkFrame(parent, fg_color="transparent")
            # 1行ずつラベルを分け、2行目以降の上に余白を空けて行間を広げる
            for line_index, line_text in enumerate(text.split("\n")):
                line_padding = (0 if line_index == 0 else _HINT_LINE_SPACING, 0)
                line_label = ctk.CTkLabel(text_area, text=line_text, text_color="gray", font=_HINT_FONT, anchor="w", height=0)
                line_label.pack(anchor="w", pady=line_padding)
            return text_area

        # 1. 初回のみ、補足テキストを並べる表を作成
        # バリデーション有効時は、補足テキストが入力欄とエラーメッセージ枠の間に並ぶよう、枠より上に配置する
        if self._hint_table is None:
            self._hint_table = ctk.CTkFrame(self._row_area, fg_color="transparent")
            if self._message_area is not None:
                self._hint_table.pack(anchor="w", pady=(_HINT_TOP_SPACING, 0), before=self._message_area)
            else:
                self._hint_table.pack(anchor="w", pady=(_HINT_TOP_SPACING, 0))

        # 2. 表の末尾の行に追加し、2件目以降は上に余白を空けて要素の切れ目を分かりやすくする
        row_index = self._hint_table.grid_size()[1]
        row_padding = (0 if row_index == 0 else _HINT_ITEM_SPACING, 0)

        # 3. 用語があれば左列に用語、右列に説明を配置
        # 用語が無い説明は、用語列の幅に引きずられず左端から表示するよう2列分を使う
        if term is not None:
            term_label = ctk.CTkLabel(self._hint_table, text=term, text_color="gray", font=_HINT_FONT, anchor="nw", height=0)
            term_label.grid(row=row_index, column=0, sticky="nw", padx=(0, 10), pady=row_padding)
            description_area = create_multiline_label(self._hint_table, description)
            description_area.grid(row=row_index, column=1, sticky="nw", pady=row_padding)
        else:
            description_area = create_multiline_label(self._hint_table, description)
            description_area.grid(row=row_index, column=0, columnspan=2, sticky="nw", pady=row_padding)

        # 自身を返す（メソッドチェーン用）
        return self

    def add_validate(self, on_validate=None):
        """
        バリデーション機能を有効化し、エラーメッセージ表示用の枠を配置する
        メッセージ表示時に下の要素が押し下げられて画面がガタつく（レイアウトシフト）のを防ぐため、領域を常時確保する

        Args:
            on_validate (callable, optional): フォーカスアウト時に実行するバリデーション関数

        Returns:
            _SettingRowBuilder: self（メソッドチェーン用）
        """
        # 1. バリデーション機能を有効化
        self._has_validation = True
        self._on_validate = on_validate

        # 2. 検証メッセージ表示用の枠をあらかじめ確保して配置
        self._message_area = ctk.CTkFrame(self._row_area, fg_color="transparent")
        self._message_area.pack(anchor="w", pady=(_HINT_TOP_SPACING, 0))

        # 3. 上限行数分の空のラベルを並べ、メッセージが無い時も高さを確保する
        # Tkのラベルは行間を指定できないため、1行ずつラベルを分けて補足テキストと同じ行間にする
        self._message_labels = []
        for line_index in range(_VALIDATION_MESSAGE_LINES):
            line_padding = (0 if line_index == 0 else _HINT_LINE_SPACING, 0)
            line_label = ctk.CTkLabel(self._message_area, text="", font=_HINT_FONT, anchor="w", height=0)
            line_label.pack(anchor="w", pady=line_padding)
            self._message_labels.append(line_label)

        # 自身を返す（メソッドチェーン用）
        return self

    def build(self):
        """
        設定項目行を完成させ、構成要素をまとめて返す
        バリデーション対象の入力欄が存在する場合はフォーカスアウト時の検証イベントを自動バインドする

        Returns:
            SettingRow: 設定キー・入力ウィジェット・検証メッセージのラベル・ボタンの組
        """
        # バリデーション対象かつコールバックと入力欄が存在する場合、フォーカスアウト時に検証を自動実行
        if self._has_validation and self._on_validate and isinstance(self._widget, ctk.CTkEntry):
            self._widget.bind("<FocusOut>", lambda event: self._on_validate())

        return SettingRow(key=self._key, widget=self._widget, message_labels=self._message_labels, button=self._button)


# ============================================================
# 設定画面
# ============================================================

# 設定キーの接頭辞に対応するタブ名（タブの生成と、入力エラーがあるタブの案内に使用する）
_TAB_NAMES_BY_KEY_PREFIX = {
    "capture": "撮影",
    "save": "保存",
    "notify": "Windows機能",
    "update": "バージョン情報",
}


class SettingsWindow(ctk.CTk):
    """
    設定画面のGUIを構築・制御するクラス
    """

    # ------------------------------------------------------------
    # 画面の構築
    # ------------------------------------------------------------

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
        self._shortcut_recorder = None

        # ドロップダウンで表示文言から選ばせる設定項目の対応表（設定キー → {保存値: 表示文言}）
        # 各項目の追加関数が自分の対応表を登録し、_get_widget_value() で表示文言から保存値へ変換する
        self._option_labels_by_key = {}

        # 適用・保存ボタンと入力エラー案内ラベルの参照を保持（バリデーション結果で表示を制御するため）
        self._button_apply = None
        self._button_save = None
        self._validation_summary_label = None

        # 1. ウィンドウのタイトル・サイズを設定
        self.title(f"{constants.APP_NAME} 設定")
        self.geometry(f"{_WINDOW_WIDTH}x{_WINDOW_HEIGHT}")
        self.resizable(False, False)

        # 2. ウィンドウアイコン・タスクバーアイコンの設定
        # WindowsのタスクバーでPython標準アイコンになるのを防ぐため、固有AppUserModelID(AUMID)を設定
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(constants.APP_SETTINGS_USER_MODEL_ID)
        # 実行形態とバージョンに対応するアイコンを取得・設定
        icon_path = paths.get_icon_path(version.APP_VERSION, is_development=not paths.is_executable())
        self.iconbitmap(icon_path)

        # 3. 外観を設定し、Windowsのアクセントカラーとホバー色を取得
        ctk.set_appearance_mode(_APPEARANCE_MODE)
        self._accent_color, self._hover_color = windows_shell.get_windows_accent_colors(_FALLBACK_ACCENT_COLOR)

        # 4. 下部の操作ボタン領域を先に配置する
        # （上部のコンテンツの高さが増減しても、下部ボタン領域が押しつぶされて縮小するのを防ぐため）
        self._build_button_area()

        # 5. 設定項目を並べるタブ領域を配置する
        self._build_tab_area()

        # 6. 初期表示時にバリデーションを実行する
        self._run_validation()

    def _build_button_area(self):
        """
        設定画面に適用・保存・キャンセルの各操作ボタンを配置する
        """
        # 1. ボタン用領域（画面下部に配置）
        buttons_area = ctk.CTkFrame(self, fg_color="transparent")
        buttons_area.pack(side="bottom", fill="x", pady=(5, 20))

        # 2. 表示中でないタブの入力エラーに気付けるよう、エラーのあるタブ名をボタンの上に案内するラベル
        # 表示時にボタンが押し下げられないよう、エラーが無い時も高さを確保しておく
        self._validation_summary_label = ctk.CTkLabel(
            buttons_area,
            text="",
            text_color=_ERROR_TEXT_COLOR,
            font=_HINT_FONT,
            height=18,
        )
        self._validation_summary_label.pack(pady=(0, 5))

        # 3. 全体を中央揃えにするためのダミー領域を利用しつつ、packで配置
        inner_area = ctk.CTkFrame(buttons_area, fg_color="transparent")
        inner_area.pack(anchor="center")

        # 4. 適用・保存・キャンセルのボタンを左から並べる
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

    def _build_tab_area(self):
        """
        設定項目を分類して表示するタブ領域を配置し、タブを1つずつ作成してその設定項目を追加する
        """
        # 1. タブ領域を配置する（余白を持たせる）
        # タブの切り替えボタンは既定だと中央寄せの並んだボタンに見えるため、左寄せにし、
        # 未選択のタブと枠の色をタブ領域と同じ色にすることで、選択中のタブだけが浮き出るタブらしい見た目にする
        tab_area_color = ctk.ThemeManager.theme["CTkFrame"]["fg_color"]
        tab_view = ctk.CTkTabview(
            self,
            anchor="w",
            fg_color=tab_area_color,
            segmented_button_fg_color=tab_area_color,
            segmented_button_unselected_color=tab_area_color,
            segmented_button_selected_color=self._accent_color,
            segmented_button_selected_hover_color=self._hover_color,
            segmented_button_font=_TAB_FONT,
        )
        tab_view.pack(fill="both", expand=True, padx=20, pady=(10, 0))

        # 2. 「撮影」タブを作成し、設定項目を追加
        capture_tab = tab_view.add(_TAB_NAMES_BY_KEY_PREFIX["capture"])
        self._add_shortcut_field(capture_tab)
        self._add_volume_field(capture_tab)

        # 3. 「保存」タブを作成し、設定項目を追加
        save_tab = tab_view.add(_TAB_NAMES_BY_KEY_PREFIX["save"])
        self._add_directory_field(save_tab)
        self._add_filename_preset_field(save_tab)
        self._add_metadata_toggle_field(save_tab)

        # 4. 「Windows機能」タブを作成し、設定項目を見出しで区切って追加
        windows_tab = tab_view.add(_TAB_NAMES_BY_KEY_PREFIX["notify"])
        self._add_section_heading(windows_tab, "スタートアップ")
        self._add_startup_field(windows_tab)
        self._add_section_heading(windows_tab, "Windows通知")
        self._add_capture_notification_field(windows_tab)
        self._add_app_event_notification_field(windows_tab)
        self._add_error_notification_field(windows_tab)

        # 5. 「バージョン情報」タブを作成し、アップデートの確認とアプリの情報を見出しで区切って追加
        update_tab = tab_view.add(_TAB_NAMES_BY_KEY_PREFIX["update"])
        self._add_section_heading(update_tab, "アップデート")
        self._add_update_check_mode_field(update_tab)
        self._add_update_check_now_field(update_tab)
        self._add_section_heading(update_tab, "このアプリについて")
        self._add_about_field(update_tab)

    def _create_row_builder(self, tab_frame, key, label_text=None):
        """
        設定項目ビルダーを生成するヘルパー関数
        設定画面の入力で検証エラーが起こりうるかを settings から判定し、対象項目の場合は自動でバリデーションを有効化する

        Args:
            tab_frame: 設定項目を配置するタブの領域
            key (str): 設定キー
            label_text (str, optional): 画面に表示する見出しテキスト

        Returns:
            _SettingRowBuilder: 行ビルダーのインスタンス
        """
        # 1. アクセントカラーを引き継いだ行ビルダーを生成
        builder = _SettingRowBuilder(
            parent=tab_frame,
            key=key,
            label_text=label_text,
            accent_color=self._accent_color,
            hover_color=self._hover_color,
        )
        # 2. 入力で検証エラーが起こりうる項目のみ、エラー表示枠を確保してバリデーションを有効化
        if settings.can_fail_input_validation(key):
            builder.add_validate(on_validate=self._run_validation)

        return builder

    def _add_section_heading(self, tab_frame, text):
        """
        タブ内の設定項目を区切る見出しを追加する

        Args:
            tab_frame: 見出しを配置するタブの領域
            text (str): 見出しテキスト
        """
        heading_label = ctk.CTkLabel(tab_frame, text=text, font=_HEADING_FONT)
        heading_label.pack(anchor="w", pady=(0, 5))

    # ------------------------------------------------------------
    # 設定項目の追加（1関数で1項目。タブ内の表示順に並べる）
    # ------------------------------------------------------------

    def _add_shortcut_field(self, tab_frame):
        """ショートカットキー設定項目を追加する"""
        key = "capture.triggerShortcut"

        # 記録ボタン押下時の処理
        def record_shortcut():
            entry = setting_row.widget
            button = setting_row.button
            previous_value = entry.get()

            def _finish_recording(result_value):
                # 1. 低レベルキーボードフックを解除して入力待ち状態を終了
                if self._shortcut_recorder:
                    self._shortcut_recorder.stop()
                    self._shortcut_recorder = None

                # 2. 入力欄を編集可能に戻し、記録結果（キャンセル時は記録前の値）を入れる
                entry.configure(state="normal")
                entry.delete(0, "end")
                entry.insert(0, result_value)
                # 3. 入力完了後にバリデーションを実行し適用・保存ボタンの状態を更新、記録ボタンを元に戻す
                self._run_validation()
                button.configure(state="normal", text="キーを記録", command=record_shortcut)

            # キー押下検知時のコールバック
            def _on_key_captured(captured_shortcut):
                # メインスレッドで安全にUIを更新
                self.after(0, lambda: _finish_recording(captured_shortcut))

            # キャンセル時のコールバック
            def _on_cancelled():
                # メインスレッドで元の値に戻す
                self.after(0, lambda: _finish_recording(previous_value))

            # 1. 入力欄に案内文を表示し、記録中は編集できないようにする
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, "キーを押してください（Escでキャンセル）")
            entry.configure(state="disabled")

            # 2. 記録中は入力欄に案内文が入っているため、案内文がショートカットとして保存されないよう適用・保存ボタンを無効化する
            # （記録終了時の _run_validation() で、検証結果に応じた状態に戻る）
            self._button_apply.configure(state="disabled")
            self._button_save.configure(state="disabled")

            # 3. ボタンを「キャンセル」に切り替え、再クリックで安全に中断できるように設定
            button.configure(state="normal", text="キャンセル", command=lambda: _finish_recording(previous_value))

            # 4. 既存のレコーダーが残っていれば念のため停止
            if self._shortcut_recorder:
                self._shortcut_recorder.stop()

            # 5. 低レベルフック（WH_KEYBOARD_LL）を開始
            # PrintScreenやAltキーなどのシステムキーも確実に捕捉し、
            # 既存の登録済みホットキーによる撮影発火を防ぎながら安全に記録する
            self._shortcut_recorder = hotkey.Recorder(
                on_captured=_on_key_captured,
                on_cancelled=_on_cancelled,
            )
            self._shortcut_recorder.start()

        setting_row = (
            self._create_row_builder(tab_frame=tab_frame, key=key, label_text="ショートカットキー:")
            .add_entry(initial_value=settings.get(key))
            .add_button(text="キーを記録", width=100, command=record_shortcut)
            .add_hint("記録ボタン押下後、設定したいキーを押してください。\nEscキーまたはキャンセルボタンで中断")
            .build()
        )
        self._setting_items[key] = setting_row

    def _add_volume_field(self, tab_frame):
        """音量設定項目を追加する"""
        key = "capture.soundVolume"

        # 1. 音量の選択肢（保存値 → 表示文言）を登録する。0%〜100%を10%刻みで選ばせる
        volume_labels = {volume: f"{volume}%" if volume > 0 else "0% (無音)" for volume in range(0, 101, 10)}
        self._option_labels_by_key[key] = volume_labels

        # 2. 現在の設定値を表示文言に変換（選択肢に無い値の場合は「100%」を表示）
        initial_label = volume_labels.get(settings.get(key), volume_labels[100])

        # テスト再生ボタン（保存前でも画面上の選択値で再生する）
        def test_sound():
            capture.play_capture_sound(volume=self._get_widget_value(setting_row))

        # 3. ドロップダウンとテスト再生ボタンを配置する
        setting_row = (
            self._create_row_builder(tab_frame=tab_frame, key=key, label_text="撮影時の通知音量:")
            .add_option_menu(values=list(volume_labels.values()), initial_value=initial_label)
            .add_button(text="テスト再生", width=100, command=test_sound)
            .build()
        )
        self._setting_items[key] = setting_row

    def _add_directory_field(self, tab_frame):
        """保存先フォルダ設定項目を追加する"""
        key = "save.directory"

        def browse_directory():
            # 1. 初期表示フォルダ：入力があればそのフォルダを展開、無ければユーザーフォルダを表示
            entry = setting_row.widget
            initial_dir = paths.expand_path(entry.get())
            if not os.path.exists(initial_dir):
                initial_dir = paths.expand_path("~")
            # 2. フォルダ選択ダイアログを表示
            selected_dir = filedialog.askdirectory(initialdir=initial_dir, title="フォルダを選択")
            # 3. フォルダが選択された場合は、Windows 形式の区切り文字にして入力欄に反映
            if selected_dir:
                selected_dir = selected_dir.replace("/", "\\")
                entry.delete(0, "end")
                entry.insert(0, selected_dir)
                # 検証は入力欄のフォーカスアウト時に走るため、ダイアログでの選択直後にも実行してパス長の警告などを即時表示する
                self._run_validation()

        setting_row = (
            self._create_row_builder(tab_frame=tab_frame, key=key, label_text="保存先フォルダ:")
            .add_entry(initial_value=settings.get(key))
            .add_button(text="参照...", width=80, command=browse_directory)
            .build()
        )
        self._setting_items[key] = setting_row

    def _add_filename_preset_field(self, tab_frame):
        """ファイル名プリセット設定項目を追加する"""
        key = "save.filenamePreset"
        self._setting_items[key] = (
            self._create_row_builder(tab_frame=tab_frame, key=key, label_text="ファイル名プリセット:")
            .add_entry(initial_value=settings.get(key))
            # 画面幅に収まるよう、説明は1行を短く区切る
            .add_hint(
                "撮影日時\n{timestamp:(書式)} で書式を指定できます。\n%f でマイクロ秒を出力できます。\n例: {timestamp:%Y%m%d_%H%M%S_%f}",
                term="{timestamp}",
            )
            .add_hint("ウィンドウタイトル", term="{title}")
            .add_hint("保存先で重複しない連番\n{index:0(桁数)} で0埋めが可能です。\n例: {index:03}", term="{index}")
            .add_hint(
                "同名ファイルがある時のみ付く連番（既定: 「 (2)」）\n{dup:(書式)} で書式を指定できます。%d が番号です。\n例: {dup:_%d}\n{dup:(書式):(番号)} で2件目の番号を指定できます。\n例: {dup:_%d:1}",
                term="{dup}",
            )
            .build()
        )

    def _add_metadata_toggle_field(self, tab_frame):
        """撮影日時のEXIFメタデータ埋め込み設定スイッチを追加する"""
        key = "save.embedDatetimeMetadata"
        self._setting_items[key] = (
            self._create_row_builder(tab_frame=tab_frame, key=key)
            .add_switch(
                text="撮影日時をメタデータ（EXIF / PNG）に埋め込む",
                is_selected=bool(settings.get(key)),
            )
            .build()
        )

    def _add_startup_field(self, tab_frame):
        """
        Windows起動時の自動起動を登録・解除する項目を追加する
        登録状態は settings.json ではなくショートカットの有無で管理するため、適用・保存とは切り離してボタン押下時に即時反映する
        """
        # 1. 登録状態ごとの (状態ラベルの文言, ボタンの文言)
        display_texts_by_status = {
            startup.StartupStatus.UNREGISTERED: ("登録されていません", "登録する"),
            startup.StartupStatus.ENABLED: ("登録されています", "解除する"),
            startup.StartupStatus.DISABLED_BY_WINDOWS: ("Windowsの設定で無効になっています", "解除する"),
        }

        # 現在の登録状態を読み取り、状態ラベルとボタンの文言を更新する
        def refresh_display():
            status_text, button_text = display_texts_by_status[startup.get_status()]
            setting_row.widget.configure(text=status_text)
            setting_row.button.configure(text=button_text)

        # 未登録なら登録、登録済み（Windows側で無効な場合を含む）なら解除し、結果を表示に反映する
        def toggle_registration():
            if startup.get_status() == startup.StartupStatus.UNREGISTERED:
                startup.register()
            else:
                startup.unregister()
            refresh_display()

        # 2. 状態ラベルと登録・解除ボタンを配置する（適用・保存の対象外とするため、_setting_items には登録しない）
        setting_row = (
            self._create_row_builder(tab_frame=tab_frame, key="startup", label_text="Windows起動時の自動起動:")
            .add_label()
            .add_button(text="登録する", width=100, command=toggle_registration)
            .add_hint(
                "ボタンを押した時点で反映されます。Windows側で無効になっている場合は、\nタスクマネージャーの「スタートアップ アプリ」から有効にしてください。"
            )
            .build()
        )

        # 3. 開発時は開発環境が登録されてしまうのを防ぐため、操作できないようにする
        if not paths.is_executable():
            setting_row.widget.configure(text="exe実行時のみ設定できます。")
            setting_row.button.configure(state="disabled")
            return

        # 4. 現在の登録状態を表示する
        refresh_display()

    def _add_capture_notification_field(self, tab_frame):
        """撮影時のWindows通知の設定スイッチを追加する"""
        key = "notify.onCapture"
        self._setting_items[key] = (
            self._create_row_builder(tab_frame=tab_frame, key=key)
            .add_switch(
                text="撮影時に通知する",
                is_selected=bool(settings.get(key)),
            )
            .build()
        )

    def _add_app_event_notification_field(self, tab_frame):
        """起動・終了時やショートカットキー変更時のWindows通知の設定スイッチを追加する"""
        key = "notify.onAppEvent"
        self._setting_items[key] = (
            self._create_row_builder(tab_frame=tab_frame, key=key)
            .add_switch(
                text="起動・終了時やショートカットキー変更時に通知する",
                is_selected=bool(settings.get(key)),
            )
            .build()
        )

    def _add_error_notification_field(self, tab_frame):
        """エラー発生時のWindows通知の設定スイッチを追加する"""
        key = "notify.onError"
        self._setting_items[key] = (
            self._create_row_builder(tab_frame=tab_frame, key=key)
            .add_switch(
                text="エラー発生時に通知する",
                is_selected=bool(settings.get(key)),
            )
            .add_hint("オフにすると、撮影の失敗などはログファイルでのみ確認できます。")
            .build()
        )

    def _add_update_check_mode_field(self, tab_frame):
        """アップデート確認の対象範囲を選ぶドロップダウンを追加する"""
        key = "update.checkMode"

        # 1. 対象範囲の選択肢（保存値 → 表示文言）を登録する
        # 保存値は型チェック（str）を通るよう、列挙型ではなく文字列の値をキーにする
        check_mode_labels = {
            updater.UpdateCheckMode.DISABLED.value: "確認しない",
            updater.UpdateCheckMode.STABLE.value: "正式版のみ確認する",
            updater.UpdateCheckMode.PRERELEASE.value: "ベータ版も確認する",
        }
        self._option_labels_by_key[key] = check_mode_labels

        # 2. 現在の設定値を表示文言に変換（未定義の値の場合はデフォルトの「正式版のみ」を表示）
        initial_label = check_mode_labels.get(settings.get(key), check_mode_labels[updater.UpdateCheckMode.STABLE.value])

        # 3. ドロップダウンを配置する
        self._setting_items[key] = (
            self._create_row_builder(tab_frame=tab_frame, key=key, label_text="起動時のアップデート確認:")
            .add_option_menu(values=list(check_mode_labels.values()), initial_value=initial_label)
            .add_hint("新しいバージョンが公開されている場合に通知します。")
            .build()
        )

    def _add_update_check_now_field(self, tab_frame):
        """
        新しいバージョンをその場で確認し、結果を画面内に表示する項目を追加する
        「確認しない」設定や通知オフでも結果が分かるよう、Windows通知ではなく画面内のラベルに表示する
        外部APIへの問い合わせを必要な時に限るため、画面を開いた時には確認せず、ボタンを押した時だけ確認する
        確認範囲のドロップダウンを切り替えた時は、updater が保持する取得済みのリリース一覧から選び直す（通信しない）
        """
        # 結果を表示済みか（「今すぐ確認」を押す前のドロップダウンの切り替えでは、通信を伴う確認をしないため）
        has_checked_update = False

        # 画面上の確認範囲（保存前の選択値）が、beta版も含む設定かを判定する
        def is_prerelease_selected():
            return self._get_widget_value(self._setting_items["update.checkMode"]) == updater.UpdateCheckMode.PRERELEASE

        # 通信で画面が固まらないよう、別スレッドでリリース一覧を取得し直して確認する
        def start_check():
            setting_row.widget.configure(text="確認しています...", text_color=default_text_color)
            setting_row.button.configure(state="disabled")
            threading.Thread(target=run_check, args=(is_prerelease_selected(),), daemon=True).start()

        # 別スレッドで確認を実行し、結果の表示はメインスレッドに戻して行う
        def run_check(include_prerelease):
            try:
                result = updater.get_latest_release(include_prerelease, refetch=True)
            except Exception as exception:
                result = exception
            try:
                self.after(0, lambda: show_result(result))
            except Exception:
                # 確認中に画面が閉じられた場合は表示先が無いため何もしない（RuntimeError / TclError のどちらにもなり得る）
                pass

        # 確認結果に応じてラベルとボタンを切り替える
        # 新しいバージョンがあればボタンでリリースページを開けるようにし、無い場合と失敗時は「今すぐ確認」に戻して確認し直せるようにする
        # 新しいバージョンが無い場合も、比べた相手が分かるよう公開中の最新版を表示する
        # （最新の正式版より新しいbeta版を使っている場合もあるため、「最新版を使用しています」とは表示しない）
        def show_result(result):
            nonlocal has_checked_update
            if isinstance(result, Exception):
                # 例外メッセージは長くボタンを押し出してしまうため、詳細はログに出力する
                notifier.log(f"アップデートの確認に失敗しました。\n{result}")
                setting_row.widget.configure(text="確認に失敗しました。(詳細はログを参照)", text_color=_ERROR_TEXT_COLOR)
                setting_row.button.configure(state="normal", text="今すぐ確認", command=start_check)
                return

            has_checked_update = True
            if result is None:
                setting_row.widget.configure(text="新しいバージョンはありません。", text_color=default_text_color)
                setting_row.button.configure(state="normal", text="今すぐ確認", command=start_check)
            elif not result.is_newer:
                setting_row.widget.configure(text=f"新しいバージョンはありません。（最新: {result.tag}）", text_color=default_text_color)
                setting_row.button.configure(state="normal", text="今すぐ確認", command=start_check)
            else:
                setting_row.widget.configure(text=f"{result.tag} が公開されています。", text_color=default_text_color)
                setting_row.button.configure(
                    state="normal", text="リリースページを開く", command=lambda: webbrowser.open(updater.get_release_page_url(result.tag))
                )

        # 確認範囲のドロップダウンを切り替えた時、確認済みであれば取得済みの一覧から選び直して表示する
        # （選択された表示文言が引数で渡されるが、保存値への変換を共通化するため _get_widget_value() で取り直す）
        def refresh_on_mode_change(selected_label):
            if not has_checked_update:
                return
            try:
                result = updater.get_latest_release(is_prerelease_selected())
            except Exception as exception:
                result = exception
            show_result(result)

        # 1. 確認結果の表示と確認ボタンを配置する（適用・保存の対象外とするため、_setting_items には登録しない）
        # 現在のバージョンは「このアプリについて」に常に表示するため、ここでは確認結果だけを表示する
        setting_row = (
            self._create_row_builder(tab_frame=tab_frame, key="updateCheckNow", label_text="新しいバージョン:")
            .add_label(text="まだ確認していません。")
            .add_button(text="今すぐ確認", width=120, command=start_check)
            .build()
        )

        # 2. 失敗表示のエラー色から戻すため、既定の文字色を控えておく
        default_text_color = setting_row.widget.cget("text_color")

        # 3. 確認範囲のドロップダウン（この項目より先に追加済み）に、切り替え時の処理を設定する
        self._setting_items["update.checkMode"].widget.configure(command=refresh_on_mode_change)

    def _add_about_field(self, tab_frame):
        """
        アプリのバージョン・著作権表示・GitHub のリンクを表示する項目を追加する
        新しいバージョンの確認結果とは別に表示し、確認した後も現在のバージョンが分かるようにする
        """
        # 1. 項目を縦に並べる領域を作成
        about_area = ctk.CTkFrame(tab_frame, fg_color="transparent")
        about_area.pack(fill="x", pady=(0, 15))

        # 2. バージョンと著作権表示を表示
        for text in (f"バージョン: {version.APP_VERSION}", constants.COPYRIGHT):
            ctk.CTkLabel(about_area, text=text, font=_SYS_FONT, anchor="w").pack(anchor="w")

        # 3. GitHub のリポジトリをリンクとして表示し、クリックでブラウザを開く
        # リンクと分かるよう、リンク色の文字と手の形のカーソルにする
        link_label = ctk.CTkLabel(
            about_area,
            text=f"GitHub: {constants.REPOSITORY_URL}",
            font=_SYS_FONT,
            text_color=_LINK_TEXT_COLOR,
            cursor="hand2",
            anchor="w",
        )
        link_label.pack(anchor="w")
        link_label.bind("<Button-1>", lambda event: webbrowser.open(constants.REPOSITORY_URL))

    # ------------------------------------------------------------
    # 入力値の検証・保存
    # ------------------------------------------------------------

    def _run_validation(self):
        """
        全設定項目のバリデーションを実行し、エラー・警告の表示とボタン状態を更新する
        検証メッセージのラベルはあらかじめ枠を確保して配置されているため、テキストの更新のみを行いレイアウトのズレを防ぐ
        """

        def show_message(setting_row, message, text_color=_ERROR_TEXT_COLOR):
            """
            設定項目の検証メッセージを表示する（空文字の場合は消去する）

            Args:
                setting_row (SettingRow): 表示先の設定項目
                message (str): 改行区切りのメッセージ
                text_color (str, optional): 文字色
            """
            # 改行ごとに各行のラベルへ割り当て、上限行数を超えた分は最終行にまとめて表示する
            message_lines = message.split("\n", _VALIDATION_MESSAGE_LINES - 1) if message else []
            for line_index, line_label in enumerate(setting_row.message_labels):
                line_text = message_lines[line_index] if line_index < len(message_lines) else ""
                line_label.configure(text=line_text, text_color=text_color)

        # 1. バリデーション対象の全項目の値を保存値の形式で集め、エラーと警告を一括取得する
        # 保存先フォルダとファイル名の組み合わせで決まるパス長も検証するため、項目単位ではなく一括で行う
        validation_rows = {key: setting_row for key, setting_row in self._setting_items.items() if setting_row.message_labels is not None}
        values = {key: self._get_widget_value(setting_row) for key, setting_row in validation_rows.items()}
        validation_results = settings.validate_all(values)

        # 2. 項目ごとにエラー・警告を表示しつつ、エラーのあるタブ名を集める
        error_tab_names = []
        for key, setting_row in validation_rows.items():
            result = validation_results.get(key)
            if result is None:
                show_message(setting_row, "")
            elif result.is_error:
                show_message(setting_row, result.message, text_color=_ERROR_TEXT_COLOR)
                # 設定キーの接頭辞（例: "save.directory" の "save"）から所属タブ名を求める
                tab_name = _TAB_NAMES_BY_KEY_PREFIX[key.split(".")[0]]
                if tab_name not in error_tab_names:
                    error_tab_names.append(tab_name)
            else:
                # 警告は保存を妨げないため、タブ案内やボタン状態には反映しない
                show_message(setting_row, result.message, text_color=_WARNING_TEXT_COLOR)

        # 3. エラーのあるタブ名をボタン上部に案内する（例: 「撮影」「保存」タブに入力エラーがあります。）
        has_error = bool(error_tab_names)
        summary_text = ""
        if has_error:
            summary_text = "".join(f"「{tab_name}」" for tab_name in error_tab_names) + "タブに入力エラーがあります。"
        self._validation_summary_label.configure(text=summary_text)

        # 4. エラーがある場合は適用・保存ボタンを非活性にする
        state = "disabled" if has_error else "normal"
        self._button_apply.configure(state=state)
        self._button_save.configure(state=state)

    def _get_widget_value(self, setting_row):
        """
        設定項目のウィジェットから現在の値を取得し、設定ファイルに保存する形式へ変換する
        バリデーションと保存で同じ値を扱うため、表示文言から保存値への変換をここに集約する

        Args:
            setting_row (SettingRow): 対象の設定項目行

        Returns:
            設定ファイルに保存する形式の値
        """
        # 1. ウィジェットから現在の値を取得
        value = setting_row.widget.get()

        # 2. CTkSwitch の場合は 0/1 が返るため bool に変換する
        if isinstance(setting_row.widget, ctk.CTkSwitch):
            return bool(value)

        # 3. ドロップダウンで選ばせる項目は、表示文言から保存値に変換する（該当しない場合はバリデーションでエラーにするため元の値を返す）
        for saved_value, label in self._option_labels_by_key.get(setting_row.key, {}).items():
            if label == value:
                return saved_value

        return value

    def _apply_settings(self):
        """
        現在の入力を設定ファイルに保存する。画面はそのまま維持される
        """
        # 1. UI上の全ての入力値を保存値の形式に変換して settings オブジェクトに反映させる
        for key, setting_row in self._setting_items.items():
            settings.set(key, self._get_widget_value(setting_row))

        # 2. 設定ファイルに保存する
        settings.save()

        # 3. mainプロセスへ設定変更を通知し、ログに残す
        if self.update_event is not None:
            self.update_event.set()

        notifier.log("設定を適用しました。")

    def _save_settings(self):
        """
        現在の入力を設定ファイルに保存し、画面を閉じる
        """
        self._apply_settings()
        self.destroy()

    # ------------------------------------------------------------
    # 後片付け
    # ------------------------------------------------------------

    def destroy(self):
        """
        設定画面破棄時のクリーンアップ処理
        キー記録中の低レベルフックが残っていれば確実に解除する
        """
        if hasattr(self, "_shortcut_recorder") and self._shortcut_recorder is not None:
            self._shortcut_recorder.stop()
            self._shortcut_recorder = None
        super().destroy()


# ============================================================
# 設定画面プロセスの起動
# ============================================================

# 開いている設定画面のプロセス
_settings_process = None

# メインプロセスへ設定変更（ホットキー再登録など）を通知するためのイベント
settings_update_event = multiprocessing.Event()


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
        # 1. すでに設定画面が開いている場合は多重起動しない
        if _settings_process is not None and _settings_process.is_alive():
            return

        # 2. 設定画面を別プロセスで起動する（常駐側のトレイ・ホットキーの処理を止めないため）
        _settings_process = multiprocessing.Process(target=_run_settings_window_process, args=(settings_update_event,), daemon=True)
        _settings_process.start()
    except Exception as exception:
        # エラー通知・ログ出力
        notifier.error("設定画面の起動に失敗しました。", f"エラーが発生しました。\n{exception}")


# このファイルを直接起動した際に設定画面を表示する
if __name__ == "__main__":
    _run_settings_window_process()
