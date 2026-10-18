# EXIF Capture テスト仕様書

本ドキュメントでは、EXIF Capture のテスト方針、自動テスト(UT)・手動テストの観点・ケース・実行方法について記載する。

---

# 1. テスト方針

本アプリケーションのテストは以下の2つで構成する。

- 自動テスト: 単体テスト(UT)レベルで、pytestを用いて自動で検証する。
- 手動テスト: 自動テストではカバーできない動作（画面キャプチャ、GUI操作、トレイ常駐、通知表示、GitHubとの通信など）を手動で検証する。

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
python -m pytest tests/test_settings.py -v
python -m pytest tests/test_hotkey.py -v
python -m pytest tests/test_capture.py -v
python -m pytest tests/test_filename_preset.py -v
python -m pytest tests/test_notifier.py -v
python -m pytest tests/test_paths.py -v
python -m pytest tests/test_startup.py -v
python -m pytest tests/test_updater.py -v
python -m pytest tests/test_version.py -v
```

## 2.2 テスト観点

| モジュール | テスト観点                                                                         |
| ---------- | ---------------------------------------------------------------------------------- |
| settings   | 入力値検証、保存先パス長の検証と警告、上書きの恐れの警告、破損ファイルの自己復旧、旧キー移行（1つの旧キーの分割を含む）、旧デフォルトのプリセット移行、アトミック書き込み |
| hotkey     | ショートカット文字列の構文解析、仮想キーコード解決、妥当性判定、設定変更時の再登録要否判定 |
| capture    | 禁止文字置換、同名ファイルの回避、パス長制限、EXIFメタデータ付与、撮影の多重実行防止、通知音の音量変換 |
| notifier   | 通知の種別ごとの設定に応じたトースト通知の表示有無、種別指定の必須化、起動時のログファイル世代切り替え |
| startup    | ショートカットの有無とWindows側の無効化記録による登録状態の判定、登録・解除、起動時のショートカット更新、開発時の操作抑止 |
| updater    | タグ名の解析と大小比較、最新リリースの選択、新しいバージョンの有無の確認、起動時の設定に応じたアップデート確認と通知 |
| filename_preset | ファイル名プレースホルダ展開（連番・重複時連番を含む）と保存先パスの組み立て、既存ファイルと被らない連番の探索 |
| paths      | チルダ展開、環境変数展開、アプリパス解決、バージョンに応じたアイコン選択 |
| version    | 環境変数・git describe・フォールバックによるバージョン解決                         |

## 2.3 テストケース一覧

### test_settings.py

#### TestValidation（バリデーション検証）

| テストケース                                                | 検証内容                                                   |
| ----------------------------------------------------------- | ---------------------------------------------------------- |
| test_validate_not_empty_rejects_empty                       | 空文字列・空白のみの文字列・None でエラーを返すこと        |
| test_validate_not_empty_accepts_valid_string                | 正常な文字列で None を返すこと                             |
| test_validate_path_chars_rejects_forbidden_chars            | 禁止文字（< > " \| ? \*）でエラーを返すこと                |
| test_validate_path_chars_rejects_invalid_colon              | ドライブレター以外のコロンでエラーを返すこと               |
| test_validate_path_chars_rejects_invalid_drive_format       | 不正なドライブ形式でエラーを返すこと                       |
| test_validate_path_chars_accepts_valid_paths                | 正常なパス（絶対パス・チルダ・環境変数）で None を返すこと |
| test_validate_filename_chars_rejects_forbidden_chars        | 禁止文字（< > : " / \ \| ? \*）でエラーを返すこと          |
| test_validate_filename_chars_ignores_placeholder_brackets   | プレースホルダ内の記号を誤検知しないこと                   |
| test_validate_shortcut_format_delegates_to_hotkey_manager   | ショートカット検証が hotkey.Manager へ正しく委譲されること |
| test_validate_preset_placeholders_accepts_allowed_keys      | 許可済みキー（timestamp, title, index, dup）で None を返すこと |
| test_validate_preset_placeholders_rejects_unknown_keys      | 未定義プレースホルダでエラーを返すこと                     |
| test_validate_preset_placeholders_rejects_unbalanced_braces | 不正な波括弧構文でエラーを返すこと                         |
| test_validate_preset_placeholders_rejects_invalid_duplicate_format | {dup} の不正なテンプレート・開始番号でエラーを返すこと |
| test_validate_overwrite_risk_warns_without_unique_placeholder | {index} / {dup} / %f 付き {timestamp} が無い場合に警告を返すこと |
| test_validate_overwrite_risk_accepts_unique_placeholder     | {index} / {dup} / %f 付き {timestamp} のいずれかがあれば警告しないこと |
| test_default_preset_has_no_validation_result                | デフォルトのファイル名プリセットでエラー・警告が出ないこと |
| test_validate_all_returns_errors_for_invalid_entries        | 複数項目の一括バリデーションでエラーを正しく集約すること   |
| test_validate_prefers_error_over_preceding_warning          | 先のルールが警告でも、後のルールのエラーを優先して返すこと |

#### TestOutputPathLength（保存先パス長検証）

| テストケース                                            | 検証内容                                                                 |
| ------------------------------------------------------- | ------------------------------------------------------------------------ |
| test_validate_all_rejects_path_exceeding_max_length     | {title} が空でも最短フルパスが 260 文字になる場合、プリセット側にエラーを返すこと |
| test_validate_all_accepts_path_within_max_length        | 最短フルパスがちょうど 259 文字の場合はエラーにならず、警告になること     |
| test_validate_all_uses_expanded_directory_length        | 環境変数を含むフォルダを展開後の長さで判定すること                       |
| test_validate_all_skips_path_length_check_on_format_error | プリセット書式エラー時はパス長ではなく書式のエラーを返すこと           |
| test_warning_when_title_margin_below_threshold          | タイトルに使える残り文字数が閾値未満の場合に警告を返すこと               |
| test_no_warning_when_title_margin_at_threshold          | 残り文字数が閾値ちょうどの場合は警告しないこと                           |
| test_no_warning_when_preset_has_no_title                | プリセットに {title} が無い場合は警告しないこと                          |

#### TestSettingsManagerIO（ファイル読み書き・リカバリ検証）

| テストケース                                            | 検証内容                                                                       |
| ------------------------------------------------------- | ------------------------------------------------------------------------------ |
| test_load_creates_default_settings_when_file_not_exists | 設定ファイル不在時にデフォルト値で新規作成されること                           |
| test_load_reads_existing_valid_settings                 | 正常な設定ファイルから値（通知設定3項目・アップデート確認を含む）を読み込めること |
| test_load_migrates_old_key_names                        | 旧キー名（notify.updateCheck を含む）が新キー名に自動マイグレーションされること |
| test_load_splits_old_notification_key_into_categories   | 旧キー capture.enableSystemNotification の値が通知設定3項目すべてへ引き継がれ、旧キーがファイルから除去されること |
| test_load_removes_old_key_when_new_key_exists           | 現キーと旧キーが混在する場合、現キーの値を優先し、旧キーがファイルから除去されること |
| test_load_handles_corrupted_json_and_recovers           | JSON 破損時にバックアップ退避の上デフォルト復旧すること                        |
| test_load_replaces_invalid_value_with_default           | 不正な設定値がデフォルト値に差し替えられること                                 |
| test_load_migrates_legacy_default_preset                | 旧デフォルトのファイル名プリセットが現デフォルトへ置き換えて保存されること     |
| test_load_replaces_preset_when_path_exceeds_max_length  | フォルダとプリセットの組み合わせで最大パス長を超える場合、プリセットがデフォルト値に戻り元ファイルが退避されること |
| test_save_atomic_write_creates_valid_json               | save がアトミック書き込みで正しく保存されること                                |
| test_get_and_set_in_memory                              | メモリ上での get / set が期待通り動作すること                                  |

### test_hotkey.py

#### TestParseShortcutString（文字列解析検証）

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

#### TestIsValidShortcut（ショートカット妥当性検証）

| テストケース                                     | 検証内容                            |
| ------------------------------------------------ | ----------------------------------- |
| test_is_valid_shortcut_returns_true_for_valid    | 有効な組み合わせで True を返すこと  |
| test_is_valid_shortcut_returns_false_for_invalid | 無効な組み合わせで False を返すこと |

#### TestReloadHotkey（再登録要否判定検証）

| テストケース                                       | 検証内容                                                       |
| -------------------------------------------------- | -------------------------------------------------------------- |
| test_skips_reregistration_when_shortcut_unchanged  | 登録中と同じ組み合わせ（表記揺れを含む）なら解除・再登録しないこと |
| test_reregisters_when_shortcut_changed             | 異なる組み合わせなら旧キーを解除して新キーを登録すること       |
| test_reregisters_when_previous_registration_failed | 前回の登録に失敗している場合、同じ組み合わせでも再登録すること |

### test_capture.py

#### TestGenerateOutputPath（保存先パス生成検証）

| テストケース                                                | 検証内容                                         |
| ----------------------------------------------------------- | ------------------------------------------------ |
| test_generate_output_path_replaces_forbidden_characters     | ウィンドウタイトルの禁止文字が置換されること     |
| test_generate_output_path_formats_timestamp_and_title       | プリセットに基づきパスが正しく組み立てられること |
| test_generate_output_path_avoids_existing_file              | 同名ファイルがある場合に {dup} の連番付きパスを返すこと |
| test_generate_output_path_rejects_path_exceeding_max_length | パス長 259 文字超過時に None を返すこと          |
| test_generate_output_path_handles_format_error              | プリセット書式エラー時に None を返すこと         |

#### TestGenerateExifMetadata（メタデータ生成検証）

| テストケース                                                      | 検証内容                                                     |
| ----------------------------------------------------------------- | ------------------------------------------------------------ |
| test_generate_exif_metadata_embeds_modification_time_and_png_info | 更新日時と PNG 作成日時が常時埋め込まれること                |
| test_generate_exif_metadata_embeds_shooting_time_when_enabled     | メタデータ有効時に撮影日時・デジタル化日時が埋め込まれること |
| test_generate_exif_metadata_skips_shooting_time_when_disabled     | メタデータ無効時に撮影日時が埋め込まれないこと               |

#### TestCaptureLock（多重実行防止検証）

| テストケース                     | 検証内容                                                     |
| -------------------------------- | ------------------------------------------------------------ |
| test_skips_capture_while_running | 撮影処理の実行中のキー入力は撮影せず、スキップのログのみ出力すること |

#### TestPlayCaptureSound（通知音再生検証）

| テストケース                           | 検証内容                                                 |
| -------------------------------------- | -------------------------------------------------------- |
| test_does_not_play_when_volume_is_zero | 音量0%の場合に MCI コマンドを送信しないこと              |
| test_plays_with_scaled_volume          | 音量50%が MCI の音量500に変換されて再生されること        |

### test_notifier.py

#### TestNotifyCategory（通知の種別による表示切り替え検証）

| テストケース                                 | 検証内容                                                                                     |
| -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| test_sends_toast_when_category_enabled       | 種別（撮影時・起動終了時など・エラー・アップデート）に対応する設定がオンの場合、トースト通知が送信されること |
| test_skips_toast_when_category_disabled      | 種別に対応する設定がオフ（False / "disabled"）の場合、トースト通知は送信されずログのみ出力されること |
| test_other_category_setting_does_not_affect  | 他の種別の設定がオフでも、対象の種別の設定がオンなら送信されること                           |
| test_category_is_required                    | 種別を指定せずに呼び出すと TypeError になること                                              |

#### TestRotateLogFile（ログファイルの世代切り替え検証）

| テストケース                                   | 検証内容                                                                           |
| ---------------------------------------------- | ---------------------------------------------------------------------------------- |
| test_keeps_file_within_limit                   | 基準サイズ以下のログファイルは切り替えられないこと                                 |
| test_does_nothing_without_log_file             | ログファイルが存在しない場合、例外を出さず何もしないこと                           |
| test_moves_oversized_file_and_overwrites_old   | 基準サイズを超えたログファイルが app.log.old へ移り、既存の旧世代は上書きされること |
| test_continues_when_replace_fails              | 置換に失敗しても例外を外に出さず、失敗をログに記録すること                         |

### test_startup.py

#### TestGetStatus（登録状態の判定検証）

| テストケース                                     | 検証内容                                                                         |
| ------------------------------------------------ | -------------------------------------------------------------------------------- |
| test_returns_unregistered_when_shortcut_missing  | ショートカットが無い場合に未登録と判定されること                                 |
| test_returns_enabled_when_not_disabled_by_windows | ショートカットがあり、StartupApproved の記録が無いか先頭バイトが偶数の場合に有効と判定されること |
| test_returns_disabled_when_disabled_by_windows   | ショートカットがあり、StartupApproved の先頭バイトが奇数の場合にWindows側で無効と判定されること |

#### TestRegistration（登録・解除検証）

| テストケース                                     | 検証内容                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------------ |
| test_register_creates_shortcut                   | スタートアップフォルダのパスでショートカットが作成されること             |
| test_register_notifies_error_on_failure          | 作成失敗時に False を返し、エラー通知されること                          |
| test_unregister_removes_shortcut                 | 解除時にショートカットが削除されること                                   |
| test_unregister_succeeds_when_shortcut_missing   | ショートカットが既に無い場合も解除成功として扱い、エラー通知しないこと   |
| test_skips_in_development_environment           | 開発時は登録・解除・更新のいずれもショートカットを操作しないこと         |

#### TestRefreshShortcut（起動時のショートカット更新検証）

| テストケース                   | 検証内容                                   |
| ------------------------------ | ------------------------------------------ |
| test_skips_when_unregistered   | 未登録の場合はショートカットを作成しないこと |
| test_recreates_when_registered | 登録済みの場合はショートカットを作り直すこと |

### test_updater.py

#### TestParseVersion（タグ名の解析・比較検証）

| テストケース                              | 検証内容                                                                  |
| ----------------------------------------- | ------------------------------------------------------------------------- |
| test_parse_stable_version                 | 正式版のタグ名が正式版フラグ付きのタプルに変換されること                  |
| test_parse_beta_version                   | beta版のタグ名がbeta番号付きのタプルに変換されること                      |
| test_parse_invalid_version_returns_none   | 想定外の形式のタグ名（フォールバック文字列を含む）で None が返ること      |
| test_version_ordering                     | beta版は同番号の正式版より古く、各番号が数値として比較されること          |

#### TestFindLatestRelease（最新リリースの選択検証）

| テストケース                                | 検証内容                                                   |
| ------------------------------------------- | ---------------------------------------------------------- |
| test_excludes_prerelease_when_not_included  | Pre-releaseを含めない場合、正式版の中で最大のものが選ばれること |
| test_includes_prerelease_when_included      | Pre-releaseを含める場合、beta版も選択対象になること        |
| test_excludes_draft                         | 下書きのリリースが選択対象外になること                     |
| test_returns_none_when_no_candidate         | 対象となるリリースが無い場合に None が返ること             |

#### TestGetNewerReleaseTag（新しいバージョンの有無の確認検証）

| テストケース                                            | 検証内容                                                                 |
| ------------------------------------------------------- | ------------------------------------------------------------------------ |
| test_returns_newer_prerelease_only_when_included        | 新しいbeta版は、Pre-releaseを対象に含めた場合のみ返ること                |
| test_raises_on_fetch_failure                            | リリース一覧の取得に失敗した場合、例外がそのまま送出されること           |
| test_raises_without_fetch_when_current_version_unparsable | 現在のバージョンを解析できない場合、リリース一覧を取得せずに ValueError を送出すること |

#### TestCheckForUpdate（起動時のアップデート確認と通知検証）

| テストケース                                 | 検証内容                                                                         |
| -------------------------------------------- | -------------------------------------------------------------------------------- |
| test_notifies_when_newer_prerelease_exists   | 新しいbeta版がある場合、リリースページボタン付き・アップデート種別で通知されること |
| test_does_not_notify_when_up_to_date         | 最新版を使用している場合、通知されないこと                                       |
| test_skips_fetch_when_disabled               | 「確認しない」設定では、リリース一覧を取得しないこと                             |
| test_fetch_failure_logs_without_notification | 取得失敗時、通知せずログ出力のみ行うこと                                         |

### test_filename_preset.py

#### TestFormattableTimestamp（日時フォーマット検証）

| テストケース                          | 検証内容                                                       |
| ------------------------------------- | -------------------------------------------------------------- |
| test_default_format_without_specifier | 書式指定なしでデフォルト書式（%Y%m%d\_%H%M%S）が適用されること |
| test_custom_format_with_specifier     | カスタム書式指定が正しく反映されること                         |

#### TestFormatOutputPath（保存先パス組み立て検証）

| テストケース                                               | 検証内容                                                     |
| ---------------------------------------------------------- | ------------------------------------------------------------ |
| test_format_output_path_expands_directory_and_formats_preset | フォルダの環境変数が展開され、プリセットが置換されたパスを返すこと |
| test_format_output_path_formats_index                      | {index} に連番が入り、{index:03} でゼロ埋めされること        |

#### TestDuplicateSuffix（重複時連番の書式検証）

| テストケース                           | 検証内容                                                         |
| -------------------------------------- | ---------------------------------------------------------------- |
| test_first_file_has_no_suffix          | 1件目は書式指定に関わらず空文字になること                        |
| test_default_format_without_specifier  | 書式指定が無い場合は「 (2)」形式になること                       |
| test_custom_template_and_zero_padding  | テンプレートで区切り文字やゼロ埋めを指定できること               |
| test_custom_start_number               | 「:」区切りで2件目の番号を指定できること                         |
| test_invalid_format_raises_value_error | 変換指定の無いテンプレートや整数でない開始番号で ValueError になること |

#### TestBuildOutputPath（重複しない保存先パスの確定検証）

| テストケース                                          | 検証内容                                                             |
| ----------------------------------------------------- | -------------------------------------------------------------------- |
| test_returns_first_path_when_not_exists               | 同名ファイルが無い場合は連番なしのパスを返すこと                     |
| test_skips_existing_files                             | 同名ファイルがある場合は空いている連番のパスを返すこと               |
| test_skips_existing_files_with_index                  | {index} でも既存ファイルと被らない番号を返すこと                     |
| test_returns_existing_path_without_sequence_placeholder | {index} / {dup} が無い場合は同名ファイルがあってもそのパスを返すこと |

### test_paths.py

#### TestExpandPath（パス展開検証）

| テストケース                                | 検証内容                               |
| ------------------------------------------- | -------------------------------------- |
| test_expand_path_with_empty_string          | 空文字列に対して空文字列を返すこと     |
| test_expand_path_with_tilde                 | チルダがユーザーホームに展開されること |
| test_expand_path_with_environment_variables | 環境変数が正しく展開・正規化されること |

#### TestAppPaths（パス解決検証）

| テストケース                                   | 検証内容                                       |
| ---------------------------------------------- | ---------------------------------------------- |
| test_get_app_path_in_development_environment   | 開発環境でリポジトリルート基準のパスを返すこと |
| test_get_asset_path_in_development_environment | 開発環境で assets フォルダ配下のパスを返すこと |
| test_get_app_icon_path_in_development_environment | 開発環境で開発用アイコン（icon_dev.ico）のパスを返すこと |

#### TestIconFilename（アイコン選択検証）

| テストケース                           | 検証内容                                  |
| -------------------------------------- | ----------------------------------------- |
| test_stable_version_uses_default_icon  | 正式版のタグ名で icon.ico が選ばれること  |
| test_beta_version_uses_beta_icon       | beta版のタグ名で icon_beta.ico が選ばれること |

### test_version.py

#### TestVersionResolution（バージョン解決検証）

| テストケース                                          | 検証内容                                        |
| ----------------------------------------------------- | ----------------------------------------------- |
| test_get_app_version_from_custom_environment_variable | EXIF_CAPTURE_VERSION 環境変数から取得できること |
| test_get_app_version_from_github_ref_name             | GITHUB_REF_NAME 環境変数から取得できること      |
| test_get_app_version_from_git_describe                | git describe の出力から取得できること           |
| test_get_app_version_fallback                         | 全手段失敗時にフォールバック文字列を返すこと    |

# 3. 手動テスト

pytest による自動テストでは検証できない範囲について、手動テストを行う。
設定値や分岐によるロジックの違いは自動テストで検証し、手動テストは OS ネイティブ機能・GUI・実通信・ビルド成果物の確認に限る。
確認の回数を抑えるため、1ケースの期待結果は1つとする。

## 3.1 テスト観点

| 対象領域                       | テスト観点                                                                     | 手動実施の理由                                                           |
| ------------------------------ | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| main.pyw（アプリ起動・終了）   | 起動通知、トレイメニュー、終了処理                                             | トレイ常駐・スレッド管理の統合処理があり、pytestでの試験が困難なため     |
| capture.py（キャプチャ統合）   | ホットキー押下→撮影→保存→通知の一連フロー、全画面キャプチャ                   | 実際の画面描画（GDI / DWM / ImageGrab）を伴うため                        |
| notifier.py（通知）            | トースト通知のボタンアクション、閉じ方による影響、エラー通知                   | OSネイティブ機能の確認を要し、pytestでは送信処理をモック化しているため   |
| settings_window.py（設定画面） | タブ表示、タブをまたいだ保存、テスト再生、バリデーション表示と解除、キー記録とキャンセル | GUIアプリケーションのため                                                |
| hotkey.py（ホットキー登録）    | 競合時のエラー通知、設定変更時の再登録                                         | Windowsのメッセージループ上で動作し、OSネイティブ機能の確認を要するため  |
| updater.py（アップデート確認） | GitHub Releasesからの取得、リリースページを開くボタン、設定画面の今すぐ確認ボタン | 実際のGitHub APIとの通信を伴い、pytestでは取得処理をモック化しているため |
| startup.py（スタートアップ）   | 設定画面からの登録・解除、Windows側で無効化した状態の表示、サインイン時の自動起動 | スタートアップフォルダ・タスクマネージャー・サインインといったOSの機能を使い、exeのビルドも要するため |
| アプリアイコンの出し分け       | 実行中のトレイ・設定画面のアイコン、終了後のスタートメニューでのアイコン       | exeのビルドと、トレイ・スタートメニュー等での目視確認を要するため        |

## 3.2 テストケース一覧

起動方法の指定がないケースは、リポジトリルートのコンソールから `python src/main.pyw` で起動した状態で行う。

### アプリ起動（main.pyw）

| #    | テストケース   | 手順                                                                   | 期待結果                                                                                   |
| ---- | -------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| M-01 | 起動通知       | `python src/main.pyw` で起動する                                       | バージョン番号付きの起動通知が表示される                                                   |
| M-02 | トレイメニュー | トレイアイコンを右クリックする                                         | 「設定を開く」「保存先フォルダを開く」「ログファイルを開く」「終了」の4項目が表示される     |
| M-03 | 開発時アイコン | トレイメニュー→「設定を開く」で設定画面を開く                         | トレイと設定画面に icon_dev.ico のアイコンが表示される                                     |

### キャプチャ（capture.py）

| #    | テストケース         | 手順                                                                                                                                  | 期待結果                                              |
| ---- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| M-04 | ウィンドウキャプチャ | メモ帳を最前面にしてショートカットキー（既定: Shift+PrintScreen）を押し、表示された通知の「キャプチャした画像を開く」を押す          | メモ帳のウィンドウが写った画像が既定アプリで開かれる  |
| M-05 | EXIF メタデータ      | 「保存」タブで「撮影日時のEXIFメタデータを埋め込む」を有効にしてキャプチャする。保存されたPNGを右クリック→プロパティ→詳細タブを開く | 「撮影日時」に撮影時刻が記録されている                |
| M-06 | 全画面キャプチャ     | デスクトップの何もない場所をクリックし、全ウィンドウを非アクティブにした状態でショートカットキーを押す                                | 保存先フォルダに「FullScreen」を含むPNGが作成される   |

### 通知（notifier.py）

| #    | テストケース | 手順                                                                                       | 期待結果                                                                                         |
| ---- | ------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| M-07 | 通知の閉じ方 | キャプチャを2回行い、1回目の通知は×で閉じ、2回目の通知は放置して消えるのを待つ             | コンソールにエラー（Event loop is closed 等）や閉じた理由の出力（ToastDismissalReason）が出ない |
| M-08 | エラー通知   | 保存先フォルダを存在しないドライブ（例: `Z:\Screenshots`）にしてキャプチャする             | 「撮影に失敗しました。」の通知が表示される                                                       |

### 設定画面（settings_window.py）

| #    | テストケース               | 手順                                                                                                                                 | 期待結果                                                                                         |
| ---- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| M-09 | タブの表示                 | 「撮影」「保存」「Windows機能」「アップデート」タブを順に選択する                                                                                           | 各タブの項目が見切れずに表示され、選択中のタブがアクセントカラーで強調される                     |
| M-10 | タブをまたいだ保存         | 「撮影」タブで音量を変更し、「保存」タブの「参照...」で保存先フォルダを選び、「保存」を押す                                         | settings.json に音量と保存先フォルダの両方の変更が反映されている                                 |
| M-11 | テスト再生                 | 「撮影」タブで音量を「50%」にして「テスト再生」を押す                                                                               | 通知音が鳴る                                                                                     |
| M-12 | バリデーションエラー表示   | 「保存」タブの保存先フォルダの入力欄に禁止文字（例: `C:\Save<here`）を入力し、「Windows機能」タブに切り替える                             | ボタンの上に「「保存」タブに入力エラーがあります。」と表示され、「適用」「保存」ボタンが押せない |
| M-13 | バリデーションエラーの解除 | M-12 の状態から「保存」タブに戻り、入力を元に戻す                                                                                    | エラー表示が消え、「適用」「保存」ボタンが押せるようになる                                       |
| M-14 | ショートカットキー記録     | 「撮影」タブで「キーを記録」ボタンを押し、Ctrl+Shift+S を押す                                                                       | 入力欄に「ctrl+shift+s」が反映される                                                             |
| M-15 | キー記録のキャンセル       | M-14 の後、もう一度「キーを記録」ボタンを押し、Esc を押す                                                                           | 入力欄が「ctrl+shift+s」（記録前の値）に戻る                                                     |

### ホットキー登録（hotkey.py）

| #    | テストケース     | 手順                                                                                                         | 期待結果                                                     |
| ---- | ---------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| M-16 | ホットキー競合   | settings.json の capture.triggerShortcut を「ctrl+c」など他アプリが使用しているキーに直接書き換えて起動する | 「ショートカットキーの登録に失敗しました」の通知が表示される |
| M-17 | ホットキー再登録 | M-16 の状態から設定画面でショートカットキーを「Shift+PrintScreen」に変更して「適用」を押し、そのキーを押す  | キャプチャが実行され、保存先フォルダにPNGが作成される        |

### アップデート確認（updater.py）

| #    | テストケース     | 手順                                                                                                                                                                                                     | 期待結果                                  |
| ---- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| M-18 | アップデート通知 | アップデートの確認を「正式版のみ確認する」にし、`EXIF_CAPTURE_VERSION=v1.0.0 python src/main.pyw` で起動する（bash の場合）。数十秒後に表示される新バージョンの通知の「リリースページを開く」を押す | ブラウザで GitHub Releases のページが開く |
| M-19 | 今すぐ確認（新版あり） | `EXIF_CAPTURE_VERSION=v1.0.0 python src/settings_window.py` で設定画面を開き（bash の場合）、「アップデート」タブで「今すぐ確認」を押した後、「リリースページを開く」を押す | ブラウザで GitHub Releases のページが開く |
| M-20 | 今すぐ確認（失敗） | ネットワークを切断した状態で、M-19 と同様に「今すぐ確認」を押す | 「確認に失敗しました。(詳細はログを参照)」と赤字で表示される |

### アプリ終了（main.pyw）

| #    | テストケース | 手順                                        | 期待結果                                                       |
| ---- | ------------ | ------------------------------------------- | -------------------------------------------------------------- |
| M-21 | アプリ終了   | トレイアイコン右クリック→「終了」を選択する | 「終了します。」の通知が表示され、通知領域からアイコンが消える |

### exe 版のアイコン

| #    | テストケース             | 手順                                                                                                                                                   | 期待結果                                                                   |
| ---- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| M-22 | exe 実行中のアイコン     | `EXIF_CAPTURE_VERSION=v1.2.0-beta.1 python tools/build.py` を実行し、生成された exe を起動して設定画面を開く（bash の場合）                            | トレイと設定画面に icon_beta.ico のアイコンが表示される                    |
| M-23 | exe 終了後のアイコン     | M-22 の exe でキャプチャを1回行ってから終了し、スタートメニューの「EXIF Capture」を確認する                                                            | icon_beta.ico のアイコンが表示されている（汎用アイコンや空白にならない）   |

### スタートアップ（startup.py）

| #    | テストケース             | 手順                                                                                                                       | 期待結果                                                                 |
| ---- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| M-24 | 開発時の操作抑止         | `python src/main.pyw` で起動し、設定画面の「Windows機能」タブを開く                                                               | 「exe実行時のみ設定できます。」と表示され、ボタンが押せない              |
| M-25 | スタートアップへの登録   | `python tools/build.py` で生成した exe を起動し、設定画面の「Windows機能」タブで「登録する」を押す                                | `shell:startup` のフォルダに「EXIF Capture.lnk」が作成される             |
| M-26 | Windows側で無効化した表示 | M-25 の後、タスクマネージャーの「スタートアップ アプリ」で EXIF Capture を無効にし、設定画面を開き直す                     | 「Windowsの設定で無効になっています」と表示される                        |
| M-27 | サインイン時の自動起動   | M-26 の項目をタスクマネージャーで有効に戻し、サインアウトしてからサインインする                                            | アプリが自動で起動し、起動通知が表示される                               |
| M-28 | スタートアップの登録解除 | M-27 の後、設定画面の「Windows機能」タブで「解除する」を押す                                                                       | `shell:startup` のフォルダから「EXIF Capture.lnk」が削除され、「登録されていません」と表示される |
