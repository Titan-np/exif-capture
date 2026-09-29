# EXIF Capture テスト仕様書

本ドキュメントでは、EXIF Capture のテスト方針、自動テスト(UT)・手動テストの観点・ケース・実行方法について記載する。

---

# 1. テスト方針

本アプリケーションのテストは以下の2つで構成する。

- 自動テスト: 単体テスト(UT)レベルで、pytestを用いて自動で検証する。
- 手動テスト: 自動テストではカバーできない動作（画面キャプチャ、GUI操作、トレイ常駐、通知表示など）を手動で検証する。

# 2. 自動テスト

リリース前のリグレッション検知等を目的とし、 pytest で確認可能なモジュールは自動テストの対象とする。

## 2.1 実行方法

前提環境はアプリケーション本体と同様。
リポジトリルート直下で以下のコマンドを実行する。

```bash
# 依存パッケージが未インストールであれば、インストールする
pip install pytest

# 全テストを詳細表示で実行
python -m pytest tests/ -v

# 特定のテストモジュールのみを実行
python -m pytest tests/test_settings_manager.py -v
python -m pytest tests/test_hotkey_manager.py -v
python -m pytest tests/test_capture.py -v
python -m pytest tests/test_utils.py -v
python -m pytest tests/test_version.py -v
```

## 2.2 テスト観点

| モジュール       | テスト観点                                                                 |
| ---------------- | -------------------------------------------------------------------------- |
| settings_manager | 入力値検証、破損ファイルの自己復旧、旧キー移行、アトミック書き込み         |
| hotkey_manager   | ショートカット文字列の構文解析、仮想キーコード解決、妥当性判定             |
| capture          | ファイル名プレースホルダ展開、禁止文字置換、パス長制限、EXIFメタデータ付与 |
| utils            | チルダ展開、環境変数展開、アプリパス解決                                   |
| version          | 環境変数・git describe・フォールバックによるバージョン解決                 |

## 2.3 テストケース一覧

### test_settings_manager.py

**TestValidation（バリデーション検証）**

| テストケース                                                | 検証内容                                                   |
| ----------------------------------------------------------- | ---------------------------------------------------------- |
| test_validate_not_empty_rejects_empty                       | 空文字列でエラーを返すこと                                 |
| test_validate_not_empty_rejects_whitespace                  | 空白のみの文字列でエラーを返すこと                         |
| test_validate_not_empty_rejects_none                        | None でエラーを返すこと                                    |
| test_validate_not_empty_accepts_valid_string                | 正常な文字列で None を返すこと                             |
| test_validate_path_chars_rejects_forbidden_chars            | 禁止文字（< > " \| ? \*）でエラーを返すこと                |
| test_validate_path_chars_rejects_invalid_colon              | ドライブレター以外のコロンでエラーを返すこと               |
| test_validate_path_chars_rejects_invalid_drive_format       | 不正なドライブ形式でエラーを返すこと                       |
| test_validate_path_chars_accepts_valid_paths                | 正常なパス（絶対パス・チルダ・環境変数）で None を返すこと |
| test_validate_filename_chars_rejects_forbidden_chars        | 禁止文字（< > : " / \ \| ? \*）でエラーを返すこと          |
| test_validate_filename_chars_ignores_placeholder_brackets   | プレースホルダ内の記号を誤検知しないこと                   |
| test_validate_shortcut_format_delegates_to_hotkey_manager   | ショートカット検証が hotkey_manager へ正しく委譲されること |
| test_validate_preset_placeholders_accepts_allowed_keys      | 許可済みキー（timestamp, title）で None を返すこと         |
| test_validate_preset_placeholders_rejects_unknown_keys      | 未定義プレースホルダでエラーを返すこと                     |
| test_validate_preset_placeholders_rejects_unbalanced_braces | 不正な波括弧構文でエラーを返すこと                         |
| test_validate_all_returns_errors_for_invalid_entries        | 複数項目の一括バリデーションでエラーを正しく集約すること   |

**TestSettingsManagerIO（ファイル読み書き・リカバリ検証）**

| テストケース                                            | 検証内容                                                |
| ------------------------------------------------------- | ------------------------------------------------------- |
| test_load_creates_default_settings_when_file_not_exists | 設定ファイル不在時にデフォルト値で新規作成されること    |
| test_load_reads_existing_valid_settings                 | 正常な設定ファイルから値を正しく読み込めること          |
| test_load_migrates_old_key_names                        | 旧キー名が新キー名に自動マイグレーションされること      |
| test_load_handles_corrupted_json_and_recovers           | JSON 破損時にバックアップ退避の上デフォルト復旧すること |
| test_load_replaces_invalid_value_with_default           | 不正な設定値がデフォルト値に差し替えられること          |
| test_save_atomic_write_creates_valid_json               | save がアトミック書き込みで正しく保存されること         |
| test_get_and_set_in_memory                              | メモリ上での get / set が期待通り動作すること           |

### test_hotkey_manager.py

**TestParseShortcutString（文字列解析検証）**

| テストケース                             | 検証内容                                           |
| ---------------------------------------- | -------------------------------------------------- |
| test_parse_valid_modifier_and_normal_key | 修飾キー＋英数字の組み合わせが正しく解析されること |
| test_parse_multiple_modifiers            | 複数修飾キーがビット論理和で合成されること         |
| test_parse_special_keys_print_screen     | PrintScreen の各種エイリアスが正しく解決されること |
| test_parse_function_keys                 | F1〜F24 のファンクションキーが正しく解決されること |
| test_parse_numpad_keys                   | テンキーの各キーが正しく解決されること             |
| test_parse_rejects_empty_and_whitespace  | 空文字・空白文字列で None が返ること               |
| test_parse_rejects_trailing_plus         | 末尾プラス記号の未完成文字列で None が返ること     |
| test_parse_rejects_modifier_only         | 修飾キー単体（メインキーなし）で None が返ること   |
| test_parse_rejects_multiple_main_keys    | 複数メインキーで None が返ること                   |
| test_parse_rejects_unknown_key_name      | 未定義キー名で None が返ること                     |

**TestIsValidShortcut（ショートカット妥当性検証）**

| テストケース                                     | 検証内容                            |
| ------------------------------------------------ | ----------------------------------- |
| test_is_valid_shortcut_returns_true_for_valid    | 有効な組み合わせで True を返すこと  |
| test_is_valid_shortcut_returns_false_for_invalid | 無効な組み合わせで False を返すこと |

### test_capture.py

**TestFormattableTimestamp（日時フォーマット検証）**

| テストケース                          | 検証内容                                                       |
| ------------------------------------- | -------------------------------------------------------------- |
| test_default_format_without_specifier | 書式指定なしでデフォルト書式（%Y%m%d\_%H%M%S）が適用されること |
| test_custom_format_with_specifier     | カスタム書式指定が正しく反映されること                         |

**TestGenerateOutputPath（保存先パス生成検証）**

| テストケース                                                | 検証内容                                         |
| ----------------------------------------------------------- | ------------------------------------------------ |
| test_generate_output_path_replaces_forbidden_characters     | ウィンドウタイトルの禁止文字が置換されること     |
| test_generate_output_path_formats_timestamp_and_title       | プリセットに基づきパスが正しく組み立てられること |
| test_generate_output_path_rejects_path_exceeding_max_length | パス長 259 文字超過時に None を返すこと          |
| test_generate_output_path_handles_format_error              | プリセット書式エラー時に None を返すこと         |

**TestGenerateExifMetadata（メタデータ生成検証）**

| テストケース                                                      | 検証内容                                                     |
| ----------------------------------------------------------------- | ------------------------------------------------------------ |
| test_generate_exif_metadata_embeds_modification_time_and_png_info | 更新日時と PNG 作成日時が常時埋め込まれること                |
| test_generate_exif_metadata_embeds_shooting_time_when_enabled     | メタデータ有効時に撮影日時・デジタル化日時が埋め込まれること |
| test_generate_exif_metadata_skips_shooting_time_when_disabled     | メタデータ無効時に撮影日時が埋め込まれないこと               |

### test_utils.py

**TestExpandPath（パス展開検証）**

| テストケース                                | 検証内容                               |
| ------------------------------------------- | -------------------------------------- |
| test_expand_path_with_empty_string          | 空文字列に対して空文字列を返すこと     |
| test_expand_path_with_tilde                 | チルダがユーザーホームに展開されること |
| test_expand_path_with_environment_variables | 環境変数が正しく展開・正規化されること |

**TestAppPaths（パス解決検証）**

| テストケース                                   | 検証内容                                       |
| ---------------------------------------------- | ---------------------------------------------- |
| test_get_app_path_in_development_environment   | 開発環境でリポジトリルート基準のパスを返すこと |
| test_get_asset_path_in_development_environment | 開発環境で assets フォルダ配下のパスを返すこと |

### test_version.py

**TestVersionResolution（バージョン解決検証）**

| テストケース                                          | 検証内容                                        |
| ----------------------------------------------------- | ----------------------------------------------- |
| test_get_app_version_from_custom_environment_variable | EXIF_CAPTURE_VERSION 環境変数から取得できること |
| test_get_app_version_from_github_ref_name             | GITHUB_REF_NAME 環境変数から取得できること      |
| test_get_app_version_from_git_describe                | git describe の出力から取得できること           |
| test_get_app_version_fallback                         | 全手段失敗時にフォールバック文字列を返すこと    |

# 3. 手動テスト

pytest による自動テストでは検証できない範囲について、手動テストを行う。

## 3.1 テスト観点

| 対象領域                             | テスト観点                                                       | 手動実施の理由                                                       |
| ------------------------------------ | ---------------------------------------------------------------- | -------------------------------------------------------------------- |
| main.pyw（アプリ起動・終了）         | トレイ常駐、起動通知、終了処理                                   | トレイ常駐・スレッド管理の統合処理があり、pytestでの試験が困難なため |
| capture_screenshot（キャプチャ統合） | ホットキー押下→撮影→保存→通知の一連フロー、全画面キャプチャ      | 実際の画面描画（GDI / DWM / ImageGrab）・音声再生（MCI）を伴うため   |
| settings_ui.py（設定画面）           | 画面表示、入力操作、バリデーション表示、保存・適用、キー記録     | GUIアプリケーションのため                                            |
| notifier.py（通知・ログ）            | トースト通知表示、ボタンアクション、ログファイル出力             | OSネイティブ機能の確認を要するため                                   |
| hotkey_manager.py（ホットキー登録）  | グローバルホットキー登録、競合時のエラー通知、設定変更時の再登録 | OSネイティブ機能の確認を要するため                                   |

## 3.2 テストケース一覧

### アプリ起動・終了（main.pyw）

| #    | テストケース | 手順                                        | 期待結果                                                                                                                                                                          |
| ---- | ------------ | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M-01 | 正常起動     | main.pyw を実行する                         | 通知領域にアイコンが表示される。右クリックメニューに「設定を開く」「保存先フォルダを開く」「ログファイルを開く」「終了」の4項目が表示される。起動通知（バージョン番号付き）が出る |
| M-02 | 正常終了     | トレイアイコン右クリック→「終了」を選択する | 「終了します。」の通知が表示され、通知領域からアイコンが消える                                                                                                                    |

### キャプチャ（capture.py）

| #    | テストケース         | 手順                                                                                                                                              | 期待結果                                                                                                                            |
| ---- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| M-03 | ウィンドウキャプチャ | メモ帳等のウィンドウを最前面にした状態で、設定済みのショートカットキー（既定: Shift+PrintScreen）を押す                                           | 保存先フォルダにPNGファイルが作成される。ファイル名にウィンドウタイトルが含まれる。通知が表示される                                 |
| M-04 | 全画面キャプチャ     | デスクトップの何もない場所をクリックし、全ウィンドウを非アクティブにした状態でショートカットキーを押す                                            | 保存先フォルダに「FullScreen」を含むファイル名のPNGが作成される                                                                     |
| M-05 | EXIF メタデータ確認  | 設定画面で「撮影日時のEXIFメタデータを埋め込む」を有効にしてキャプチャを実行する。保存されたPNGファイルを右クリック→プロパティ→詳細タブを確認する | 「撮影日時」に撮影時刻が記録されている                                                                                              |
| M-06 | 連続キャプチャ       | ショートカットキーを1秒以内に3回以上素早く連打する                                                                                                | エラーやクラッシュが発生せず、連打回数分のファイルが保存される（ロックにより一部スキップされてもよいが、少なくとも1枚は保存される） |

### 設定画面（settings_ui.py）

| #    | テストケース           | 手順                                                                                                                                       | 期待結果                                                                                             |
| ---- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| M-07 | 設定画面の起動と保存   | トレイメニュー→「設定を開く」で設定画面を開く。保存先フォルダを別のパス（例: C:\Users\<ユーザー名>\Pictures\test）に変更し、「保存」を押す | 設定画面に現在の設定値が表示される。「保存」押下後に画面が閉じ、settings.json に変更が反映されている |
| M-08 | バリデーションエラー   | 保存先フォルダの入力欄に禁止文字（例: `C:\Save<here`）を入力し、別の欄をクリックしてフォーカスを外す                                       | 入力欄の下に赤字でエラーメッセージが表示され、「適用」「保存」ボタンがグレーアウトになる             |
| M-09 | ショートカットキー記録 | 「キーを記録」ボタンを押し、Ctrl+Shift+S を押す。続けて、もう一度「キーを記録」→ Esc を押してキャンセルする                                | 1回目: 入力欄に「ctrl+shift+s」が反映される。2回目: 入力欄が「ctrl+shift+s」（記録前の値）に戻る     |
| M-10 | フォルダ参照と適用     | 「参照...」ボタンでフォルダを選択し、「適用」ボタンを押す                                                                                  | 選択したパスが入力欄に反映される。「適用」後も画面は開いたまま。settings.json に変更が反映されている |
| M-11 | テスト再生             | 音量を「50%」に変更して「テスト再生」ボタンを押す。次に「0% (無音)」に変更して再度押す                                                     | 50%時: 通知音が適度な音量で再生される。0%時: 通知音が鳴らない                                        |

### 通知（notifier.py）

| #    | テストケース       | 手順                                                                                                                                          | 期待結果                                                                                                                     |
| ---- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| M-12 | トースト通知と操作 | 「Windowsの通知を表示する」を有効にしてキャプチャを実行する。表示された通知の「キャプチャした画像を開く」または「保存先フォルダを開く」を押す | Windows のトースト通知が表示される。ボタン押下で画像が既定アプリで開かれる、またはエクスプローラーで保存先フォルダが開かれる |
| M-13 | 通知無効化確認     | 設定画面で「Windowsの通知を表示する」を無効にし、キャプチャを実行する。その後 logs/app.log を確認する                                         | トースト通知は表示されない。app.log に撮影ログがタイムスタンプ付きで記録されている                                           |

### ホットキー登録（hotkey_manager.py）

| #    | テストケース     | 手順                                                                                                                | 期待結果                                                                                                                     |
| ---- | ---------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| M-14 | ホットキー競合   | settings.json の capture.triggerShortcut を「ctrl+c」など他アプリが使用しているキーに直接書き換え、アプリを起動する | 「ショートカットキーの登録に失敗しました」の通知が表示される。トレイアイコンのツールチップに「ホットキー未登録」と表示される |
| M-15 | ホットキー再登録 | M-14 の状態から設定画面を開き、ショートカットキーを「Shift+PrintScreen」等の有効なキーに変更して「適用」を押す      | 「ショートカットキーを変更しました」の通知が表示される。新しいキーでキャプチャが実行できる                                   |
