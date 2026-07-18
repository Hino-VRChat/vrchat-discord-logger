"""
log_watcher.py — ファイル監視モジュール
VRChatのログファイルを監視し、新しい行をジェネレーターで返す。
"""

import glob
import os
import time


class LogWatcher:
    """VRChatのoutput_logを監視するクラス"""

    def __init__(self, log_dir: str, poll_interval: float = 1.0,
                 rotation_interval: float = 30.0):
        self.log_dir = log_dir
        self.poll_interval = poll_interval
        self.rotation_interval = rotation_interval
        self._file = None
        self._current_path = None

    def get_latest_log(self) -> str | None:
        """最新の output_log_*.txt を取得"""
        pattern = os.path.join(self.log_dir, "output_log_*.txt")
        files = glob.glob(pattern)
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    def _open_log(self, path: str, seek_end: bool = True):
        """ログファイルを開く。seek_end=Trueなら末尾にジャンプ。"""
        if self._file:
            self._file.close()
        self._current_path = path
        self._file = open(path, "r", encoding="utf-8", errors="replace")
        if seek_end:
            self._file.seek(0, 2)

    def _check_rotation(self) -> bool:
        """ログローテーションを確認。切り替わったらTrueを返す。"""
        new_log = self.get_latest_log()
        if new_log and new_log != self._current_path:
            print(f"[Rotation] 新しいログに切り替え: {os.path.basename(new_log)}")
            self._open_log(new_log, seek_end=False)
            return True
        return False

    def watch(self):
        """メイン監視ジェネレーター。新しい行を yield で返す。"""
        # 最新ログ検出（見つからなければ現れるまで待機）
        log_path = self.get_latest_log()
        seek_end = True
        if not log_path:
            print(f"[Wait] ログファイルが見つかりません: {self.log_dir}")
            print("[Wait] VRChatの起動を待っています...")
            while not log_path:
                time.sleep(self.poll_interval)
                log_path = self.get_latest_log()
            # 待機中に現れたログは新規作成なので先頭から読む（起動時イベントを拾う）
            seek_end = False

        self._open_log(log_path, seek_end=seek_end)
        print(f"[Start] 監視開始: {os.path.basename(log_path)}")

        try:
            last_rotation_check = time.time()

            while True:
                line = self._file.readline()

                if line:
                    yield line.rstrip("\n\r")
                else:
                    time.sleep(self.poll_interval)

                    # ログローテーション確認
                    now = time.time()
                    if now - last_rotation_check >= self.rotation_interval:
                        last_rotation_check = now
                        self._check_rotation()

        finally:
            if self._file:
                self._file.close()
