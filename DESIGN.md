# VRChat Discord Logger — DESIGN.md

VRChatでの活動をリアルタイムにDiscordへ可視化するツール。
VRChatのログファイル (`output_log_*.txt`) を監視し、イベントをDiscord Webhookで通知する。

---

## アーキテクチャ

```
output_log_*.txt
      │
      ▼
 [log_watcher.py]  ── ジェネレーター方式で新しい行を yield ──►
      │
      ▼
 [log_parser.py]   ── 正規表現でマッチ → イベントオブジェクトに変換 ──►
      │
      ▼
 [main.py]         ── EventFilter（状態マシン）でフィルタリング ──►
      │
      ▼
 [discord_sender.py] ── Embed生成 → Discord Webhook送信
```

### ファイル構成

| ファイル | 役割 |
|---|---|
| `events.py` | イベント dataclass 定義 |
| `log_watcher.py` | ログファイル監視（ジェネレーター） |
| `log_parser.py` | ログ行 → イベントオブジェクト変換 |
| `main.py` | フィルタリング状態マシン + エントリーポイント |
| `discord_sender.py` | Discord Embed生成 + Webhook送信 + バッチング |
| `config.json` | 設定ファイル |

---

## イベント一覧

| イベント | ログパターン | Embed |
|---|---|---|
| `JoiningWorldEvent` | `[Behaviour] Joining wrld_...` | 🌍 ワールド名 + Access/Region/Owner |
| `PlayerJoinedEvent` | `[Behaviour] OnPlayerJoined ...` | 📥 Player joined |
| `PlayerLeftEvent` | `[Behaviour] OnPlayerLeft ...` | 📤 Player left |
| `VideoPlaybackEvent` | `[Video Playback] ...` / `[YamaStream] ...` | 🎬 Video playback |
| `OnLeftRoomEvent` | `[Behaviour] OnLeftRoom` | 🚪 Left room |
| `ImageDownloadEvent` | `[Image Download] ...` | 🖼️ Image download |
| `EnteringRoomEvent` | `[Behaviour] Entering Room: ...` | ※送信しない（world_name を JoiningWorldEvent に統合） |

### EnteringRoom → JoiningWorld 統合

VRChatのログでは `Entering Room:` の直後に `Joining wrld_...` が出る。
`EnteringRoomEvent` は保留（pending_room）し、直後の `JoiningWorldEvent` に `world_name` を統合して1つのEmbedとして送信する。

### VideoPlaybackEvent の統合

動画プレイヤーごとにログ表記が異なる：

- `[Video Playback] Attempting to resolve URL '...'` → content = URL
- `[UdonBehaviour-YamaStream] Loaded video info from YouTube: ...` → content = タイトル

両方とも同一の `VideoPlaybackEvent(content=...)` として扱う。

---

## インスタンスアクセスタイプ

ログのインスタンスURL構造からアクセスタイプを判定する。

| ログ | access_type | Embed表示 |
|---|---|---|
| `~hidden(usr_...)` | hidden | 👥 Friends+ |
| `~friends(usr_...)` | friends | 👥 Friends |
| `~private(usr_...)` | private | 🔐 Invite |
| `~private(usr_...)~canRequestInvite` | invite+ | 🔐 Invite+ |
| `~group(grp_...)~groupAccessType(members)` | group | 🏠 Group |
| `~group(grp_...)~groupAccessType(plus)` | group+ | 🏠 Group+ |
| `~group(grp_...)~groupAccessType(public)` | group-public | 🌐 Group Public |
| (なし) | public | 🌐 Public |

### リンク生成

- **ワールド**: `https://vrchat.com/home/world/{world_id}/info`
- **オーナー** (usr_): `https://vrchat.com/home/user/{owner_id}`
- **グループ** (grp_): `https://vrchat.com/home/group/{group_id}`

---

## フィルタリング（EventFilter 状態マシン）

### 状態

| 状態 | 説明 |
|---|---|
| `current_access_type` | 現在のインスタンス種別 |
| `is_leaving_world` | OnLeftRoom後にON、次のワールド移動でリセット |

### フィルタルール

```
[通常] ──(OnLeftRoom)──► [退出中: Leave全無視]
                                │
                   (Entering Room / Joining wrld)
                                │
                                ▼
                             [通常]
```

- **EnteringRoom / JoiningWorld**: 常に通知（状態リセット）
- **OnLeftRoom**: 退出フラグON + 通知
- **PlayerLeft + 退出中フラグON**: 抑制（自分の退出時に全員分のLeaveが出るのを防ぐ）
- **public インスタンス** (`mute_join_leave_in_public: true`): Join/Leave/Video/Image を抑制
- **イベント個別**: `config.json` の `events` で true/false 切替

---

## Discord 送信

### バッチング

Join/Leave が短時間に連続する場合、5秒のウィンドウでまとめて1つのEmbedとして送信。
1人だけの場合は個別Embed、2人以上はバッチEmbed（`📥 Player joined（3人）`）。

### レート制限

429応答 → `retry_after` 秒待機してリトライ。

### 起動/停止メッセージ

- 起動: `🟢 VRChat Logger 起動しました`
- 停止: `🔴 VRChat Logger 停止しました`

---

## ログファイル監視 (LogWatcher)

- **方式**: ジェネレーター (`yield`) で新しい行を返す
- **ポーリング間隔**: `poll_interval_sec` (デフォルト 1秒)
- **ログローテーション**: `rotation_check_interval_sec` 間隔で最新の `output_log_*.txt` を確認し、変わっていたら切り替え
- **起動時**: 最新ログの末尾にシーク（過去ログは読まない）

---

## config.json

```json
{
    "discord_webhook_url": "https://discord.com/api/webhooks/...",
    "vrchat_log_dir": "C:\\Users\\...\\VRChat\\VRChat",
    "poll_interval_sec": 1.0,
    "rotation_check_interval_sec": 30,
    "events": {
        "on_left_room": true,
        "player_joined": true,
        "player_left": true,
        "video_playback": true,
        "image_download": true
    },
    "filter": {
        "show_self_join_leave": false,
        "mute_join_leave_in_public": true
    },
    "embed_colors": {
        "entering_room": 3447003,
        "player_joined": 3066993,
        "player_left": 15158332,
        "disconnect": 15548997,
        "self_event": 10181046,
        "video": 16750848
    }
}
```
