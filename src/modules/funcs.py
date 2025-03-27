#  Copyright (c) 2025 AshokShau.
#  TgMusicBot is an open-source Telegram music bot licensed under AGPL-3.0.
#  All rights reserved where applicable.
#

import re
from typing import Union

from pyrogram import types, Client, filters

from src.database import db
from src.logger import LOGGER
from src.modules.play import play_music, _get_platform_url
from src.modules.utils import PauseButton, ResumeButton, sec_to_min
from src.modules.utils.admins import is_admin
from src.modules.utils.cacher import chat_cache
from src.modules.utils.play_helpers import extract_argument, del_msg, edit_text
from src.platforms.downloader import MusicServiceWrapper
from src.pytgcalls import call


async def is_admin_or_reply(msg: types.Message) -> Union[int, types.Message]:
    """Check if user is admin and if a song is playing."""
    chat_id = msg.chat.id

    if not await chat_cache.is_active(chat_id):
        return await msg.reply_text(text="❌ No song is currently playing.")

    if not await is_admin(chat_id, msg.from_user.id):
        return await msg.reply_text("You must be an admin to use this command.")

    return chat_id


async def handle_playback_action(
    msg: types.Message, action, success_msg: str, fail_msg: str
) -> None:
    """Handle playback actions like stop, pause, resume, mute, unmute."""
    chat_id = await is_admin_or_reply(msg)
    if isinstance(chat_id, types.Message):
        return

    try:
        await action(chat_id)
        await msg.reply_text(
            f"{success_msg}\n│ \n└ Requested by: {msg.from_user.mention} 🥀"
        )
    except Exception as e:
        LOGGER.error(f"Error in {action.__name__}: {e}")
        await msg.reply_text(f"⚠️ {fail_msg}\nError: {e}")


@Client.on_message(filters.command("setPlayType"))
async def set_play_type(_: Client, msg: types.Message) -> None:
    if msg.chat.id > 0:
        return

    play_type = extract_argument(msg.text, enforce_digit=True)
    if not play_type:
        await msg.reply_text(
            text="Usage: /setPlayType 0/1\n\n0 = Directly play the first search result.\n1 = Show a list of songs to choose from."
        )
        return

    play_type = int(play_type)
    if play_type not in (0, 1):
        await msg.reply_text("Invalid option! Please use: /setPlayType 0/1")
        return

    try:
        await db.set_play_type(msg.chat.id, play_type)
        await msg.reply_text(f"✅ Play type set to {play_type}")
    except Exception as e:
        LOGGER.error(f"Error setting play type: {e}")
        await msg.reply_text("⚠️ Failed to set play type. Please try again.")


@Client.on_message(filters.command("queue"))
async def queue_info(_: Client, msg: types.Message) -> None:
    chat_id = msg.chat.id
    if chat_id > 0:
        return

    chat = msg.chat
    _queue = await chat_cache.get_queue(chat_id)
    if not _queue:
        await msg.reply_text(text="🛑 The queue is empty. No tracks left to play!")
        return

    if not await chat_cache.is_active(chat_id):
        await msg.reply_text(text="❌ No song is currently playing in this chat!")
        return

    current_song = _queue[0]
    text = (
        f"<b>🎶 Current Queue in {chat.title}:</b>\n\n"
        f"<b>Currently Playing:</b>\n"
        f"‣ <b>{current_song.name[:30]}</b>\n"
        f"   ├ <b>By:</b> {current_song.user}\n"
        f"   ├ <b>Duration:</b> {sec_to_min(current_song.duration)} minutes\n"
        f"   ├ <b>Loop:</b> {current_song.loop}\n"
        f"   └ <b>Played Time:</b> {sec_to_min(await call.played_time(chat.id))} min"
    )

    if queue_remaining := _queue[1:]:
        text += "\n<b>⏭ Next in Queue:</b>\n"
        for i, song in enumerate(queue_remaining, start=1):
            text += (
                f"{i}. <b>{song.name[:30]}</b>\n"
                f"   ├ <b>Duration:</b> {sec_to_min(song.duration)} min\n"
            )

    text += f"\n<b>» Total of {len(_queue)} track(s) in the queue.</b>"
    if len(text) > 4096:
        short_text = f"<b>🎶 Current Queue in {chat.title}:</b>\n\n"
        short_text += "<b>Currently Playing:</b>\n"
        short_text += f"‣ <b>{current_song.name[:30]}</b>\n"
        short_text += f"   ├ <b>By:</b> {current_song.user}\n"
        short_text += (
            f"   ├ <b>Duration:</b> {sec_to_min(current_song.duration)} minutes\n"
        )
        short_text += f"   ├ <b>Loop:</b> {current_song.loop}\n"
        short_text += f"   └ <b>Played Time:</b> {sec_to_min(await call.played_time(chat.id))} min"
        short_text += f"\n\n<b>» Total of {len(_queue)} track(s) in the queue.</b>"
        text = short_text
    await msg.reply_text(text, disable_web_page_preview=True)


@Client.on_message(filters.command("loop"))
async def modify_loop(_: Client, msg: types.Message) -> None:
    chat_id = msg.chat.id
    if chat_id > 0:
        return

    args = extract_argument(msg.text, enforce_digit=True)
    if not await is_admin(chat_id, msg.from_user.id):
        await msg.reply_text("You need to be an admin to use this command")
        return

    if not await chat_cache.is_active(chat_id):
        await msg.reply_text("❌ No song is currently playing in this chat!")
        return

    if not args:
        await msg.reply_text(
            "🛑 Usage: /loop times\n\nExample: /loop 5 will loop the current song 5 times or 0 to disable"
        )
        return

    loop = int(args)
    try:
        await chat_cache.set_loop_count(chat_id, loop)
        action = "disabled" if loop == 0 else f"changed to {loop} times"
        await msg.reply_text(
            f"🔄 Loop {action}\n│ \n└ Action by: {msg.from_user.mention}"
        )
    except Exception as e:
        LOGGER.error(f"Error setting loop: {e}")
        await msg.reply_text(f"⚠️ Something went wrong...\n\nError: {str(e)}")


@Client.on_message(filters.command("seek"))
async def seek_song(_: Client, msg: types.Message) -> None:
    chat_id = msg.chat.id
    if chat_id > 0:
        return

    args = extract_argument(msg.text, enforce_digit=True)
    if not args:
        await msg.reply_text(
            "🛑 Usage: /seek seconds (must be a number greater than 20)"
        )
        return

    seek_time = int(args)
    if seek_time < 20:
        await msg.reply_text("🛑 Invalid input! Seconds must be greater than 20.")
        return

    curr_song = await chat_cache.get_current_song(chat_id)
    if not curr_song:
        await msg.reply_text("❌ No song is currently playing in this chat!")
        return

    curr_dur = await call.played_time(chat_id)
    seek_to = curr_dur + seek_time

    if seek_to >= curr_song.duration:
        await msg.reply_text(
            f"🛑 Cannot seek past the song duration ({sec_to_min(curr_song.duration)} min)."
        )
        return

    try:
        await call.seek_stream(
            chat_id, curr_song.file_path, seek_to, curr_song.duration
        )
        await msg.reply_text(
            f"⏩ Seeked to {seek_to} seconds\n│ \n└ Action by: {msg.from_user.mention}"
        )
    except Exception as e:
        LOGGER.error(f"Error seeking song: {e}")
        await msg.reply_text(f"⚠️ Something went wrong...\n\nError: {str(e)}")


def extract_number(text: str) -> float | None:
    match = re.search(r"[-+]?\d*\.?\d+", text)
    return float(match.group()) if match else None


@Client.on_message(filters.command("speed"))
async def change_speed(_: Client, msg: types.Message) -> None:
    chat_id = msg.chat.id
    if chat_id > 0:
        return

    args = extract_number(msg.text)
    if args is None:
        await msg.reply_text(
            "🛑 Usage: /speed speed (must be a number between 0.5 and 4.0)"
        )
        return

    if not await is_admin(chat_id, msg.from_user.id):
        await msg.reply_text("You need to be an admin to use this command")
        return

    if not await chat_cache.is_active(chat_id):
        await msg.reply_text("❌ No song is currently playing in this chat!")
        return

    speed = round(float(args), 2)
    try:
        await call.speed_change(chat_id, speed)
        await msg.reply_text(
            f"🚀 Speed changed to {speed}\n│ \n└ Action by: {msg.from_user.mention}"
        )
    except Exception as e:
        LOGGER.error(f"Error changing speed: {e}")
        await msg.reply_text(f"⚠️ Something went wrong...\n\nError: {str(e)}")


@Client.on_message(filters.command("remove"))
async def remove_song(_: Client, msg: types.Message) -> None:
    chat_id = msg.chat.id
    if chat_id > 0:
        return

    args = extract_argument(msg.text, enforce_digit=True)
    if not await is_admin(chat_id, msg.from_user.id):
        await msg.reply_text("You need to be an admin to use this command")
        return

    if not await chat_cache.is_active(chat_id):
        await msg.reply_text("❌ No song is playing in this chat!")
        return

    if not args:
        await msg.reply_text("🛑 Usage: /remove track number (must be a valid number)")
        return

    track_num = int(args)
    _queue = await chat_cache.get_queue(chat_id)

    if not _queue:
        await msg.reply_text("🛑 The queue is empty. No tracks to remove.")
        return

    if track_num <= 0 or track_num > len(_queue):
        await msg.reply_text(
            f"🛑 Invalid track number! The current queue has {len(_queue)} tracks."
        )
        return

    try:
        await chat_cache.remove_track(chat_id, track_num)
        await msg.reply_text(
            f"✔️ Track removed from queue\n│ \n└ Removed by: {msg.from_user.mention}"
        )
    except Exception as e:
        LOGGER.error(f"Error removing track: {e}")
        await msg.reply_text(f"⚠️ Something went wrong...\n\nError: {str(e)}")


@Client.on_message(filters.command("clear"))
async def clear_queue(_: Client, msg: types.Message) -> None:
    chat_id = msg.chat.id
    if chat_id > 0:
        return

    if not await is_admin(chat_id, msg.from_user.id):
        await msg.reply_text("You need to be an admin to use this command")
        return

    if not await chat_cache.is_active(chat_id):
        await msg.reply_text("❌ No song is currently playing in this chat!")
        return

    if not await chat_cache.get_queue(chat_id):
        await msg.reply_text("🛑 The queue is already empty!")
        return

    try:
        await chat_cache.clear_chat(chat_id)
        await msg.reply_text(
            f"🗑️ Queue cleared\n│ \n└ Action by: {msg.from_user.mention}"
        )
    except Exception as e:
        LOGGER.error(f"Error clearing queue: {e}")
        await msg.reply_text(f"⚠️ Something went wrong...\n\nError: {str(e)}")


@Client.on_message(filters.command(["stop", "end"]))
async def stop_song(_: Client, msg: types.Message) -> None:
    chat_id = await is_admin_or_reply(msg)
    if isinstance(chat_id, types.Message):
        return

    try:
        await call.end(chat_id)
        await msg.reply_text(
            f"🎵 <b>Stream Ended</b> ❄️\n│ \n└ Requested by: {msg.from_user.mention} 🥀"
        )
    except Exception as e:
        LOGGER.error(f"Error stopping song: {e}")
        await msg.reply_text(f"⚠️ Failed to stop the song.\nError: {str(e)}")


@Client.on_message(filters.command("pause"))
async def pause_song(_: Client, msg: types.Message) -> None:
    await handle_playback_action(
        msg, call.pause, "⏸️ <b>Stream Paused</b> 🥺", "Failed to pause the song"
    )


@Client.on_message(filters.command("resume"))
async def resume(_: Client, msg: types.Message) -> None:
    await handle_playback_action(
        msg, call.resume, "🎶 <b>Stream Resumed</b> 💫", "Failed to resume the song"
    )


@Client.on_message(filters.command("mute"))
async def mute_song(_: Client, msg: types.Message) -> None:
    await handle_playback_action(
        msg, call.mute, "🔇 <b>Stream Muted</b>", "Failed to mute the song"
    )


@Client.on_message(filters.command("unmute"))
async def unmute_song(_: Client, msg: types.Message) -> None:
    await handle_playback_action(
        msg, call.unmute, "🔊 <b>Stream Unmuted</b>", "Failed to unmute the song"
    )


@Client.on_message(filters.command("volume"))
async def volume(_: Client, msg: types.Message) -> None:
    chat_id = await is_admin_or_reply(msg)
    if isinstance(chat_id, types.Message):
        return

    args = extract_argument(msg.text, enforce_digit=True)
    if not args:
        await msg.reply_text("⚠️ Usage: /volume 1-200")
        return

    vol_int = int(args)
    if vol_int == 0:
        await msg.reply_text("🔇 Use /mute to mute the song.")
        return

    if not 1 <= vol_int <= 200:
        await msg.reply_text(
            "⚠️ Volume must be between 1 and 200.\nUsage: /volume 1-200"
        )
        return

    try:
        await call.change_volume(chat_id, vol_int)
        await msg.reply_text(
            f"🔊 <b>Stream volume set to {vol_int}</b>\n│ \n└ Requested by: {msg.from_user.mention} 🥀"
        )
    except Exception as e:
        LOGGER.error(f"Error changing volume: {e}")
        await msg.reply_text(f"⚠️ Failed to change volume.\nError: {e}")


@Client.on_message(filters.command("skip"))
async def skip_song(_: Client, msg: types.Message) -> None:
    chat_id = await is_admin_or_reply(msg)
    if isinstance(chat_id, types.Message):
        return

    try:
        await del_msg(msg)
        await call.play_next(chat_id)
        await msg.reply_text(
            f"⏭️ Song skipped\n│ \n└ Requested by: {msg.from_user.mention} 🥀"
        )
    except Exception as e:
        LOGGER.error(f"Error skipping song: {e}")
        await msg.reply_text(f"⚠️ Failed to skip the song.\nError: {e}")


@Client.on_callback_query(filters.regex(r"play_\w+"))
async def callback_query(_: Client, message: types.CallbackQuery) -> None:
    data = message.data
    chat_id = message.message.chat.id
    user = message.from_user

    async def send_response(
        msg: str, alert: bool = False, delete: bool = False, markup=None
    ) -> None:
        if alert:
            await message.answer(msg, show_alert=True)
        else:
            if message.message.caption:
                await edit_text(msg=message.message, text=msg, reply_markup=markup)
                return
            else:
                await edit_text(msg=message.message, text=msg, reply_markup=markup)
        if delete:
            await del_msg(message.message)

    if data == "play_skip":
        if not await chat_cache.is_active(chat_id):
            return await send_response(
                "❌ Nothing is currently playing in this chat.", alert=True
            )

        try:
            await call.play_next(chat_id)
            await send_response("⏭️ Song skipped", delete=True)
        except Exception as e:
            LOGGER.warning(f"Could not skip song: {e}")
            return await send_response(
                "⚠️ Error: Next song not found to play.", alert=True
            )

    elif data == "play_stop":
        if not await chat_cache.is_active(chat_id):
            return await send_response(
                f"<b>➻ Stream stopped:</b>\n└ Requested by: {user.first_name}"
            )

        try:
            await chat_cache.clear_chat(chat_id)
            await call.end(chat_id)
            await send_response(
                f"<b>➻ Stream stopped:</b>\n└ Requested by: {user.first_name}"
            )
        except Exception as e:
            LOGGER.warning(f"Error stopping stream: {e}")
            return await send_response(
                "⚠️ Error stopping the stream. Please try again.", alert=True
            )

    elif data == "play_pause":
        if not await chat_cache.is_active(chat_id):
            return await send_response(
                "❌ Nothing is currently playing in this chat.", alert=True
            )

        try:
            await call.pause(chat_id)
            await send_response(
                f"<b>➻ Stream paused:</b>\n└ Requested by: {user.first_name}",
                markup=PauseButton,
            )
        except Exception as e:
            LOGGER.warning(f"Error pausing stream: {e}")
            return await send_response(
                "⚠️ Error pausing the stream. Please try again.", alert=True
            )

    elif data == "play_resume":
        if not await chat_cache.is_active(chat_id):
            return await send_response(
                "❌ Nothing is currently playing in this chat.", alert=True
            )

        try:
            await call.resume(chat_id)
            await send_response(
                f"<b>➻ Stream resumed:</b>\n└ Requested by: {user.first_name}",
                markup=ResumeButton,
            )
        except Exception as e:
            LOGGER.warning(f"Error resuming stream: {e}")
            return await send_response(
                "⚠️ Error resuming the stream. Please try again.", alert=True
            )

    else:
        LOGGER.info("Playing song, data %s", data)
        _, platform, song_id = data.split("_", 2)
        await message.answer(f"Playing song for {user.first_name}", show_alert=True)
        reply_message = await edit_text(
            msg=message.message,
            text=f"🎶 Searching ...\nRequested by: {user.first_name} 🥀",
        )

        url = _get_platform_url(platform, song_id)
        if not url:
            return await edit_text(
                reply_message, text=f"⚠️ Error: Invalid Platform WTF ? {platform}"
            )

        if _song := await MusicServiceWrapper(url).get_info():
            return await play_music(reply_message, _song, user.first_name)

        return await edit_text(
            reply_message, text="⚠️ Error: Song not found on Spotify. (Data not found)"
        )
