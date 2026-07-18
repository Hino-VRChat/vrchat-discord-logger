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
| `UserAuthenticatedEvent` | `User Authenticated: ...` | ✅ VRChat started（User + VR/Desktopモード） |
| `VRDisabledEvent` | `VR Disabled` | ※送信しない（Desktopモード判定用の内部状態） |
| `EnteringRoomEvent` | `[Behaviour] Entering Room: ...` | ※送信しない（world_name を JoiningWorldEvent に統合） |
| `JoiningWorldEvent` | `[Behaviour] Joining wrld_...` | 🌍 ワールド名 + Access/Region/Owner/Group |
| `PlayerJoinedEvent` | `[Behaviour] OnPlayerJoined ...` | 📥 Player joined |
| `PlayerLeftEvent` | `[Behaviour] OnPlayerLeft ...` | 📤 Player left |
| `ImageDownloadEvent` | `[Image Download] Attempting to load image from URL ...` | 🖼️ Image download（プレビュー付き） |
| `VideoPlaybackEvent` | `[Video Playback] Attempting to resolve URL ...` | 🎬 Video playback |
| `BoopEvent` | `Received Notification: ... of type: boop ...` | 👋 Booped me!（Sender + Boop種別） |
| `OnLeftRoomEvent` | `[Behaviour] OnLeftRoom` | ※送信しない（ロード中の中間状態のため。退出中フラグ用） |
| `ShutdownEvent` | `UserInterface destroyed` | ⏻ VRChat Shutdown |

### EnteringRoom → JoiningWorld 統合

VRChatのログでは `Entering Room:` の直後に `Joining wrld_...` が出る。
`EnteringRoomEvent` は保留（pending_room）し、直後の `JoiningWorldEvent` に `world_name` を統合して1つのEmbedとして送信する。

### 重複抑制（main.py）

- **UserAuthenticated**: 同一タイムスタンプの2行目をスキップ（同内容が2行出るため）
- **Image / Video**: 直前と同一URLをスキップ（リトライ/フォールバックによる重複対策）。ワールド移動でリセット

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
| `current_access_type` | 現在のインスタンス種別。OnLeftRoom / Shutdown でクリア |
| `is_leaving_world` | OnLeftRoom / Shutdown 後にON、次の JoiningWorld でリセット |

### フィルタルール

```
[通常] ──(OnLeftRoom / Shutdown)──► [退出中: Leave全無視]
                                          │
                                   (Joining wrld)
                                          │
                                          ▼
                                       [通常]
```

- **JoiningWorld**: 常に通知（access_type を記憶、退出中フラグをリセット）
- **OnLeftRoom**: 退出中フラグON + access_type クリア + 通知しない
- **Shutdown**: 退出中フラグON + access_type クリア + ⏻ Embed を通知
- **PlayerLeft + 退出中フラグON**: 抑制（自分の退出時に全員分のLeaveが出るのを防ぐ）
- **public / group-public インスタンス** (`mute_join_leave_in_public: true`): Join/Leave/Video/Image を抑制
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

## 多重起動ガード

起動時に名前付きMutex（`VRChatDiscordLogger`）を `CreateMutexW` で作成し、`ERROR_ALREADY_EXISTS`（183）が返ったら既に起動中と判定して終了する。

- 検出時は返ってきた既存Mutexへのハンドルを `CloseHandle` してから終了（参照を残さない）
- 保持側のハンドルはプロセス終了時にOSが自動で閉じるため、クラッシュしてもロックは残らない
- `GetLastError` は `use_last_error=True` + `ctypes.get_last_error()` で取得する（`ctypes.windll` 経由だと他のAPI呼び出しで上書きされる可能性がある）

## ログファイル監視 (LogWatcher)

- **方式**: ジェネレーター (`yield`) で新しい行を返す
- **ポーリング間隔**: `poll_interval_sec` (デフォルト 1秒)
- **ログローテーション**: `rotation_check_interval_sec` 間隔で最新の `output_log_*.txt` を確認し、変わっていたら切り替え（切替後は先頭から読む）
- **起動時**: 最新ログの末尾にシーク（過去ログは読まない）
- **ログ未発見時**: ログファイルが現れるまで待機（VRChatより先に起動してOK）。待機後に現れたログは先頭から読む

---

## config.json

```json
{
    "discord_webhook_url": "https://discord.com/api/webhooks/...",
    "vrchat_log_dir": "C:\\Users\\...\\VRChat\\VRChat",
    "poll_interval_sec": 1.0,
    "rotation_check_interval_sec": 30,
    "events": {
        "player_joined": true,
        "player_left": true,
        "image_download": true,
        "video_playback": true,
        "boop": true
    },
    "filter": {
        "mute_join_leave_in_public": true
    },
    "embed_colors": {
        "user_authenticated": 32768,
        "entering_room": 3447003,
        "player_joined": 3066993,
        "player_left": 15158332,
        "image": 1752220,
        "video": 1752220,
        "boop": 16738740,
        "shutdown": 15548997
    }
}
```

- `vrchat_log_dir` が空欄なら `%APPDATA%` から `LocalLow\VRChat\VRChat` を自動検出
- `--config <path>`（`-c`）でスクリプト外の config.json を指定できる。省略時は `main.py` と同じディレクトリの `config.json` を読む
