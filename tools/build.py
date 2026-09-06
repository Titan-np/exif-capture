import os
import sys
import subprocess

# build.py自身の絶対パスから、リポジトリルートフォルダを算出
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)

# srcフォルダをPythonパスに追加して、constants.pyをインポート可能にする
src_dir = os.path.join(project_root, "src")
sys.path.append(src_dir)

from constants import APP_NAME


def build_app():
    """
    アプリケーションのビルドプロセスを実行する
    """
    print(f"ビルドを開始します: {APP_NAME}")

    # PyInstallerのコマンド構築
    command = [
        "pyinstaller",
        "--noconfirm",  # 既存のdist/buildを上書き
        "--noconsole",
        "--onefile",
        "--icon=assets/icon.ico",
        # assetsフォルダ内のすべてのファイルをバンドル対象にする (Windows環境を想定してセミコロン区切り)
        "--add-data=assets;assets",
        f"--name={APP_NAME}",
        "src/main.pyw",
    ]

    # ビルド実行 (カレントフォルダをプロジェクトのルートに指定)
    try:
        result = subprocess.run(command, cwd=project_root)

        if result.returncode == 0:
            print(f"\nビルドが完了しました！ dist/{APP_NAME}.exe を確認してください。")
        else:
            print(f"\nビルド中にエラーが発生しました (終了コード: {result.returncode})。")
    except FileNotFoundError:
        print("\nエラー: PyInstallerが見つかりません。'pip install pyinstaller' を実行してインストールしてください。")
    except Exception as exception:
        print(f"\n予期せぬエラーが発生しました:\n{exception}")


if __name__ == "__main__":
    build_app()
