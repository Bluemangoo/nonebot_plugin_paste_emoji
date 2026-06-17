from typing import Tuple

from nonebot import logger, Bot
from nonebot.adapters.onebot.v11 import MessageEvent, GroupMessageEvent, GROUP
from nonebot.internal.rule import Rule
from nonebot.plugin import PluginMetadata
from nonebot.plugin.on import on_command, on_message

"""
对 emoji 的处理实质上是将其转换为对应的 unicode 编码。
对于转换的解释：
    utf-32-be: UTF-32 Big-Endian（大端序 UTF-32）保证了每个字符占用 4 个字节，即非组合的单个 emoji 一定占用一个字符。
    [:4] 取前 4 个字节(encode -> bytes)，确保我们只处理单个 emoji。同时 qq api 内表情 id 为 uint32，即 4 个字节。
        uint32 这点见 https://bot.q.qq.com/wiki/develop/api-v2/openapi/emoji/model.html
        虽然 NTQQ 的 api 里用的是 string，但越界会有极为诡异的表现。
        njs api: session.getMsgService().setMsgEmojiLikes (peer: Peer, msgSeq: string, emojiId: string, emojiType: string, setOrCancel: boolean)
    from_bytes 的 big 是端序，与 utf-32-be 保持一致。
    最后过滤一些特殊情况，这些字符直接用 ASCII 加上变体选择符 emoji，会直接与 QQ 系统表情 ID 冲突。以免歧义直接过滤掉。
其它情况：
    1. 纯数字，直接当做表情 ID。
    2. 以 u+/0x/u 开头或以 h 结尾的字符串，尝试解析为十六进制数。
    位运算看不明白自己补习去。
"""

__plugin_meta__ = PluginMetadata(
    name="贴表情",
    description="QQ群 向命令这条消息贴指定表情，用于获取并传递表情。",
    usage="/贴表情 [表情ID] 或 /贴表情 [表情]",
    homepage="https://github.com/Bluemangoo/nonebot_plugin_paste_emoji",
    extra={
        "author": "https://github.com/bluemangoo",
    },
)


def try_remove_prefixes(s: str, prefixes: list[str]) -> str | None:
    for prefix in prefixes:
        if s.startswith(prefix):
            return s[len(prefix):]
    return None


def try_remove_suffixes(s: str, suffixes: list[str]) -> str | None:
    for suffix in suffixes:
        if s.endswith(suffix):
            return s[:-len(suffix)]
    return None


def try_parse_emoji(emoji_id: str) -> str | None:
    if emoji_id.isnumeric():
        emoji_int_id = int(emoji_id)
        if emoji_int_id >> 32 > 0:
            return None  # 越界
    elif (stripped := try_remove_prefixes(emoji_id.lower(), ["u+", "0x", "u"])) or \
            (stripped := try_remove_suffixes(emoji_id.lower(), ["h"])):
        try:
            emoji_int_id = int(stripped, 16)  # try parse as hex
            if emoji_int_id >> 32 == 0:
                emoji_id = str(emoji_int_id)
            else:
                return None  # 越界
        except ValueError:
            return None
    else:
        emoji_int_id = int.from_bytes(emoji_id.encode('utf-32-be')[:4], 'big')  # [:4] = uint32
        if emoji_int_id <= 256:
            return None  # Filter ascii: Emoji Keycap Sequences = 0-9/#/* + U+FE0F(VS16) + U+20E3
        emoji_id = str(emoji_int_id)
    return emoji_id


def is_zhu(event: GroupMessageEvent):
    return (str(event.group_id), str(event.user_id)) in zhu_list


paste_face = on_command("paste_face",
                        aliases={"贴表情", "paste-face"},
                        priority=5,
                        permission=GROUP,
                        force_whitespace=True)
help_yourself = on_command("自㊗️餐", aliases={"自㊗餐"}, priority=5)
stop_help_yourself = on_command("停止自㊗️餐",
                                aliases={f"{i}自{j}餐" for i in ["停止", "结束", "关闭"] for j in ["㊗️", "㊗"]},
                                priority=5,
                                permission=GROUP)
paste_it = on_message(rule=Rule(is_zhu), priority=6, permission=GROUP, block=False)  # 5+1
zhu_list: list[Tuple[str, str]] = []


@paste_face.handle()
async def _(event: MessageEvent, bot: Bot):
    args: list[str] = []
    for seg in event.message:
        if seg.type == "text":
            text = seg.data.get("text", "").strip()
            if text:
                args.extend(text.split(" "))
        if seg.type == "face":
            args.append(seg.data.get("id", ""))

    args = [arg for arg in args if arg][1:]  # 去掉命令本身
    emojis = [emoji for arg in args if (emoji := try_parse_emoji(arg)) is not None]
    logger.debug(f"Parsed emoji_id: {emojis}")
    message_id = event.message_id
    if event.reply:
        message_id = event.reply.message_id
    for emoji_id in emojis:
        payloads = {
            "message_id": message_id,
            "emoji_id": emoji_id,
            "set": True
        }
        logger.debug(await bot.call_api("set_msg_emoji_like", **payloads))


def parse_users(event: GroupMessageEvent) -> list[str]:
    at: list[str] = []
    for seg in event.message:
        if seg.type == "at":
            s = seg.data.get("qq", "")
            if s and s != "all":
                at.append(s)
    if len(at) == 0:
        at.append(str(event.user_id))
    return at


@help_yourself.handle()
async def _(event: GroupMessageEvent):
    for qq in parse_users(event):
        zhu_list.append((str(event.group_id), qq))
    await help_yourself.finish("用餐愉快")


@stop_help_yourself.handle()
async def _(event: GroupMessageEvent):
    for qq in parse_users(event):
        try:
            zhu_list.remove((str(event.group_id), qq))
        except ValueError:
            pass
    await stop_help_yourself.finish("感谢您的光临")


@paste_it.handle()
async def _(event: GroupMessageEvent, bot: Bot):
    payloads = {
        "message_id": event.message_id,
        "emoji_id": "12951",
        "set": True
    }
    logger.debug(await bot.call_api("set_msg_emoji_like", **payloads))
