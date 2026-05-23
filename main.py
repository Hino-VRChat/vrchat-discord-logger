"""
VRChat Discord Logger — main.py
エントリーポイント。フィルタリングロジック（状態管理）を担当する。
"""

import json
import os
import sys
import ctypes

from events import (
    VRChatEvent, EnteringRoomEvent, JoiningWorldEvent,
    PlayerJoinedEvent, PlayerLeftEvent, VideoPlaybackEvent,
    OnLeftRoomEvent, ImageDownloadEvent,
)
from log_parser import parse_line
from log_watcher import LogWatcher
from discord_sender import DiscordSender


HANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)


# ========== 設定読み込み ==========

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ========== フィルタリング状態 ==========

class EventFilter:
    """DESIGN.md のフィルタリング仕様を実装する状態マシン"""

    def __init__(self, config: dict):
        # 現在のインスタンス種別
        self.current_access_type: str = ""  # hidden / friends / private / invite+ / group / group+ / group-public / public

        # ワールド退出中フラグ（OnLeftRoom後にON）
        self.is_leaving_world: bool = False

        # config からフィルタ設定を読む
        filter_cfg = config.get("filter", {})
        self.show_self_join_leave = filter_cfg.get("show_self_join_leave", False)
        self.mute_in_public = filter_cfg.get("mute_join_leave_in_public", True)

        # イベント有効/無効
        self.enabled_events = config.get("events", {})

    def should_send(self, event: VRChatEvent) -> bool:
        """このイベントをDiscordに送信すべきかどうか判定する。
        状態の更新もここで行う。"""

        # --- 状態更新（常に行う） ---

        # ワールド移動 → 退出中フラグをリセット、インスタンス種別をクリア
        if isinstance(event, EnteringRoomEvent):
            self.is_leaving_world = False
            return True  # ワールド移動は常に通知

        # インスタンスJoin → 種別を記憶、退出中フラグをリセット
        if isinstance(event, JoiningWorldEvent):
            self.current_access_type = event.access_type
            self.is_leaving_world = False
            print(f"[Instance] {event.access_type} / {event.region}")
            return True  # インスタンス参加は常に通知

        # --- フィルタリング ---

        # OnLeftRoom → 退出中フラグON、通知する
        if isinstance(event, OnLeftRoomEvent):
            self.is_leaving_world = True
            return True

        # ワールド退出時の OnPlayerLeft 抑制
        if isinstance(event, PlayerLeftEvent):
            # 退出中フラグON → 全Leaveを無視
            if self.is_leaving_world:
                return False

        # publicインスタンスでのフィルタ
        if self.mute_in_public and self.current_access_type in ("public", "group-public"):
            if isinstance(event, (PlayerJoinedEvent, PlayerLeftEvent,
                                  ImageDownloadEvent, VideoPlaybackEvent)):
                return False

        # イベント有効/無効チェック
        event_type_map = {
            PlayerJoinedEvent: "player_joined",
            PlayerLeftEvent: "player_left",
            ImageDownloadEvent: "image_download",
            VideoPlaybackEvent: "video_playback",
            OnLeftRoomEvent: "on_left_room",
        }
        event_key = event_type_map.get(type(event))
        if event_key and not self.enabled_events.get(event_key, True):
            return False

        return True


# ========== メイン ==========

def main():
    # 設定読み込み
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_path):
        print(f"[Error] 設定ファイルが見つかりません: {config_path}")
        sys.exit(1)

    config = load_config(config_path)

    webhook_url = config.get("discord_webhook_url", "")
    if not webhook_url:
        print("[Error] config.json の discord_webhook_url を設定してください")
        sys.exit(1)

    log_dir = config.get("vrchat_log_dir", "")
    if not log_dir:
        # %APPDATA% (Roaming) → 1つ上がって LocalLow\VRChat\VRChat
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            log_dir = os.path.join(appdata, "..", "LocalLow", "VRChat", "VRChat")
            log_dir = os.path.normpath(log_dir)
        else:
            print("[Error] vrchat_log_dir が未設定で、APPDATA 環境変数も見つかりません")
            sys.exit(1)
    print(f"[Info] Log dir: {log_dir}")

    # モジュール初期化
    watcher = LogWatcher(
        log_dir=log_dir,
        poll_interval=config.get("poll_interval_sec", 1.0),
        rotation_interval=config.get("rotation_check_interval_sec", 30),
    )

    sender = DiscordSender(
        webhook_url=webhook_url,
        colors=config.get("embed_colors"),
    )

    event_filter = EventFilter(config)

    # 疎通確認
    print(f"[Info] Webhook: ...{webhook_url[-20:]}")
    if sender.test_connection():
        print("[Info] Discord 疎通OK")
    else:
        print("[Warning] Discord 疎通失敗。URLを確認してください")

    print("[Info] Ctrl+C で終了")

    # ウィンドウの×ボタンでも cleanup が走るようにする（Windows）
    def console_ctrl_handler(ctrl_type):
        # CTRL_CLOSE_EVENT = 2 (×ボタン)
        if ctrl_type == 2:
            print("\n[Stop] ウィンドウが閉じられました。終了します")
            sender.flush()
            sender.send_shutdown()
            return True
        return False

    _handler = HANDLER_ROUTINE(console_ctrl_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True)

    # メインループ
    pending_room = None  # EnteringRoomEvent を保留するバッファ

    def send_event(event):
        if event_filter.should_send(event):
            print(f"[Send] {type(event).__name__}: {event.raw_line[:80]}")
            sender.send(event)

    try:
        for line in watcher.watch():
            event = parse_line(line)
            if event is None:
                continue

            # EnteringRoomEvent → 保留（送信しない。直後の JoiningWorldEvent に world_name を統合）
            if isinstance(event, EnteringRoomEvent):
                pending_room = event
                continue

            # JoiningWorldEvent → 保留中の EnteringRoom から world_name を取り込んで統合送信
            if isinstance(event, JoiningWorldEvent):
                if pending_room:
                    event.world_name = pending_room.world_name
                    pending_room = None
                send_event(event)
                continue

            # その他のイベント → 保留があれば破棄（Joining が来なかった稀なケース）
            if pending_room:
                pending_room = None

            send_event(event)

    except KeyboardInterrupt:
        print("\n[Stop] 終了します")
    finally:
        sender.flush()
        sender.send_shutdown()
        print("[Info] 残りのバッチを送信しました")


if __name__ == "__main__":
    main()
