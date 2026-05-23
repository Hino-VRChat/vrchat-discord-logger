"""
events.py — イベントデータクラス定義
VRChatログから抽出されたイベントを表現する。
"""

from dataclasses import dataclass, field


@dataclass
class VRChatEvent:
    """全イベント共通の基底クラス"""
    timestamp: str  # "YYYY.MM.DD HH:MM:SS"
    raw_line: str   # パース元の生ログ行


@dataclass
class VRDisabledEvent(VRChatEvent):
    """VRモードがOFF"""
    pass


@dataclass
class UserAuthenticatedEvent(VRChatEvent):
    """ユーザー認証完了"""
    user_name: str          # ユーザー名
    user_id: str            # ユーザーID
    vr_mode: bool = True    # False = デスクトップ / True = VR


@dataclass
class EnteringRoomEvent(VRChatEvent):
    """ワールド移動"""
    world_name: str
    world_url: str = ""  # JoiningWorldEventから後付けされる


@dataclass
class JoiningWorldEvent(VRChatEvent):
    """ワールドJoin（インスタンス詳細情報）"""
    world_id: str          # wrld_XXXX
    instance_number: str   # 5桁の数字
    access_type: str       # hidden / friends / private / invite+ / group / group+ / group-public / public
    owner_id: str          # usr_XXXX（group/publicの場合は空文字）
    region: str            # jp / us / eu
    group_id: str = ""     # grp_XXXX（groupインスタンスの場合）
    world_name: str = ""   # EnteringRoomEventから後付け


@dataclass
class PlayerJoinedEvent(VRChatEvent):
    """プレイヤーJoin"""
    player_name: str
    player_id: str  # usr_XXXX


@dataclass
class PlayerLeftEvent(VRChatEvent):
    """プレイヤーLeave"""
    player_name: str
    player_id: str  # usr_XXXX


@dataclass
class ImageDownloadEvent(VRChatEvent):
    """画像ダウンロード"""
    url: str


@dataclass
class VideoPlaybackEvent(VRChatEvent):
    """動画再生（URL解決 / タイトル取得）"""
    content: str  # URLまたはタイトル


@dataclass
class OnLeftRoomEvent(VRChatEvent):
    """自分がルームを抜けた"""
    pass


@dataclass
class ShutdownEvent(VRChatEvent):
    """VRChatが終了した"""
    pass

