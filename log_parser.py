"""
log_parser.py — ログパースモジュール
VRChatのoutput_logの行を正規表現でマッチし、イベントオブジェクトに変換する。
"""

import re
from events import (
    VRChatEvent, EnteringRoomEvent, JoiningWorldEvent,
    PlayerJoinedEvent, PlayerLeftEvent, VideoPlaybackEvent,
    OnLeftRoomEvent, ImageDownloadEvent,
)

# タイムスタンプ抽出（全行共通）
TIMESTAMP_RE = re.compile(r"^(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})")

# イベントパターン（順序はマッチ優先度）
EVENT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("entering_room", re.compile(
        r"\[Behaviour\] Entering Room: (.+)$"
    )),
    ("joining_world", re.compile(
        r"\[Behaviour\] Joining (wrld_[0-9a-f\-]+):(\d{5})"
        r"(?:~(hidden|friends|private)\((usr_[0-9a-f\-]+)\))?"
        r"(?:~canRequestInvite)?"
        r"(?:~group\((grp_[0-9a-f\-]+)\))?"
        r"(?:~groupAccessType\((\w+)\))?"
        r"~region\((\w+)\)"
    )),
    ("player_joined", re.compile(
        r"\[Behaviour\] OnPlayerJoined (.+?) \((usr_[0-9a-f\-]+)\)"
    )),
    ("player_left", re.compile(
        r"\[Behaviour\] OnPlayerLeft (.+?) \((usr_[0-9a-f\-]+)\)"
    )),
    ("image_download", re.compile(
        r"\[Image Download\] Attempting to load image from URL '(.+?)'"
    )),
    # 動画再生: [Video Playback] のURL解決
    ("video_playback", re.compile(
        r"\[Video Playback\] Attempting to resolve URL '(.+?)'"
    )),
    ("on_left_room", re.compile(
        r"\[Behaviour\] OnLeftRoom$"
    )),

]


def extract_timestamp(line: str) -> str:
    """行からタイムスタンプを抽出。見つからなければ空文字。"""
    m = TIMESTAMP_RE.match(line)
    return m.group(1) if m else ""


def parse_line(line: str) -> VRChatEvent | None:
    """ログ行をパースし、マッチしたイベントオブジェクトを返す。
    マッチしなければ None。"""
    timestamp = extract_timestamp(line)

    for name, pattern in EVENT_PATTERNS:
        m = pattern.search(line)
        if not m:
            continue

        if name == "entering_room":
            return EnteringRoomEvent(
                timestamp=timestamp, raw_line=line,
                world_name=m.group(1),
            )
        elif name == "joining_world":
            # アクセスタイプ決定
            group_id = m.group(5) or ""
            group_access = m.group(6) or ""
            if group_id:
                # group系: groupAccessType で分岐
                access = {
                    "members": "group",
                    "plus": "group+",
                    "public": "group-public",
                }.get(group_access, f"group({group_access})")
            elif m.group(3):
                # private系: canRequestInvite は非キャプチャなので有無で判定
                # canRequestInvite があれば invite+ だが、非キャプチャにしたので
                # 文字列 "canRequestInvite" が raw_line に含まれるかで判定
                access = m.group(3)
                if "~canRequestInvite~" in line:
                    access = "invite+"
            else:
                access = "public"
            return JoiningWorldEvent(
                timestamp=timestamp, raw_line=line,
                world_id=m.group(1),
                instance_number=m.group(2),
                access_type=access,
                owner_id=m.group(4) or "",
                region=m.group(7),
                group_id=group_id,
            )
        elif name == "player_joined":
            return PlayerJoinedEvent(
                timestamp=timestamp, raw_line=line,
                player_name=m.group(1), player_id=m.group(2),
            )
        elif name == "player_left":
            return PlayerLeftEvent(
                timestamp=timestamp, raw_line=line,
                player_name=m.group(1), player_id=m.group(2),
            )
        elif name == "image_download":
            return ImageDownloadEvent(
                timestamp=timestamp, raw_line=line,
                url=m.group(1),
            )
        elif name == "video_playback":
            return VideoPlaybackEvent(
                timestamp=timestamp, raw_line=line,
                content=m.group(1),
            )
        elif name == "on_left_room":
            return OnLeftRoomEvent(
                timestamp=timestamp, raw_line=line,
            )


    return None
