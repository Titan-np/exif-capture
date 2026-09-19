import os
import sys
import subprocess
import shutil
import stat

# build.py自身の絶対パスから、リポジトリルートフォルダを算出
script_directory_path = os.path.dirname(os.path.abspath(__file__))
project_root_directory_path = os.path.dirname(script_directory_path)

# srcフォルダをPythonパスに追加して、constants.pyをインポート可能にする
source_directory_path = os.path.join(project_root_directory_path, "src")
sys.path.append(source_directory_path)

from constants import APP_NAME


def clean_previous_build_artifacts():
    """
    過去のビルドで生成したフォルダ・キャッシュを削除

    Returns:
        bool: 削除処理が正常に完了した場合はTrue、失敗した場合はFalse
    """
    # 削除対象となるフォルダやファイルのパス一覧
    targets_to_remove = [
        os.path.join(project_root_directory_path, "build"),
        os.path.join(project_root_directory_path, "dist"),
        os.path.join(project_root_directory_path, f"{APP_NAME}.spec"),
    ]

    def remove_readonly_permission(function_reference, target_path, excinfo):
        """
        shutil.rmtreeのエラーハンドラ。ファイルが読み取り専用の場合に書き込み権限を付与して削除を再試行する

        Args:
            function_reference (callable): 再実行する削除関数の参照
            target_path (str): 削除対象のファイルまたはディレクトリのパス
            excinfo (tuple): 例外情報 (type, value, traceback)
        """
        # 対象のパスに書き込み権限を付与
        os.chmod(target_path, stat.S_IWRITE)
        # 削除処理を再実行
        function_reference(target_path)

    # 削除対象を順番に削除
    for target_path in targets_to_remove:
        if os.path.exists(target_path):
            try:
                if os.path.isdir(target_path):
                    # Windows環境で読み取り専用ファイルが存在しても削除できるようハンドラを指定
                    shutil.rmtree(target_path, onexc=remove_readonly_permission)
                else:
                    # 単一ファイルの場合も読み取り専用属性を解除してから削除
                    os.chmod(target_path, stat.S_IWRITE)
                    os.remove(target_path)
                print(f"削除しました: {target_path}")
            except Exception as exception:
                print(f"削除処理中にエラーが発生しました: {target_path}\n{exception}")
                return False
        else:
            print(f"削除対象が存在しません: {target_path}")
    return True


def build_app():
    """
    アプリケーションのビルドプロセスを実行する

    Returns:
        int: ビルド処理の終了コード (0: 成功, 1以上: エラー)
    """
    # ビルド実行前にキャッシュや中間生成物をクリア
    if not clean_previous_build_artifacts():
        return 1

    print(f"ビルドを開始します: {APP_NAME}")

    # PyInstallerのコマンド構築
    command = [
        "pyinstaller",
        "--noconfirm",  # 既存のdist/buildを上書き
        "--clean",  # ビルド前にPyInstallerのキャッシュをクリア
        "--noconsole",
        "--onefile",
        "--icon=assets/icon.ico",
        # assetsフォルダ内のすべてのファイルをバンドル対象にする (Windows環境を想定してセミコロン区切り)
        "--add-data=assets;assets",
        "--paths=src",  # src フォルダを明示的に探索パスに追加
        f"--name={APP_NAME}",
        "src/main.pyw",
    ]

    # ビルド実行 (カレントフォルダをプロジェクトのルートに指定)
    try:
        result = subprocess.run(command, cwd=project_root_directory_path)

        if result.returncode == 0:
            print(f"\nビルドが完了しました！ dist/{APP_NAME}.exe を確認してください。")
            return 0
        else:
            print(f"\nビルド中にエラーが発生しました (終了コード: {result.returncode})。")
            return result.returncode
    except FileNotFoundError:
        print("\nエラー: PyInstallerが見つかりません。'pip install pyinstaller' を実行してインストールしてください。")
        return 1
    except Exception as exception:
        print(f"\n予期せぬエラーが発生しました:\n{exception}")
        return 1


if __name__ == "__main__":
    # ビルド処理を実行し、結果の終了コードを受け取る
    execution_exit_code = build_app()

    # CI環境（GitHub Actions等）での自動実行でない場合、ログ確認できるようキーを押下させてから終了する
    is_ci_environment = os.getenv("CI") == "true" or "GITHUB_ACTIONS" in os.environ
    if not is_ci_environment:
        input("\nEnterキーを押すと終了します...")

    # build_app()の戻り値を終了コードとし、プロセスを終了する
    sys.exit(execution_exit_code)
