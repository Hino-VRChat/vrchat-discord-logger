"""
discord_sender.py — Discord Webhook 送信モジュール
イベントをEmbed形式でDiscordに送信する。バッチング対応。
"""

import time
import threading
import requests
from events import (
    VRChatEvent, VRDisabledEvent, UserAuthenticatedEvent,
    EnteringRoomEvent, JoiningWorldEvent,
    PlayerJoinedEvent, PlayerLeftEvent, VideoPlaybackEvent,
    OnLeftRoomEvent, ImageDownloadEvent, ShutdownEvent,
)


# DESIGN.md 準拠のEmbed色
DEFAULT_COLORS = {
    "user_authenticated": 32768, # 濃い緑
    "entering_room": 3447003,    # 青
    "player_joined": 3066993,    # 緑
    "player_left":   15158332,   # 赤
    "image":         1752220,    # ティール
    "video":         16750848,   # オレンジ
    "shutdown":      15548997,   # 濃い赤
}


class DiscordSender:
    """Discord WebhookでイベントをEmbed送信するクラス"""

    def __init__(self, webhook_url: str, colors: dict = None,
                 batching_window: float = 5.0):
        self.webhook_url = webhook_url
        self.colors = colors or DEFAULT_COLORS
        self.batching_window = batching_window

        # バッチング用
        self._batch_lock = threading.Lock()
        self._join_batch: list[PlayerJoinedEvent] = []
        self._leave_batch: list[PlayerLeftEvent] = []
        self._batch_timer: threading.Timer | None = None

    # ========== Embed 生成 ==========

    def _make_embed(self, event: VRChatEvent) -> dict | None:
        """イベントからDiscord Embedを生成"""
        ts = event.timestamp.split(" ")[-1] if event.timestamp else ""

        if isinstance(event, UserAuthenticatedEvent):
            user_url = f"https://vrchat.com/home/user/{event.user_id}"
            fields = [
                {"name": "User", "value": f"[{event.user_name}]({user_url})", "inline": True},
                {"name": "Mode", "value": "VR" if event.vr_mode else "Desktop", "inline": True},
            ]

            return {
                "title": "✅ VRChat started",
                "fields": fields,
                "color": self.colors.get("user_authenticated", 32768),
                "footer": {"text": ts},
            }

        elif isinstance(event, JoiningWorldEvent):
            access_display = {
                "private": "🔐 Invite",
                "invite+": "🔐 Invite+",
                "friends": "👥 Friends",
                "hidden": "👥 Friends+",
                "group": "🏠 Group",
                "group+": "🏠 Group+",
                "group-public": "🌐 Group Public",
                "public": "🌐 Public",
            }.get(event.access_type, event.access_type)

            world_url = f"https://vrchat.com/home/world/{event.world_id}/info"
            title = event.world_name if event.world_name else "Instance joined"

            fields = [
                {"name": "Access", "value": access_display, "inline": True},
                {"name": "Region", "value": event.region.upper(), "inline": True},
            ]
            if event.owner_id:
                owner_url = f"https://vrchat.com/home/user/{event.owner_id}"
                fields.append({"name": "Owner", "value": f"[Profile link]({owner_url})", "inline": True})
            if event.group_id:
                group_url = f"https://vrchat.com/home/group/{event.group_id}"
                fields.append({"name": "Group", "value": f"[Page link]({group_url})", "inline": True})

            return {
                "title": f"🌍 {title}",
                "url": world_url,
                "fields": fields,
                "color": self.colors.get("entering_room", 3447003),
                "footer": {"text": ts},
            }

        elif isinstance(event, PlayerJoinedEvent):
            return {
                "title": "📥 Player joined",
                "description": event.player_name,
                "color": self.colors.get("player_joined", 3066993),
                "footer": {"text": ts},
            }

        elif isinstance(event, PlayerLeftEvent):
            return {
                "title": "📤 Player left",
                "description": event.player_name,
                "color": self.colors.get("player_left", 15158332),
                "footer": {"text": ts},
            }

        elif isinstance(event, ImageDownloadEvent):
            embed = {
                "title": "🖼️ Image download",
                "description": event.url,
                "color": self.colors.get("image", 1752220),
                "footer": {"text": ts},
            }
            # DiscordのEmbedにimageを設定するとプレビュー表示される
            embed["image"] = {"url": event.url}
            return embed

        elif isinstance(event, VideoPlaybackEvent):
            return {
                "title": "🎬 Video playback",
                "description": event.content,
                "color": self.colors.get("video", 16750848),
                "footer": {"text": ts},
            }

        elif isinstance(event, ShutdownEvent):
            return {
                "title": "⏻ VRChat Shutdown",
                "color": self.colors.get("shutdown", 8411941),
                "footer": {"text": ts},
            }

        return None

    def _make_batch_embed(self, events: list[VRChatEvent],
                          emoji: str, title: str, color_key: str) -> dict:
        """バッチ用Embed生成（複数プレイヤーをまとめる）"""
        ts = events[0].timestamp.split(" ")[-1] if events[0].timestamp else ""
        names = [e.player_name for e in events]
        body = "\n".join(f"• {n}" for n in names)

        return {
            "title": f"{emoji} {title}（{len(events)}人）",
            "description": body,
            "color": self.colors.get(color_key, 3066993),
            "footer": {"text": ts},
        }

    # ========== 送信 ==========

    def _post_embeds(self, embeds: list[dict]):
        """Embedリストを送信（Discordは1リクエストで最大10 embeds）"""
        if not embeds:
            return

        payload = {"embeds": embeds[:10]}
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 1)
                print(f"[Rate Limit] {retry_after}秒待機...")
                time.sleep(retry_after)
                requests.post(self.webhook_url, json=payload, timeout=10)
            elif resp.status_code >= 400:
                print(f"[Discord Error] status={resp.status_code}")
        except requests.RequestException as e:
            print(f"[Network Error] {e}")

    def _flush_batch(self):
        """バッチに溜まったJoin/Leaveをまとめて送信"""
        with self._batch_lock:
            embeds = []

            if self._join_batch:
                if len(self._join_batch) == 1:
                    embeds.append(self._make_embed(self._join_batch[0]))
                else:
                    embeds.append(self._make_batch_embed(
                        self._join_batch, "📥", "Player joined", "player_joined"))
                self._join_batch.clear()

            if self._leave_batch:
                if len(self._leave_batch) == 1:
                    embeds.append(self._make_embed(self._leave_batch[0]))
                else:
                    embeds.append(self._make_batch_embed(
                        self._leave_batch, "📤", "Player left", "player_left"))
                self._leave_batch.clear()

            self._batch_timer = None

        if embeds:
            self._post_embeds(embeds)

    # ========== 公開API ==========

    def send(self, event: VRChatEvent):
        """イベントを送信する。Join/Leaveはバッチング対象。"""

        if isinstance(event, (PlayerJoinedEvent, PlayerLeftEvent)):
            with self._batch_lock:
                if isinstance(event, PlayerJoinedEvent):
                    self._join_batch.append(event)
                else:
                    self._leave_batch.append(event)

                # タイマーが走ってなければ開始
                if self._batch_timer is None:
                    self._batch_timer = threading.Timer(
                        self.batching_window, self._flush_batch)
                    self._batch_timer.daemon = True
                    self._batch_timer.start()
            return

        # それ以外は即時送信
        embed = self._make_embed(event)
        if embed:
            self._post_embeds([embed])

    def flush(self):
        """残りのバッチを強制送信（終了時用）"""
        if self._batch_timer:
            self._batch_timer.cancel()
        self._flush_batch()

    def test_connection(self) -> bool:
        """Webhookの疎通確認"""
        try:
            payload = {"content": "🟢 VRChat Logger 起動しました"}
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code < 400
        except requests.RequestException:
            return False

    def send_shutdown(self):
        """停止メッセージを送信"""
        try:
            payload = {"content": "🔴 VRChat Logger 停止しました"}
            requests.post(self.webhook_url, json=payload, timeout=10)
        except requests.RequestException:
            pass
