from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os
import json
import asyncio
import time
import re
import random
from collections import defaultdict, deque

# =========================================================
# 1. BOT SETTINGS
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="",
    intents=intents,
    case_insensitive=True,
    status=discord.Status.dnd,
    activity=discord.Activity(type=discord.ActivityType.listening, name="!help | /help"),
)

# =========================================================
# 2. PER-SERVER CONFIG (saved in guild_config.json)
# =========================================================
# بۆ ئەوەی ڕێکخستنەکان لە Railway دوای ئەپدەیت/ڕیدیپلۆی نەسڕێنەوە:
#   1) لە Railway Volume دروست بکە و Mount Path بکە بە  /data
#   2) ئەگەر /data هەبێت بۆتەکە خۆکار لەوێ هەڵیدەگرێت
#   (یان Variable بەناوی CONFIG_PATH دابنێ)

if os.getenv("CONFIG_PATH"):
    CONFIG_FILE = os.getenv("CONFIG_PATH")
elif os.path.isdir("/data"):
    CONFIG_FILE = "/data/guild_config.json"
else:
    CONFIG_FILE = "guild_config.json"

LOG_TYPES = {
    "welcome": "Welcome",
    "server": "Server Log",
    "chat": "Chat Log",
    "voice": "Voice Log",
    "ban": "Ban Log",
    "left": "Left Log",
    "channel": "Channel Log",
    "role": "Role Log",
    "member": "Member Log",
    "nickname": "Nickname Log",
}

PERM_LABELS = {
    "mute": "Mute",
    "ban": "Ban (Bfra / Unban)",
    "safika": "Safika (Clear)",
    "staff": "Staff (/staff)",
}

# ناوی پیشاندراوی ستافەکان (value ەکان وەک خۆیان ماونەتەوە بۆ ئەوەی ڕێکخستنە کۆنەکان نەچن)
STAFF_LABELS = {
    "staff1": "Lady Staff",
    "staff2": "Boy Staff",
}

BOT_OWNER_ID = 1130455970494025860  # Bot owner: full control without needing a server role

NO_PERM_TEXT = "To regat penadrawa ta ama bakar bhenit"

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
except Exception:
    config = {}


def save_config():
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except Exception as e:
        print(f"save_config error: {e}")


def cfg(guild_id):
    d = config.setdefault(str(guild_id), {})
    d.setdefault("channels", {})       # welcome + log channels
    d.setdefault("roles", {})          # staff1, staff2
    d.setdefault("regri_roles", [])    # roles allowed to use /regri
    d.setdefault("restricted", [])     # users blocked from color change
    d.setdefault("color_roles", [])    # roles allowed to use /rangi-role (/regadan-ranggorin)
    d.setdefault("color_users", [])    # specific users allowed to use /rangi-role (/regadan-ranggorin)
    d.setdefault("welcome_text", "Baxer beyt")
    d.setdefault("welcome_image", None)  # image / gif link shown under the welcome text
    d.setdefault("dev_roles", [])      # developer roles (full control like owner)
    d.setdefault("mute_role", None)    # role given on mute (set with /setmuterole)
    d.setdefault("autorole", None)     # OLD single autorole (migrated into autoroles)
    d.setdefault("autoroles", [])      # roles given automatically to new members (/autorole)
    if d.get("autorole"):
        if d["autorole"] not in d["autoroles"]:
            d["autoroles"].append(d["autorole"])
        d["autorole"] = None
    perm = d.setdefault("perm_roles", {})  # roles allowed: mute / ban / safika / staff
    for k in PERM_LABELS:
        perm.setdefault(k, [])
    bl = d.setdefault("perm_blacklist", {})  # users blocked from each permission
    for k in ("mute", "ban", "safika", "staff", "regri", "xp"):
        bl.setdefault(k, [])
    d.setdefault("xp_roles", [])       # roles allowed to use /xp (empty = everyone)
    d.setdefault("xp_channels", [])    # channels where /xp works (empty = everywhere)
    d.setdefault("love_channels", [])  # channels where ship/kiss/hug/pat work (empty = everywhere)
    d.setdefault("love_texts", {})     # custom status texts: {"9": "...", "self": "..."} (empty = defaults)
    return d


def blacklist_list(gid, key):
    """Blacklisted user ids for a permission. Color uses the same list as /regri (restricted)."""
    c = cfg(gid)
    if key == "color":
        return c["restricted"]
    return c["perm_blacklist"].setdefault(key, [])


def is_blacklisted(member, key):
    """Blacklist beats roles/administrator. Only the server owner is exempt."""
    try:
        if member.id == member.guild.owner_id:
            return False
        return member.id in blacklist_list(member.guild.id, key)
    except Exception:
        return False


def has_cmd_access(member, key):
    """Owner + Administrator + roles chosen with /rolemute /roleban /rolesafika"""
    try:
        if member.id in (BOT_OWNER_ID, member.guild.owner_id):
            return True
        if is_blacklisted(member, key):
            return False
        if member.guild_permissions.administrator:
            return True
        allowed = cfg(member.guild.id)["perm_roles"].get(key, [])
        return any(r.id in allowed for r in member.roles)
    except Exception:
        return False


def is_dev(member):
    """Owner + roles chosen with /setdev (NOT every administrator)"""
    try:
        if member.id in (BOT_OWNER_ID, member.guild.owner_id):
            return True
        dev = cfg(member.guild.id)["dev_roles"]
        return any(r.id in dev for r in member.roles)
    except Exception:
        return False


def has_staff_access(member):
    """Owner + developer roles + roles chosen with /rolestaff"""
    try:
        if is_blacklisted(member, "staff"):
            return False
        if is_dev(member):
            return True
        allowed = cfg(member.guild.id)["perm_roles"].get("staff", [])
        return any(r.id in allowed for r in member.roles)
    except Exception:
        return False


def has_color_access(member):
    """Owner + developer roles + roles/users chosen with /regadan-ranggorin"""
    try:
        if is_blacklisted(member, "color"):
            return False
        if is_dev(member):
            return True
        c = cfg(member.guild.id)
        if member.id in c["color_users"]:
            return True
        return any(r.id in c["color_roles"] for r in member.roles)
    except Exception:
        return False


def get_mute_role(guild):
    """Role chosen with /setmuterole, otherwise a role named Muted"""
    rid = cfg(guild.id).get("mute_role")
    if rid:
        role = guild.get_role(rid)
        if role:
            return role
    return discord.utils.get(guild.roles, name="Muted")


def is_mute_role(role):
    try:
        rid = cfg(role.guild.id).get("mute_role")
        return role.name == "Muted" or (rid is not None and role.id == rid)
    except Exception:
        return role.name == "Muted"


def block_reason(guild, target, perm, role=None):
    """Explains exactly why Discord will refuse the action (or None if OK)."""
    me = guild.me
    if target.id == guild.owner_id:
        return "❌ خاوەنی سێرڤەر Ban/Mute ناکرێت (Discord ڕێگە نادات)."
    gp = me.guild_permissions
    if not (gp.administrator or getattr(gp, perm, False)):
        return f"❌ بۆتەکە مۆڵەتی `{perm}` ی نییە."
    if target.top_role >= me.top_role:
        return (
            f"❌ ڕۆڵی بۆتەکە (**{me.top_role.name}**) لە خوار یان یەکسانە لەگەڵ بەرزترین ڕۆڵی "
            f"**{target.display_name}** (**{target.top_role.name}**). "
            f"Discord ئەدمینی بۆتیش ڕێگە نادات. لە Server Settings ← Roles "
            f"ڕۆڵی **{me.top_role.name}** ڕابکێشە سەروو ڕۆڵی **{target.top_role.name}**."
        )
    if role is not None and role >= me.top_role:
        return (
            f"❌ ڕۆڵی Mute (**{role.name}**) لە سەروو یان یەکسانە لەگەڵ ڕۆڵی بۆتەکە (**{me.top_role.name}**). "
            f"ڕۆڵی بۆتەکە بەرزتر بکەرەوە لە Roles."
        )
    return None


def hierarchy_error(author, target):
    """Returns an error text if author may not act on target, else None."""
    guild = author.guild
    if target.id == author.id:
        return "❌ ناتوانیت ئەمە لەسەر خۆت بکەیت."
    if target.id == guild.owner_id:
        return "❌ ناتوانیت ئەمە لەسەر خاوەنی سێرڤەر بکەیت."
    if author.id in (BOT_OWNER_ID, guild.owner_id) or author.guild_permissions.administrator:
        return None
    if target.top_role >= author.top_role:
        return "❌ ناتوانیت ئەمە لەسەر کەسێک بکەیت کە ڕۆڵەکەی بەرزترە یان یەکسانە لەگەڵ ڕۆڵی تۆ."
    return None


# ---- "No permission" replies (stay 10 seconds, then disappear) ----

async def deny_interaction(interaction):
    """Slash command used without permission."""
    try:
        await interaction.response.send_message(NO_PERM_TEXT, delete_after=10)
    except Exception:
        pass


async def deny_message(message):
    """Text command (mute / safika / bfra ...) used without permission."""
    try:
        await message.channel.send(f"{message.author.mention} {NO_PERM_TEXT}", delete_after=10)
    except Exception:
        pass


def looks_like_command(message, parts, command):
    """True only when the message really looks like a command attempt,
    so normal chat that merely contains the word 'mute' does not get an error."""
    first = parts[0].lower()
    if first == command or (command == "safika" and first.startswith("safika")):
        return True
    return bool(message.mentions or message.reference)


# ---- Bans done by the bot's own commands (so the log shows the real moderator) ----
_recent_cmd_bans = {}   # (kind, user_id) -> (time, moderator mention)


def mark_cmd_ban(kind, user_id, by_mention):
    _recent_cmd_bans[(kind, user_id)] = (time.time(), by_mention)


def cmd_ban_by(kind, user_id):
    item = _recent_cmd_bans.get((kind, user_id))
    if item and time.time() - item[0] < 30:
        return item[1]
    return None


# ---- Role edits done by the bot's own commands (so the log shows the real person) ----
_recent_cmd_role_edits = {}   # role_id -> (time, user mention)


def mark_cmd_role_edit(role_id, by_mention):
    _recent_cmd_role_edits[role_id] = (time.time(), by_mention)


def cmd_role_edit_by(role_id):
    item = _recent_cmd_role_edits.get(role_id)
    if item and time.time() - item[0] < 30:
        return item[1]
    return None


# ---- Roles given by the bot's own commands (/staff, autorole) ----
_recent_cmd_role_gives = {}   # member_id -> (time, giver mention, via text)


def mark_cmd_role_give(member_id, by_mention, via):
    _recent_cmd_role_gives[member_id] = (time.time(), by_mention, via)


def cmd_role_give_by(member_id):
    """Returns (giver mention, via text) once, if a bot command just gave roles to this member."""
    item = _recent_cmd_role_gives.pop(member_id, None)
    if item and time.time() - item[0] < 30:
        return item[1], item[2]
    return None


# =========================================================
# 3. LOG HELPERS
# =========================================================

async def send_log(guild, key, embed):
    try:
        if guild is None:
            return
        channel_id = cfg(guild.id)["channels"].get(key)
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        await channel.send(embed=embed)
    except Exception:
        pass


def make_embed(title, description, color=discord.Color.blurple()):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.set_footer(text="Server Logs")
    return embed


def add_user_thumbnail(embed, user):
    try:
        embed.set_thumbnail(url=user.display_avatar.url)
    except Exception:
        pass


# =========================================================
# 4. AUDIT LOG HELPER
# =========================================================

async def get_audit_executor(guild, action, target_id=None, delay=1.0):
    try:
        await asyncio.sleep(delay)
        async for entry in guild.audit_logs(limit=10, action=action):
            if target_id is not None:
                if entry.target is None or getattr(entry.target, "id", None) != target_id:
                    continue
            if entry.created_at:
                now = datetime.datetime.now(datetime.timezone.utc)
                if (now - entry.created_at).total_seconds() > 15:
                    continue
            return entry
    except Exception:
        pass
    return None


def who(entry, default="Unknown"):
    return entry.user.mention if entry and entry.user else default


# ---- Mute / Unmute log (shown in the Ban Log channel, with Ban / Timeout) ----
_recent_cmd_mutes = {}   # user_id -> time of a mute/unmute done by the bot's own commands


def mark_cmd_mute(user_id):
    """The bot's own mute/unmute commands log themselves (with the real moderator),
    so on_member_update must not log the same role change a second time."""
    _recent_cmd_mutes[user_id] = time.time()


async def log_mute_event(guild, target, by, muted, channel=None, via=None):
    lines = [
        f"**Member:** {target.mention}",
        f"**{'Muted' if muted else 'Unmuted'} By:** {by}",
    ]
    if channel is not None:
        lines.append(f"**Channel:** {channel.mention}")
    if via:
        lines.append(f"**Via:** {via}")

    embed = make_embed(
        "🔇 Member Muted" if muted else "🔈 Member Unmuted",
        "\n".join(lines),
        discord.Color.red() if muted else discord.Color.green()
    )
    add_user_thumbnail(embed, target)
    await send_log(guild, "ban", embed)


# =========================================================
# 5. READY
# =========================================================

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands", flush=True)
    except Exception as e:
        print(f"❌ Slash sync error: {e}", flush=True)

    for guild in bot.guilds:
        try:
            mute_role = get_mute_role(guild)
            if mute_role:
                await sync_muted_permissions(guild, mute_role)
        except Exception:
            pass

    print(f"بۆتەکە بە سەرکەوتوویی چالاک بوو وەک: {bot.user}", flush=True)
    print(f"Config file: {CONFIG_FILE}", flush=True)


# =========================================================
# 6. WELCOME + AUTOROLE
# =========================================================

@bot.event
async def on_member_join(member):
    c = cfg(member.guild.id)

    # ---- Autorole ----
    auto_roles = [r for r in (member.guild.get_role(x) for x in c["autoroles"]) if r]
    if auto_roles:
        try:
            mark_cmd_role_give(member.id, member.guild.me.mention, "Autorole")
            await member.add_roles(*auto_roles, reason="Autorole")
        except Exception as e:
            print(f"autorole error: {e}")

    for cid in list(get_welcome_channels(member.guild.id)):
        channel = member.guild.get_channel(cid)
        if channel is None:
            continue
        try:
            await channel.send(embed=build_welcome_embed(member))
        except Exception:
            pass

    embed = make_embed(
        "📥 Member Joined",
        f"**Member:** {member.mention}\n"
        f"**Username:** `{member}`\n"
        f"**ID:** `{member.id}`",
        discord.Color.green()
    )
    add_user_thumbnail(embed, member)
    await send_log(member.guild, "member", embed)


# =========================================================
# 7. MEMBER LEFT
# =========================================================

@bot.event
async def on_member_remove(member):
    embed = make_embed(
        "📤 Member Left",
        f"Member: {member.mention}\nUsername: {member}\nID: {member.id}",
        discord.Color.red()
    )
    add_user_thumbnail(embed, member)
    await send_log(member.guild, "left", embed)


# =========================================================
# 8. MEMBER UPDATE
# =========================================================

@bot.event
async def on_member_update(before, after):
    guild = after.guild

    if before.nick != after.nick:
        old_nick = before.nick if before.nick else before.name
        new_nick = after.nick if after.nick else after.name

        entry = await get_audit_executor(guild, discord.AuditLogAction.member_update, after.id)
        editor = who(entry, "Unknown / Self")

        embed = make_embed(
            "✏️ Nickname Changed",
            f"**Member:** {after.mention}\n"
            f"**Changed By:** {editor}\n"
            f"**Before:** `{old_nick}`\n"
            f"**After:** `{new_nick}`",
            discord.Color.gold()
        )
        add_user_thumbnail(embed, after)
        await send_log(guild, "nickname", embed)

    # ---- Discord Timeout (shown in the Ban Log channel) ----
    if before.timed_out_until != after.timed_out_until:
        entry = await get_audit_executor(guild, discord.AuditLogAction.member_update, after.id)
        by = who(entry)
        reason_line = f"\n**Reason:** {entry.reason}" if entry and entry.reason else ""

        if after.timed_out_until:
            ts = int(after.timed_out_until.timestamp())
            embed = make_embed(
                "⏳ Member Timed Out",
                f"**Member:** {after.mention}\n"
                f"**Timed Out By:** {by}\n"
                f"**Until:** <t:{ts}:F> (<t:{ts}:R>){reason_line}",
                discord.Color.orange()
            )
        else:
            embed = make_embed(
                "✅ Timeout Removed",
                f"**Member:** {after.mention}\n"
                f"**Removed By:** {by}{reason_line}",
                discord.Color.green()
            )
        add_user_thumbnail(embed, after)
        await send_log(guild, "ban", embed)

    # ---- Mute role given / removed by hand (not by the bot's own command) ----
    mute_role_obj = get_mute_role(guild)
    if mute_role_obj and (mute_role_obj in before.roles) != (mute_role_obj in after.roles):
        if time.time() - _recent_cmd_mutes.get(after.id, 0) > 10:
            entry = await get_audit_executor(guild, discord.AuditLogAction.member_role_update, after.id)
            await log_mute_event(
                guild, after, who(entry), mute_role_obj in after.roles, via="Role changed by hand"
            )

    added_roles = set(after.roles) - set(before.roles)
    removed_roles = set(before.roles) - set(after.roles)

    real_added = [r for r in added_roles if r.name != "@everyone" and not is_mute_role(r)]
    if real_added:
        cmd = cmd_role_give_by(after.id)
        if cmd:
            given_by, via_text = cmd
        else:
            entry = await get_audit_executor(guild, discord.AuditLogAction.member_role_update, after.id)
            given_by, via_text = who(entry), ""
        roles_text = "\n".join(f"➕ {r.mention}" for r in real_added)
        via_line = f"\n\n**Via:** {via_text}" if via_text else ""
        embed = make_embed(
            "➕ Role Added",
            f"**Member:** {after.mention}\n"
            f"**Given By:** {given_by}\n\n{roles_text}{via_line}",
            discord.Color.green()
        )
        add_user_thumbnail(embed, after)
        await send_log(guild, "member", embed)

    real_removed = [r for r in removed_roles if r.name != "@everyone" and not is_mute_role(r)]
    if real_removed:
        entry = await get_audit_executor(guild, discord.AuditLogAction.member_role_update, after.id)
        roles_text = "\n".join(f"➖ {r.mention}" for r in real_removed)
        embed = make_embed(
            "➖ Role Removed",
            f"**Member:** {after.mention}\n"
            f"**Removed By:** {who(entry)}\n\n{roles_text}",
            discord.Color.red()
        )
        add_user_thumbnail(embed, after)
        await send_log(guild, "member", embed)


# =========================================================
# 9. GET TARGET MEMBER FROM TAG OR REPLY
# =========================================================

async def get_target_member(message):
    if message.mentions:
        for member in message.mentions:
            if member.id != bot.user.id and isinstance(member, discord.Member):
                return member

    if message.reference:
        try:
            ref = message.reference.resolved
            if not isinstance(ref, discord.Message):
                ref = await message.channel.fetch_message(message.reference.message_id)
            if ref.author.id == bot.user.id:
                return None
            if isinstance(ref.author, discord.Member):
                return ref.author
            return message.guild.get_member(ref.author.id)
        except Exception:
            pass

    return None


# =========================================================
# 10. MUTED ROLE
# =========================================================

async def apply_muted_permissions(channel, mute_role):
    try:
        if isinstance(channel, (discord.TextChannel, discord.NewsChannel, discord.ForumChannel)):
            await channel.set_permissions(
                mute_role,
                send_messages=False,
                add_reactions=False,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
                reason="Muted role - block chat"
            )
    except Exception:
        pass


async def sync_muted_permissions(guild, mute_role):
    for channel in guild.channels:
        await apply_muted_permissions(channel, mute_role)


async def get_or_create_muted_role(guild):
    mute_role = get_mute_role(guild)
    if not mute_role:
        mute_role = await guild.create_role(name="Muted", reason="Mute role")
    await sync_muted_permissions(guild, mute_role)
    return mute_role


# =========================================================
# 11. CHANNEL CREATE / DELETE / UPDATE LOG
# =========================================================

@bot.event
async def on_guild_channel_create(channel):
    try:
        mute_role = get_mute_role(channel.guild)
        if mute_role:
            await apply_muted_permissions(channel, mute_role)

        entry = await get_audit_executor(channel.guild, discord.AuditLogAction.channel_create, channel.id)

        embed = make_embed(
            "📁 Channel Created",
            f"**Channel:** {channel.mention}\n"
            f"**Name:** `{channel.name}`\n"
            f"**ID:** `{channel.id}`\n"
            f"**Type:** `{channel.type}`\n"
            f"**Created By:** {who(entry)}",
            discord.Color.green()
        )
        await send_log(channel.guild, "channel", embed)
    except Exception:
        pass


@bot.event
async def on_guild_channel_delete(channel):
    entry = await get_audit_executor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)

    embed = make_embed(
        "🗑️ Channel Deleted",
        f"**Channel:** `#{channel.name}`\n"
        f"**ID:** `{channel.id}`\n"
        f"**Type:** `{channel.type}`\n"
        f"**Deleted By:** {who(entry)}",
        discord.Color.red()
    )
    await send_log(channel.guild, "channel", embed)


@bot.event
async def on_guild_channel_update(before, after):
    if before.category != after.category:
        try:
            mute_role = get_mute_role(after.guild)
            if mute_role:
                await apply_muted_permissions(after, mute_role)
        except Exception:
            pass

    changes = []

    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")

    if before.category != after.category:
        old_c = before.category.name if before.category else "None"
        new_c = after.category.name if after.category else "None"
        changes.append(f"**Category:** `{old_c}` → `{new_c}`")

    if before.position != after.position:
        changes.append(f"**Position:** `{before.position}` → `{after.position}`")

    if changes:
        entry = await get_audit_executor(after.guild, discord.AuditLogAction.channel_update, after.id)
        embed = make_embed(
            "✏ Channel Updated",
            f"**Channel:** {after.mention}\n"
            f"**ID:** `{after.id}`\n"
            f"**Updated By:** {who(entry)}\n\n"
            + "\n".join(changes),
            discord.Color.gold()
        )
        await send_log(after.guild, "channel", embed)


# =========================================================
# 15. ROLE CREATE / DELETE / UPDATE
# =========================================================

@bot.event
async def on_guild_role_create(role):
    if is_mute_role(role):
        return

    entry = await get_audit_executor(role.guild, discord.AuditLogAction.role_create, role.id)
    embed = make_embed(
        "➕ Role Created",
        f"**Role:** {role.mention}\n"
        f"**Name:** `{role.name}`\n"
        f"**ID:** `{role.id}`\n"
        f"**Created By:** {who(entry)}",
        discord.Color.green()
    )
    await send_log(role.guild, "role", embed)


@bot.event
async def on_guild_role_delete(role):
    if is_mute_role(role):
        return

    entry = await get_audit_executor(role.guild, discord.AuditLogAction.role_delete, role.id)
    embed = make_embed(
        "🗑️ Role Deleted",
        f"**Role:** `{role.name}`\n"
        f"**ID:** `{role.id}`\n"
        f"**Deleted By:** {who(entry)}",
        discord.Color.red()
    )
    await send_log(role.guild, "role", embed)


@bot.event
async def on_guild_role_update(before, after):
    if is_mute_role(after):
        return

    changes = []

    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if before.color != after.color:
        changes.append(f"**Color:** `{before.color}` → `{after.color}`")
    if before.position != after.position:
        changes.append(f"**Position:** `{before.position}` → `{after.position}`")

    if changes:
        cmd_by = cmd_role_edit_by(after.id)
        if cmd_by:
            updated_by = cmd_by
            via_line = "**Via:** Bot command (/rangi-role)\n"
        else:
            entry = await get_audit_executor(after.guild, discord.AuditLogAction.role_update, after.id)
            updated_by = who(entry)
            via_line = ""
        embed = make_embed(
            "✏️ Role Updated",
            f"**Role:** {after.mention}\n"
            f"**ID:** `{after.id}`\n"
            f"**Updated By:** {updated_by}\n"
            f"{via_line}\n"
            + "\n".join(changes),
            discord.Color.gold()
        )
        await send_log(after.guild, "role", embed)


# =========================================================
# 18. VOICE LOG
# =========================================================

@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    # ---- Server Mute / Server Deafen (کەسێکی تر میوت یان دیفێنی کرد) ----
    if before.mute != after.mute or before.deaf != after.deaf:
        entry = await get_audit_executor(guild, discord.AuditLogAction.member_update, member.id)
        by = who(entry)
        ch = after.channel or before.channel
        ch_text = ch.mention if ch else "`—`"

        if before.mute != after.mute:
            if after.mute:
                embed = make_embed(
                    "🔇 Voice Muted",
                    f"**Member:** {member.mention}\n"
                    f"**Muted By:** {by}\n"
                    f"**Channel:** {ch_text}",
                    discord.Color.red()
                )
            else:
                embed = make_embed(
                    "🔈 Voice Unmuted",
                    f"**Member:** {member.mention}\n"
                    f"**Unmuted By:** {by}\n"
                    f"**Channel:** {ch_text}",
                    discord.Color.green()
                )
            add_user_thumbnail(embed, member)
            await send_log(guild, "voice", embed)

        if before.deaf != after.deaf:
            if after.deaf:
                embed = make_embed(
                    "🙉 Voice Deafened",
                    f"**Member:** {member.mention}\n"
                    f"**Deafened By:** {by}\n"
                    f"**Channel:** {ch_text}",
                    discord.Color.red()
                )
            else:
                embed = make_embed(
                    "👂 Voice Undeafened",
                    f"**Member:** {member.mention}\n"
                    f"**Undeafened By:** {by}\n"
                    f"**Channel:** {ch_text}",
                    discord.Color.green()
                )
            add_user_thumbnail(embed, member)
            await send_log(guild, "voice", embed)

    # ---- Join / Leave / Move ----
    if before.channel is None and after.channel is not None:
        embed = make_embed(
            "🔊 Voice Join",
            f"**Member:** {member.mention}\n**Channel:** {after.channel.mention}",
            discord.Color.green()
        )
    elif before.channel is not None and after.channel is None:
        kicked_by = await find_voice_disconnector(guild)
        if kicked_by:
            embed = make_embed(
                "⛔ Voice Disconnected",
                f"**Member:** {member.mention}\n"
                f"**Disconnected By:** {kicked_by.mention}\n"
                f"**Channel:** `{before.channel.name}`",
                discord.Color.orange()
            )
        else:
            embed = make_embed(
                "🔇 Voice Leave",
                f"**Member:** {member.mention}\n**Channel:** `{before.channel.name}`",
                discord.Color.red()
            )
    elif (
        before.channel is not None
        and after.channel is not None
        and before.channel.id != after.channel.id
    ):
        mover = await find_voice_mover(guild, after.channel.id)
        by_line = f"**Moved By:** {mover.mention}\n" if mover else ""
        embed = make_embed(
            "🔀 Voice Move",
            f"**Member:** {member.mention}\n"
            f"{by_line}"
            f"**From:** `{before.channel.name}`\n"
            f"**To:** `{after.channel.name}`",
            discord.Color.gold()
        )
    else:
        return

    add_user_thumbnail(embed, member)
    await send_log(guild, "voice", embed)


# =========================================================
# 19 & 20. BAN / UNBAN LOG
# =========================================================

@bot.event
async def on_member_ban(guild, user):
    # ئەگەر بە کۆماندی Bfra بوو، ناوی ئەو کەسە دەنووسرێت کە نووسیویەتی (نەک بۆتەکە)
    by = cmd_ban_by("ban", user.id)
    if not by:
        entry = await get_audit_executor(guild, discord.AuditLogAction.ban, user.id)
        by = who(entry)

    embed = make_embed(
        "🔨 Member Banned",
        f"**Member:** {user.mention}\n**Banned By:** {by}",
        discord.Color.red()
    )
    add_user_thumbnail(embed, user)
    await send_log(guild, "ban", embed)


@bot.event
async def on_member_unban(guild, user):
    by = cmd_ban_by("unban", user.id)
    if not by:
        entry = await get_audit_executor(guild, discord.AuditLogAction.unban, user.id)
        by = who(entry)

    embed = make_embed(
        "♻ Member Unbanned",
        f"**Member:** {user.mention}\n**Unbanned By:** {by}",
        discord.Color.green()
    )
    add_user_thumbnail(embed, user)
    await send_log(guild, "ban", embed)


# =========================================================
# 21. SERVER UPDATE
# =========================================================

@bot.event
async def on_guild_update(before, after):
    changes = []

    if before.name != after.name:
        changes.append(f"**Server Name:** `{before.name}` → `{after.name}`")

    if changes:
        entry = await get_audit_executor(after, discord.AuditLogAction.guild_update)
        embed = make_embed(
            "⚙ Server Updated",
            f"**Updated By:** {who(entry)}\n\n" + "\n".join(changes),
            discord.Color.gold()
        )
        if after.icon:
            embed.set_thumbnail(url=after.icon.url)
        await send_log(after, "server", embed)


# =========================================================
# 22 & 23. MESSAGE DELETE / EDIT
# =========================================================

@bot.event
async def on_message_delete(message):
    if message.author.bot or message.guild is None:
        return

    content = message.content[:1500] if message.content else "*No text content*"

    embed = make_embed(
        "🗑️ Message Deleted",
        f"**Author:** {message.author.mention}\n"
        f"**Channel:** {message.channel.mention}\n\n"
        f"**Message:**\n```text\n{content}\n```",
        discord.Color.red()
    )
    add_user_thumbnail(embed, message.author)
    await send_log(message.guild, "chat", embed)


@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.guild is None or before.content == after.content:
        return

    old_content = before.content[:700] if before.content else "*Empty*"
    new_content = after.content[:700] if after.content else "*Empty*"

    embed = make_embed(
        "✏️ Message Edited",
        f"**Author:** {after.author.mention}\n"
        f"**Before:**\n```text\n{old_content}\n```\n"
        f"**After:**\n```text\n{new_content}\n```",
        discord.Color.gold()
    )
    add_user_thumbnail(embed, after.author)
    await send_log(after.guild, "chat", embed)


# =========================================================
# 24. MAIN COMMAND SYSTEM (no prefix)
# =========================================================

COMMAND_WORDS = ["safika", "mute", "unmute", "bfra", "unban", "lock", "unlock"]


def parse_safika_amount(parts):
    """Safika 1 / safika10 / safika ٥ / هەر شێوازێک"""
    for p in parts:
        pl = p.lower().strip()
        if pl.startswith("safika") and pl[6:].isdigit():
            return int(pl[6:])
    for p in parts:
        if p.strip().isdigit():
            return int(p.strip())
    return None


@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    mute_role = get_mute_role(message.guild)

    if (
        mute_role
        and mute_role in message.author.roles
        and message.author.id != BOT_OWNER_ID
        and not message.author.guild_permissions.administrator
    ):
        try:
            await message.delete()
        except Exception:
            pass
        return

    content = message.content.strip()
    if not content:
        return

    if content.startswith("!!"):   # TTS (ElevenLabs) - هیچ کۆمانێک لێرە کار ناکات
        return

    parts = content.split()
    command = ""

    for part in parts:
        clean_part = part.lower().strip()
        if clean_part in COMMAND_WORDS:
            command = clean_part
            break
        if clean_part.startswith("safika") and clean_part[6:].isdigit():
            command = "safika"
            break

    if not command and parts:
        command = parts[0].lower()

    # ---------------- SAFIKA ----------------
    # (ئەمە تەنها کۆماندێکە کە نامەکان دەسڕێتەوە - چونکە کارەکەی ئەوەیە)
    if command == "safika":
        if not has_cmd_access(message.author, "safika"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        amount = parse_safika_amount(parts)

        if amount is None or amount < 1:
            await message.channel.send("❌ وەک: `safika 10`", delete_after=5)
            return

        amount = min(amount, 1000)

        try:
            deleted = await message.channel.purge(limit=amount + 1)
            await message.channel.send(
                f"✅ `{max(len(deleted) - 1, 0)}` نامە سڕایەوە.", delete_after=3
            )
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە مۆڵەتی Manage Messages / Read Message History ی نییە.",
                delete_after=8
            )
        except Exception as e:
            print(f"safika error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- MUTE ----------------
    if command == "mute":
        if not has_cmd_access(message.author, "mute"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        target = await get_target_member(message)
        if not target:
            await message.channel.send(
                "❌ کەسەکە تاگ بکە یان ڕیپلەی بکە: `mute @user`", delete_after=5
            )
            return

        err = hierarchy_error(message.author, target)
        if err:
            await message.channel.send(err, delete_after=5)
            return

        try:
            muted_role = await get_or_create_muted_role(message.guild)
            reason = block_reason(message.guild, target, "manage_roles", muted_role)
            if reason:
                await message.channel.send(reason, delete_after=15)
                return
            if muted_role not in target.roles:
                mark_cmd_mute(target.id)
                await target.add_roles(muted_role, reason=f"Muted by {message.author}")
                await log_mute_event(
                    message.guild, target, message.author.mention, True,
                    channel=message.channel, via="Bot command"
                )
            # نامەی تۆ و نامەی بۆتەکە هەردووکیان دەمێننەوە (هیچ دیلیتێک نییە)
            await message.channel.send(f"damt daxaa {target.mention}")
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە مۆڵەتی Manage Roles ی نییە، یان ڕۆڵی بۆتەکە لە **Roles** دا لە خوار ڕۆڵی Muted یان ئەو کەسەیە. ڕۆڵی بۆتەکە بەرز بکەرەوە.",
                delete_after=10
            )
        except Exception as e:
            print(f"mute error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- UNMUTE ----------------
    if command == "unmute":
        if not has_cmd_access(message.author, "mute"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        target = await get_target_member(message)
        if not target:
            await message.channel.send(
                "❌ کەسەکە تاگ بکە یان ڕیپلەی بکە: `unmute @user`", delete_after=5
            )
            return

        try:
            muted_role = get_mute_role(message.guild)
            if muted_role and muted_role in target.roles:
                mark_cmd_mute(target.id)
                await target.remove_roles(muted_role)
                await log_mute_event(
                    message.guild, target, message.author.mention, False,
                    channel=message.channel, via="Bot command"
                )
            # نامەی تۆ و نامەی بۆتەکە هەردووکیان دەمێننەوە (هیچ دیلیتێک نییە)
            await message.channel.send(
                f"xwa xerm bnwse dllm basha aqllba amjara {target.mention}"
            )
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە مۆڵەتی Manage Roles ی نییە، یان ڕۆڵەکەی لە خوار ڕۆڵی Muted ە.",
                delete_after=10
            )
        except Exception as e:
            print(f"unmute error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- BFRA ----------------
    if command == "bfra":
        if not has_cmd_access(message.author, "ban"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        target = await get_target_member(message)
        if not target:
            await message.channel.send(
                "❌ کەسەکە تاگ بکە یان ڕیپلەی بکە: `bfra @user`", delete_after=5
            )
            return

        err = hierarchy_error(message.author, target)
        if err:
            await message.channel.send(err, delete_after=5)
            return

        try:
            reason = block_reason(message.guild, target, "ban_members")
            if reason:
                await message.channel.send(reason, delete_after=15)
                return
            # ناوی ئەو کەسە لە لۆگ دەنووسرێت کە Bfra ی نووسیوە
            mark_cmd_ban("ban", target.id, message.author.mention)
            # چاتی کەسە باندکراوەکە ناسڕدرێتەوە
            await target.ban(reason=f"Banned by {message.author}", delete_message_seconds=0)
            # نامەی تۆ و نامەی بۆتەکە هەردووکیان دەمێننەوە (هیچ دیلیتێک نییە)
            await message.channel.send(f"Frenraa✈️ {target.mention}")
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە مۆڵەتی Ban Members ی نییە، یان ڕۆڵی بۆتەکە لە خوار ڕۆڵی ئەو کەسەیە. ڕۆڵی بۆتەکە بەرز بکەرەوە.",
                delete_after=10
            )
        except Exception as e:
            print(f"bfra error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- UNBAN ----------------
    if command == "unban":
        if not has_cmd_access(message.author, "ban"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        user_id = None
        for p in parts:
            if p.strip().isdigit() and len(p.strip()) >= 15:
                user_id = int(p.strip())
                break

        if user_id is None:
            await message.channel.send("❌ وەک: `unban 123456789012345678`", delete_after=5)
            return

        try:
            user = await bot.fetch_user(user_id)
            mark_cmd_ban("unban", user_id, message.author.mention)
            await message.guild.unban(user)
            # نامەی تۆ و نامەی بۆتەکە هەردووکیان دەمێننەوە (هیچ دیلیتێک نییە)
            await message.channel.send("✅ Unban کرا.")
        except discord.NotFound:
            await message.channel.send("❌ ئەم کەسە لە لیستی Ban دا نییە.", delete_after=5)
        except discord.Forbidden:
            await message.channel.send("❌ بۆتەکە مۆڵەتی Ban Members ی نییە.", delete_after=8)
        except Exception as e:
            print(f"unban error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- LOCK ----------------
    if command == "lock":
        if message.author.id != BOT_OWNER_ID and not message.author.guild_permissions.manage_channels:
            return
        try:
            await message.channel.set_permissions(message.guild.default_role, send_messages=False)
            await message.channel.send("🔒 کەناڵەکە Lock کرا.")
        except Exception:
            pass
        return

    # ---------------- UNLOCK ----------------
    if command == "unlock":
        if message.author.id != BOT_OWNER_ID and not message.author.guild_permissions.manage_channels:
            return
        try:
            await message.channel.set_permissions(message.guild.default_role, send_messages=None)
            await message.channel.send("🔓 کەناڵەکە Unlock کرا.")
        except Exception:
            pass
        return


# =========================================================
# 25. SETUP SLASH COMMANDS (per server)
# =========================================================

@bot.tree.command(name="setlog", description="دیاریکردنی کەناڵی لۆگەکان")
@app_commands.guild_only()
@app_commands.describe(type="جۆری لۆگ", channel="کەناڵ")
@app_commands.choices(
    type=[app_commands.Choice(name=v, value=k) for k, v in LOG_TYPES.items() if k != "welcome"]
)
async def setlog(
    interaction: discord.Interaction,
    type: str,
    channel: discord.TextChannel
):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    cfg(interaction.guild.id)["channels"][type] = channel.id
    save_config()

    await interaction.response.send_message(
        f"✅ **{LOG_TYPES[type]}** → {channel.mention}", ephemeral=True
    )


@bot.tree.command(name="setlogall", description="هەموو لۆگەکان بخە یەک کەناڵەوە")
@app_commands.guild_only()
@app_commands.describe(channel="کەناڵی هەموو لۆگەکان")
async def setlogall(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)
    for k in LOG_TYPES:
        if k != "welcome":
            c["channels"][k] = channel.id
    save_config()

    await interaction.response.send_message(
        f"✅ هەموو لۆگەکان → {channel.mention}", ephemeral=True
    )


# ---------------------------------------------------------
# /setlogcategory : هەموو لۆگەکان لە ناو کاتێگۆریەک بە ناوەکانیانەوە دەبەستێتەوە
# ---------------------------------------------------------
import unicodedata as _ud

# ڕیزبەندی گرنگە (nickname پێش member، چونکە nickname-changed نابێت بچێتە member)
LOG_NAME_HINTS = [
    ("nickname", ("nickname", "nick")),
    ("ban", ("ban", "mute")),
    ("left", ("left", "leave")),
    ("voice", ("voice",)),
    ("chat", ("chat", "message")),
    ("role", ("role",)),
    ("channel", ("channel",)),
    ("member", ("member",)),
    ("server", ("server",)),
]


def log_type_from_name(name):
    n = _ud.normalize("NFKC", name or "").casefold()
    for t, hints in LOG_NAME_HINTS:
        if any(h in n for h in hints):
            return t
    return None


def _cat_norm(text):
    return _ud.normalize("NFKC", text or "").casefold().strip()


async def _logcat_autocomplete(interaction: discord.Interaction, current: str):
    cur = _cat_norm(current)
    out = []
    for c in interaction.guild.categories:
        if not cur or cur in _cat_norm(c.name):
            out.append(app_commands.Choice(name=c.name[:100], value=c.name[:100]))
    return out[:25]


@bot.tree.command(name="setlogcategory",
                  description="هەموو لۆگەکان لە ناو کاتێگۆریەک بە ناوەکانیانەوە ببەستەوە")
@app_commands.guild_only()
@app_commands.describe(category="ناوی کاتێگۆری (هەڵیبژێرە یان ناوەکەی لێرە بنووسە / پەیستی بکە)")
@app_commands.autocomplete(category=_logcat_autocomplete)
async def setlogcategory(interaction: discord.Interaction, category: str):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    g = interaction.guild
    want = category.strip()
    cats = list(g.categories)
    found = [c for c in cats if c.name.strip() == want]
    if not found:
        found = [c for c in cats if _cat_norm(c.name) == _cat_norm(want)]
    if not found:
        found = [c for c in cats if _cat_norm(want) and _cat_norm(want) in _cat_norm(c.name)]
    if not found:
        await interaction.response.send_message("❌ هیچ کاتێگۆریەک بەم ناوە نەدۆزرایەوە.", ephemeral=True)
        return
    if len(found) > 1:
        names = "\n".join(f"• {c.name}" for c in found[:10])
        await interaction.response.send_message(
            f"❌ چەند کاتێگۆریەک بەم ناوە هەن، ناوەکە ورد بنووسە:\n{names}", ephemeral=True)
        return
    cat = found[0]

    assigned, unmatched = {}, []
    for ch in sorted(cat.channels, key=lambda c: c.position):
        if not isinstance(ch, discord.TextChannel):
            continue
        t = log_type_from_name(ch.name)
        if t is None or t in assigned:
            unmatched.append(ch)
        else:
            assigned[t] = ch
    if not assigned:
        await interaction.response.send_message(
            "❌ لە ناو ئەم کاتێگۆریەدا هیچ کەناڵێکی لۆگ نەدۆزرایەوە (ناوی کەناڵەکان وەک `server-log` ، `chat-log` ... بن).",
            ephemeral=True)
        return

    c = cfg(g.id)
    for t, ch in assigned.items():
        c["channels"][t] = ch.id
    save_config()

    lines = []
    for k, label in LOG_TYPES.items():
        if k == "welcome":
            continue
        lines.append(f"**{label}:** " + (assigned[k].mention if k in assigned else "❌ نەدۆزرایەوە"))
    desc = f"📁 **{cat.name}**\n\n" + "\n".join(lines)
    if unmatched:
        desc += "\n\n➖ ئەم کەناڵانە نەبەسترانەوە:\n" + " ".join(ch.mention for ch in unmatched[:15])
    await interaction.response.send_message(
        embed=discord.Embed(title="✅ لۆگەکان بەسترانەوە", description=desc[:4000],
                            color=discord.Color.green()),
        ephemeral=True)


# ---------------------------------------------------------
# /rolemute  /roleban  /rolesafika  /rolestaff
# ---------------------------------------------------------

async def update_perm_role(interaction, key, action, role):
    user = interaction.user
    if not is_dev(user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)
    lst = c["perm_roles"][key]

    if action == "add":
        if role.id not in lst:
            lst.append(role.id)
        msg = f"✅ {role.mention} ئێستا دەتوانێت **{PERM_LABELS[key]}** بەکاربهێنێت."
    elif action == "remove":
        if role.id in lst:
            lst.remove(role.id)
        msg = f"✅ {role.mention} لە **{PERM_LABELS[key]}** لابرا."
    else:
        msg = "❌ هەڵبژاردنێکی نادروستە."

    save_config()
    await interaction.response.send_message(
        msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )


PERM_ACTION_CHOICES = [
    app_commands.Choice(name="Add (زیادکردن)", value="add"),
    app_commands.Choice(name="Remove (لابردن)", value="remove"),
]


@bot.tree.command(name="setmuterole", description="دیاریکردنی ئەو ڕۆڵەی لە کاتی Mute دەدرێت بە کەسەکە")
@app_commands.guild_only()
@app_commands.describe(role="ڕۆڵی Mute (بۆ نموونە Muted)")
async def setmuterole(interaction: discord.Interaction, role: discord.Role):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    if role.is_default() or role.managed:
        await interaction.response.send_message(
            "❌ ئەم ڕۆڵە ناکرێت وەک ڕۆڵی Mute بەکاربێت.", ephemeral=True
        )
        return

    cfg(interaction.guild.id)["mute_role"] = role.id
    save_config()

    await interaction.response.defer(ephemeral=True)
    await sync_muted_permissions(interaction.guild, role)

    me = interaction.guild.me
    warn = ""
    if role >= me.top_role:
        warn = f"\n⚠ ڕۆڵی بۆتەکە (**{me.top_role.name}**) دەبێت لە سەروو ئەم ڕۆڵەوە بێت لە Roles."

    await interaction.followup.send(
        f"✅ ڕۆڵی Mute: **{role.name}** (ڕێگەپێدراوییەکانی هەموو کەناڵەکان ڕێکخرا).{warn}",
        ephemeral=True
    )


@bot.tree.command(name="autorole", description="ڕۆڵە خۆکارەکان بۆ ئەندامی نوێ (چەند ڕۆڵ)")
@app_commands.guild_only()
async def autorole_cmd(interaction: discord.Interaction):
    await open_perm_panel(interaction, "auto")


@bot.tree.command(name="config", description="پیشاندانی ڕێکخستنەکانی ئەم سێرڤەرە")
@app_commands.guild_only()
async def config_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)
    lines = []

    for k, name in LOG_TYPES.items():
        if k == "welcome":
            wl = " ".join(f"<#{x}>" for x in get_welcome_channels(interaction.guild.id)) or "❌"
            lines.append(f"**{name}:** {wl}")
            continue
        cid = c["channels"].get(k)
        lines.append(f"**{name}:** {f'<#{cid}>' if cid else '❌'}")

    for slot in ("staff1", "staff2"):
        sr = ", ".join(f"<@&{r}>" for r in get_staff_roles(interaction.guild.id, slot)) or "❌"
        lines.append(f"**{STAFF_LABELS[slot]}:** {sr}")

    regri_txt = ", ".join(f"<@&{r}>" for r in c["regri_roles"]) or "❌"
    lines.append(f"**Regri roles:** {regri_txt}")

    color_roles_txt = ", ".join(f"<@&{r}>" for r in c["color_roles"]) or "❌"
    color_users_txt = ", ".join(f"<@{u}>" for u in c["color_users"]) or "❌"
    lines.append(f"**Color roles:** {color_roles_txt}")
    lines.append(f"**Color users:** {color_users_txt}")

    dev = ", ".join(f"<@&{r}>" for r in c["dev_roles"]) or "❌ (تەنها Owner)"
    lines.append(f"**Developer roles:** {dev}")

    mrid = c.get("mute_role")
    lines.append(f"**Mute role:** {f'<@&{mrid}>' if mrid else '❌ (Muted بە ناو)'}")

    ar_txt = ", ".join(f"<@&{r}>" for r in c["autoroles"]) or "❌"
    lines.append(f"**Autoroles:** {ar_txt}")

    for k, label in PERM_LABELS.items():
        roles_txt = ", ".join(f"<@&{r}>" for r in c["perm_roles"][k]) or "❌"
        lines.append(f"**{label} roles:** {roles_txt}")

    await interaction.response.send_message(
        "\n".join(lines),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
    )


# =========================================================
# 26. STAFF
# =========================================================

@bot.tree.command(name="staff", description="پێدانی ڕۆڵی ستاف بە ئەندام")
@app_commands.guild_only()
@app_commands.choices(
    role_choice=[
        app_commands.Choice(name="Lady Staff", value="staff1"),
        app_commands.Choice(name="Boy Staff", value="staff2"),
    ]
)
async def staff(
    interaction: discord.Interaction,
    member: discord.Member,
    role_choice: str
):
    if not has_staff_access(interaction.user):
        await deny_interaction(interaction)
        return

    try:
        ids = get_staff_roles(interaction.guild.id, role_choice)
        roles = [r for r in (interaction.guild.get_role(x) for x in ids) if r]

        if not roles:
            await interaction.response.send_message(
                "❌ ڕۆڵەکە دیاری نەکراوە! سەرەتا /setstaff بەکاربهێنە.", ephemeral=True
            )
            return

        new_roles = [r for r in roles if r not in member.roles]
        if not new_roles:
            await interaction.response.send_message(
                f"⚠ {member.mention} پێشتر هەموو ئەم ڕۆڵانەی هەیە.", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            mark_cmd_role_give(member.id, interaction.user.mention, "Bot command (/staff)")
            await member.add_roles(*new_roles, reason=f"Staff given by {interaction.user}")
            names = ", ".join(f"**{r.name}**" for r in new_roles)
            await interaction.response.send_message(
                f"✅ ڕۆڵی {names} بە سەرکەوتوویی درا بە {member.mention}",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )

    except Exception as e:
        await interaction.response.send_message(f"❌ کێشەیەک ڕوویدا: {e}", ephemeral=True)


# =========================================================
# 27. COLOR ROLE SYSTEM
# =========================================================

def parse_hex_color(text):
    """'#FF0000' / 'ff0000' / '#f00' -> discord.Color, or None if invalid."""
    h = text.strip().lstrip("#")
    if len(h) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in h):
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6 or not all(ch in "0123456789abcdefABCDEF" for ch in h):
        return None
    return discord.Color(int(h, 16))


@bot.tree.command(name="rangi-role", description="گۆڕینی ڕەنگی ڕۆڵ")
@app_commands.guild_only()
@app_commands.describe(
    role="ڕۆڵەکە هەڵبژێرە",
    color="کۆدی ڕەنگ بۆ نموونە #FF0000"
)
async def rangi_role(interaction: discord.Interaction, role: discord.Role, color: str):
    if not has_color_access(interaction.user):
        await deny_interaction(interaction)
        return

    guild = interaction.guild

    if interaction.user.id in cfg(guild.id)["restricted"]:
        await interaction.response.send_message(
            "❌ تۆ قەدەغەکراوی لە گۆڕینی ڕەنگ!", ephemeral=True
        )
        return

    target_role = role

    user_top_role = interaction.user.top_role
    is_owner = interaction.user.id == guild.owner_id

    if (
        target_role.is_default()
        or target_role.managed
        or target_role.is_bot_managed()
    ):
        await interaction.response.send_message(
            "❌ ناتوانیت ڕەنگی ئەم ڕۆڵە بگۆڕیت!", ephemeral=True
        )
        return

    if not is_owner and target_role > user_top_role:
        await interaction.response.send_message(
            "❌ ناتوانیت ڕەنگی ئەم ڕۆڵە بگۆڕیت چونکە لەسەروو ڕۆڵەکەتدایە!",
            ephemeral=True
        )
        return

    me = guild.me
    if target_role >= me.top_role:
        await interaction.response.send_message(
            f"❌ ڕۆڵی بۆتەکە (**{me.top_role.name}**) دەبێت لە سەروو ڕۆڵی **{target_role.name}** بێت. "
            f"لە Server Settings ← Roles ڕۆڵی بۆتەکە بەرز بکەرەوە.",
            ephemeral=True
        )
        return

    color_obj = parse_hex_color(color)
    if color_obj is None:
        await interaction.response.send_message(
            "❌ کۆدی ڕەنگ هەڵەیە. نموونە: `#FF0000`", ephemeral=True
        )
        return

    try:
        mark_cmd_role_edit(target_role.id, interaction.user.mention)
        await target_role.edit(
            color=color_obj,
            reason=f"Color changed by {interaction.user}"
        )
        await interaction.response.send_message(
            f"✅ ڕەنگی ڕۆڵی **{target_role.name}** بە سەرکەوتوویی گۆڕدرا!",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ بۆتەکە مۆڵەتی **Manage Roles** ی نییە، یان ڕۆڵەکەی لە خوار ئەم ڕۆڵەیە.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ هەڵە ڕوویدا: {e}", ephemeral=True)


# =========================================================
# 28. REGRI
# =========================================================

@bot.tree.command(name="regri", description="قەدەغەکردن یان لابردنی قەدەغەی گۆڕینی ڕەنگ")
@app_commands.guild_only()
@app_commands.choices(
    action=[
        app_commands.Choice(name="Add (قەدەغەکردن)", value="add"),
        app_commands.Choice(name="Remove (ڕێگەپێدان)", value="remove"),
    ]
)
async def regri(interaction: discord.Interaction, member: discord.Member, action: str):
    c = cfg(interaction.guild.id)

    is_owner = interaction.user.id == interaction.guild.owner_id
    has_allowed_role = any(r.id in c["regri_roles"] for r in interaction.user.roles)

    if not is_owner and (not has_allowed_role or is_blacklisted(interaction.user, "regri")):
        await deny_interaction(interaction)
        return

    if action.lower() == "add":
        if member.id not in c["restricted"]:
            c["restricted"].append(member.id)
        save_config()
        await interaction.response.send_message(
            f"🚫 {member.mention} قەدەغەکرا لە گۆڕینی ڕەنگ.", ephemeral=True
        )
    else:
        if member.id in c["restricted"]:
            c["restricted"].remove(member.id)
        save_config()
        await interaction.response.send_message(
            f"✅ ڕێگەدرا بە {member.mention} بۆ گۆڕینی ڕەنگ.", ephemeral=True
        )


# =========================================================
# 29. SECURITY SYSTEM  (/security)
# =========================================================
# Anti-Spam / Anti-Mention / Anti-Invite / Anti-Link
# Anti-Nuke: Channel + Role create/delete/rename/permissions, Ban, Kick, Bot Add
# هەموو Limit و چرکە و ماوەی Timeout لە /security دەستکاری دەکرێن.

# key: (label, default_enabled, default_limit, default_seconds, default_timeout_min, hint)
SEC_MODULES = {
    "spam": ("Anti-Spam", True, 5, 5, 10,
             "Limit = چەند نامە ڕێگەپێدراوە لە Seconds چرکەدا. زیاتر بنێرێت = سزا + سڕینەوەی نامەکان"),
    "mention": ("Anti-Mention", True, 5, 0, 10,
                "Limit = زۆرترین تاگ لە یەک نامەدا (Seconds بەکارنایەت)"),
    "invite": ("Anti-Invite", True, 1, 60, 30,
               "Limit = چەند لینکی بانگهێشت ڕێگەپێدراوە لە Seconds چرکەدا"),
    "link": ("Anti-Link", False, 2, 30, 10,
             "Limit = چەند لینک ڕێگەپێدراوە لە Seconds چرکەدا"),
    "chan_create": ("Channel Create", True, 2, 60, 60, "چەند چەناڵ دروست بکرێت لە Seconds چرکەدا"),
    "chan_delete": ("Channel Delete", True, 2, 60, 60, "چەند چەناڵ بسڕدرێتەوە لە Seconds چرکەدا"),
    "chan_name": ("Channel Rename", True, 3, 60, 60, "چەند جار ناوی چەناڵ بگۆڕدرێت"),
    "chan_perm": ("Channel Permissions", True, 3, 60, 60, "چەند جار پێرمشنی چەناڵ بگۆڕدرێت"),
    "role_create": ("Role Create", True, 2, 60, 60, "چەند ڕۆڵ دروست بکرێت"),
    "role_delete": ("Role Delete", True, 2, 60, 60, "چەند ڕۆڵ بسڕدرێتەوە"),
    "role_name": ("Role Rename", True, 3, 60, 60, "چەند جار ناوی ڕۆڵ بگۆڕدرێت"),
    "role_perm": ("Role Permissions", True, 3, 60, 60, "چەند جار پێرمشنی ڕۆڵ بگۆڕدرێت"),
    "ban": ("Anti-Ban", True, 2, 60, 60, "چەند کەس Ban بکرێن"),
    "kick": ("Anti-Kick", True, 2, 60, 60, "چەند کەس Kick بکرێن"),
    "bot_add": ("Anti-Bot Add", True, 0, 60, 60, "Limit 0 = هەر بۆتێک زیاد بکرێت، بۆتەکە دەردەکرێت و زیادکەرەکە سزا دەدرێت"),
}

# تەنها ئەم بەشانە ڕۆڵەکان لادەبەن (دەتوانیت لە /security بۆ هەر بەشێک بیگۆڕیت)
SEC_ROLE_REMOVE_DEFAULT = {"chan_delete", "ban", "kick"}

SEC_PUNISH_ORDER = ["timeout", "kick", "ban", "none"]
SEC_PUNISH_LABELS = {"timeout": "Timeout", "kick": "Kick", "ban": "Ban", "none": "Warning only"}

SEC_INVITE_RX = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.I)
SEC_LINK_RX = re.compile(r"https?://\S+", re.I)

_sec_hits = defaultdict(deque)
_sec_details = defaultdict(list)
_sec_spam = defaultdict(deque)


def get_sec(gid):
    c = cfg(gid)
    s = c.setdefault("security", {})
    s.setdefault("enabled", True)
    s.setdefault("log_channel", None)     # warning channel (chosen in /security)
    s.setdefault("punish", "timeout")
    s.setdefault("remove_roles", True)
    s.setdefault("wl_users", [])
    s.setdefault("wl_roles", [])
    mods = s.setdefault("modules", {})
    for k, (_, en, lim, sec, tmo, _) in SEC_MODULES.items():
        m = mods.setdefault(k, {"enabled": en, "limit": lim, "seconds": sec, "timeout": tmo})
        m.setdefault("timeout", tmo)
        m.setdefault("remove_roles", k in SEC_ROLE_REMOVE_DEFAULT)
        m.setdefault("wl_users", [])
        m.setdefault("wl_roles", [])
        m.setdefault("wl_channels", [])
    return s


def sec_mod_on(guild, key):
    s = get_sec(guild.id)
    return s["enabled"] and s["modules"][key]["enabled"]


def sec_exempt(guild, user_id):
    """Bot itself, owner, developer roles (/setdev) and the whitelist are never punished."""
    if user_id == bot.user.id or user_id == guild.owner_id:
        return True
    s = get_sec(guild.id)
    if user_id in s["wl_users"]:
        return True
    m = guild.get_member(user_id)
    if m is None:
        return False
    if is_dev(m):
        return True
    return any(r.id in s["wl_roles"] for r in m.roles)


async def sec_audit(guild, actions, target_id):
    await asyncio.sleep(1.0)
    for action in actions:
        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                if getattr(entry.target, "id", None) != target_id:
                    continue
                age = (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds()
                if age > 15:
                    continue
                return entry
        except Exception:
            pass
    return None


def sec_executor_id(entry, ban_kind=None, target_id=None):
    uid = entry.user.id if entry and entry.user else None
    if uid == bot.user.id and ban_kind:
        by = cmd_ban_by(ban_kind, target_id)   # ban done with the bot's own "bfra" command
        if by:
            found = re.search(r"\d+", by)
            if found:
                return int(found.group())
    return uid


def sec_add_detail(gid, uid, text):
    lst = _sec_details[(gid, uid)]
    lst.append(text)
    del lst[:-10]


async def sec_send_warning(guild, embed):
    try:
        s = get_sec(guild.id)
        cid = s.get("log_channel") or cfg(guild.id)["channels"].get("server")
        ch = guild.get_channel(cid) if cid else None
        if ch:
            await ch.send(embed=embed)
    except Exception:
        pass


async def sec_punish(guild, uid, key, count):
    s = get_sec(guild.id)
    m = s["modules"][key]
    label = SEC_MODULES[key][0]
    results = []

    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except Exception:
            member = None

    if member is None:
        results.append("⚠ ئەندامەکە لە سێرڤەر نەماوە.")
    else:
        me = guild.me
        reason = f"Security: {label}"

        # ---- remove roles ----
        if m["remove_roles"]:
            roles = [r for r in member.roles
                     if not r.is_default() and not r.managed and r < me.top_role]
            if roles:
                try:
                    await member.remove_roles(*roles, reason=reason)
                    results.append("✅ ڕۆڵەکانی لابرا: " + ", ".join(f"`{r.name}`" for r in roles))
                except Exception:
                    results.append("❌ نەتوانرا ڕۆڵەکان لابدرێن (ڕۆڵی بۆتەکە بەرز بکەرەوە).")
            else:
                results.append("ℹ️ ڕۆڵێک نەبوو بۆ لابردن.")
        else:
            results.append("ℹ️ لابردنی ڕۆڵ بۆ ئەم بەشە OFF ـە.")

        # ---- timeout / kick / ban ----
        p = s["punish"]
        try:
            if p == "timeout":
                mins = max(1, min(int(m["timeout"]), 40320))
                await member.timeout(datetime.timedelta(minutes=mins), reason=reason)
                results.append(f"✅ Timeout بۆ `{mins}` خولەک.")
            elif p == "kick":
                await member.kick(reason=reason)
                results.append("✅ Kick کرا.")
            elif p == "ban":
                await member.ban(reason=reason, delete_message_seconds=0)
                results.append("✅ Ban کرا.")
        except Exception:
            results.append(f"❌ نەتوانرا `{SEC_PUNISH_LABELS[p]}` بکرێت (مۆڵەت / ڕۆڵی بۆتەکە).")

    details = _sec_details.pop((guild.id, uid), [])
    window = f"لە `{m['seconds']}` چرکەدا" if m["seconds"] > 0 else "لە یەک نامەدا"
    embed = discord.Embed(
        title="🛡️ Security Warning",
        description=(
            f"**Member:** <@{uid}>\n"
            f"**بەش:** {label}\n\n"
            f"**هۆکاری سزا:**\n"
            f"ئەم ئەندامە {window} `{count}` جار ئەم کارەی کرد، لە کاتێکدا Limit ـەکە `{m['limit']}` ـە.\n\n"
            f"**چی کرد:**\n" + ("\n".join(details) or "—") +
            "\n\n**سزا:**\n" + "\n".join(results)
        ),
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.set_footer(text="Security")
    if member:
        add_user_thumbnail(embed, member)
    await sec_send_warning(guild, embed)


async def sec_register(guild, uid, key, what):
    """Count one action. Returns True if the user was punished."""
    if uid is None or not sec_mod_on(guild, key) or sec_exempt(guild, uid) or sec_mod_exempt(guild, uid, key):
        return False
    m = get_sec(guild.id)["modules"][key]
    sec_add_detail(guild.id, uid, what)
    dq = _sec_hits[(guild.id, uid, key)]
    now = time.time()
    dq.append(now)
    if m["seconds"] > 0:
        while dq and now - dq[0] > m["seconds"]:
            dq.popleft()
    if len(dq) > m["limit"]:
        n = len(dq)
        dq.clear()
        await sec_punish(guild, uid, key, n)
        return True
    return False


# ---------------------------------------------------------
# message protection
# ---------------------------------------------------------

async def sec_safe_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


async def sec_on_message(message):
    if message.author.bot or message.guild is None:
        return

    guild = message.guild
    s = get_sec(guild.id)
    if not s["enabled"] or sec_exempt(guild, message.author.id):
        return

    uid = message.author.id
    mods = s["modules"]
    text = message.content or ""

    def skip(key):
        return sec_mod_exempt(guild, uid, key, message.channel)

    # ---- mention spam ----
    if mods["mention"]["enabled"] and not skip("mention"):
        cnt = len(message.mentions) + len(message.role_mentions) + (1 if message.mention_everyone else 0)
        if cnt > mods["mention"]["limit"]:
            await sec_safe_delete(message)
            sec_add_detail(guild.id, uid, f"📢 {cnt} تاگی کرد لە یەک نامەدا لە {message.channel.mention}")
            await sec_punish(guild, uid, "mention", cnt)
            return

    # ---- invite / link ----
    for key, rx in (("invite", SEC_INVITE_RX), ("link", SEC_LINK_RX)):
        if mods[key]["enabled"] and rx.search(text) and not is_partner_channel(message) and not skip(key):
            await sec_safe_delete(message)
            done = await sec_register(
                guild, uid, key,
                f"🔗 {SEC_MODULES[key][0]}: لینکی نارد لە {message.channel.mention}"
            )
            if not done:
                try:
                    await message.channel.send(
                        f"⚠ {message.author.mention} نابێت لینک بنێریت.", delete_after=6)
                except Exception:
                    pass
            return

    # ---- message spam ----
    m = mods["spam"]
    if m["enabled"] and not skip("spam"):
        now = time.time()
        dq = _sec_spam[(guild.id, uid)]
        dq.append((now, message))
        while dq and now - dq[0][0] > m["seconds"]:
            dq.popleft()
        if len(dq) > m["limit"]:
            msgs = [x[1] for x in dq]
            dq.clear()
            by_ch = defaultdict(list)
            for x in msgs:
                by_ch[x.channel].append(x)
            for ch, lst in by_ch.items():
                try:
                    await ch.delete_messages(lst)
                except Exception:
                    pass
            sec_add_detail(guild.id, uid, f"💬 {len(msgs)} نامەی نارد لە {m['seconds']} چرکەدا")
            await sec_punish(guild, uid, "spam", len(msgs))


# ---------------------------------------------------------
# anti-nuke events
# ---------------------------------------------------------

async def sec_on_channel_create(channel):
    g = channel.guild
    if not sec_mod_on(g, "chan_create"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.channel_create], channel.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "chan_create", f"📁 چەناڵی `{channel.name}` دروست کرد")


async def sec_on_channel_delete(channel):
    g = channel.guild
    if not sec_mod_on(g, "chan_delete"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.channel_delete], channel.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "chan_delete", f"🗑️ چەناڵی `#{channel.name}` سڕییەوە")


async def sec_on_channel_update(before, after):
    g = after.guild
    if before.name != after.name and sec_mod_on(g, "chan_name"):
        entry = await sec_audit(g, [discord.AuditLogAction.channel_update], after.id)
        if entry and entry.user:
            await sec_register(g, entry.user.id, "chan_name",
                               f"✏️ ناوی چەناڵی `{before.name}` گۆڕی بۆ `{after.name}`")
    if before.overwrites != after.overwrites and sec_mod_on(g, "chan_perm"):
        entry = await sec_audit(g, [discord.AuditLogAction.overwrite_update,
                                    discord.AuditLogAction.overwrite_create,
                                    discord.AuditLogAction.overwrite_delete], after.id)
        if entry and entry.user:
            await sec_register(g, entry.user.id, "chan_perm",
                               f"🔐 پێرمشنی چەناڵی {after.mention} گۆڕی")


async def sec_on_role_create(role):
    g = role.guild
    if role.managed or not sec_mod_on(g, "role_create"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.role_create], role.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "role_create", f"➕ ڕۆڵی `{role.name}` دروست کرد")


async def sec_on_role_delete(role):
    g = role.guild
    if role.managed or not sec_mod_on(g, "role_delete"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.role_delete], role.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "role_delete", f"🗑️ ڕۆڵی `{role.name}` سڕییەوە")


async def sec_on_role_update(before, after):
    g = after.guild
    if after.managed:
        return
    if before.name != after.name and sec_mod_on(g, "role_name"):
        entry = await sec_audit(g, [discord.AuditLogAction.role_update], after.id)
        if entry and entry.user:
            await sec_register(g, entry.user.id, "role_name",
                               f"✏️ ناوی ڕۆڵی `{before.name}` گۆڕی بۆ `{after.name}`")
    if before.permissions != after.permissions and sec_mod_on(g, "role_perm"):
        entry = await sec_audit(g, [discord.AuditLogAction.role_update], after.id)
        if entry and entry.user:
            await sec_register(g, entry.user.id, "role_perm",
                               f"🔐 پێرمشنی ڕۆڵی `{after.name}` گۆڕی")


async def sec_on_ban(guild, user):
    if not sec_mod_on(guild, "ban"):
        return
    entry = await sec_audit(guild, [discord.AuditLogAction.ban], user.id)
    uid = sec_executor_id(entry, "ban", user.id)
    if uid:
        await sec_register(guild, uid, "ban", f"🔨 {user} (`{user.id}`) ی Ban کرد")


async def sec_on_member_remove(member):
    g = member.guild
    if not sec_mod_on(g, "kick"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.kick], member.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "kick", f"👢 {member} (`{member.id}`) ی Kick کرد")


async def sec_on_member_join(member):
    if not member.bot:
        return
    g = member.guild
    if not sec_mod_on(g, "bot_add"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.bot_add], member.id)
    if not (entry and entry.user) or sec_exempt(g, entry.user.id) or sec_mod_exempt(g, entry.user.id, "bot_add"):
        return
    try:
        await member.kick(reason="Security: Anti-Bot Add")
    except Exception:
        pass
    await sec_register(g, entry.user.id, "bot_add", f"🤖 بۆتی {member} (`{member.id}`) ی زیادکرد (دەرکرا)")


bot.add_listener(sec_on_message, "on_message")
bot.add_listener(sec_on_channel_create, "on_guild_channel_create")
bot.add_listener(sec_on_channel_delete, "on_guild_channel_delete")
bot.add_listener(sec_on_channel_update, "on_guild_channel_update")
bot.add_listener(sec_on_role_create, "on_guild_role_create")
bot.add_listener(sec_on_role_delete, "on_guild_role_delete")
bot.add_listener(sec_on_role_update, "on_guild_role_update")
bot.add_listener(sec_on_ban, "on_member_ban")
bot.add_listener(sec_on_member_remove, "on_member_remove")
bot.add_listener(sec_on_member_join, "on_member_join")


# ---------------------------------------------------------
# /security panel
# ---------------------------------------------------------

def sec_main_embed(guild):
    s = get_sec(guild.id)
    lines = []
    for k, (label, *_rest) in SEC_MODULES.items():
        m = s["modules"][k]
        lines.append(
            f"{'🟢' if m['enabled'] else '🔴'} **{label}** — `{m['limit']}` / `{m['seconds']}s` / `{m['timeout']}m`"
            + (" 🎭" if m["remove_roles"] else "")
        )
    e = discord.Embed(
        title="🛡️ Security " + ("(ON)" if s["enabled"] else "(OFF)"),
        description="\n".join(lines),
        color=discord.Color.green() if s["enabled"] else discord.Color.red()
    )
    lc = s.get("log_channel")
    e.add_field(
        name="کەناڵی وارنینگ",
        value=f"<#{lc}>" if lc else "❌ دیاری نەکراوە (Server Log بەکاردێت)",
        inline=False
    )
    e.add_field(
        name="سزا",
        value=f"**{SEC_PUNISH_LABELS[s['punish']]}**\n🎭 = ڕۆڵەکان لادەبرێن",
        inline=False
    )
    e.set_footer(text="Limit / Seconds / Timeout(خولەک) — بەشێک هەڵبژێرە بۆ دەستکاری")
    return e


def sec_module_embed(guild, key):
    label, _, _, _, _, hint = SEC_MODULES[key]
    m = get_sec(guild.id)["modules"][key]
    e = discord.Embed(
        title=f"🛡️ {label}",
        description=hint,
        color=discord.Color.green() if m["enabled"] else discord.Color.red()
    )
    e.add_field(name="Status", value="🟢 ON" if m["enabled"] else "🔴 OFF")
    e.add_field(name="Limit", value=f"`{m['limit']}`")
    e.add_field(name="Seconds", value=f"`{m['seconds']}`")
    e.add_field(name="Timeout (خولەک)", value=f"`{m['timeout']}`")
    e.add_field(name="Remove Roles", value="🎭 بەڵێ" if m["remove_roles"] else "نەخێر")
    wl = f"👤 {len(m['wl_users'])} | 🎭 {len(m['wl_roles'])}"
    if key in SEC_MSG_MODULES:
        wl += f" | 💬 {len(m['wl_channels'])}"
    e.add_field(name="Whitelist", value=wl)
    return e


def sec_wl_embed(guild):
    s = get_sec(guild.id)
    us = ", ".join(f"<@{u}>" for u in s["wl_users"]) or "—"
    rs = ", ".join(f"<@&{r}>" for r in s["wl_roles"]) or "—"
    return discord.Embed(
        title="✅ Whitelist",
        description=(
            f"**Users:** {us}\n**Roles:** {rs}\n\n"
            "ئەوەی هەڵیدەبژێریت: ئەگەر لە لیستدا بێت لادەچێت، ئەگەر نەبێت زیاد دەبێت.\n"
            "Owner و Developer (`/setdev`) خۆکار ڕزگاربوون."
        ),
        color=discord.Color.blurple()
    )


class SecBaseView(discord.ui.View):
    def __init__(self, guild, author_id):
        super().__init__(timeout=300)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id or not is_dev(interaction.user):
            await deny_interaction(interaction)
            return False
        return True


class SecModuleSelect(discord.ui.Select):
    def __init__(self, guild):
        s = get_sec(guild.id)
        opts = [
            discord.SelectOption(
                label=label, value=k, description=hint[:100],
                emoji="🟢" if s["modules"][k]["enabled"] else "🔴"
            )
            for k, (label, _, _, _, _, hint) in SEC_MODULES.items()
        ]
        super().__init__(placeholder="بەشێک هەڵبژێرە...", options=opts, row=0)

    async def callback(self, interaction):
        key = self.values[0]
        await interaction.response.edit_message(
            embed=sec_module_embed(self.view.guild, key),
            view=SecModuleView(self.view.guild, self.view.author_id, key)
        )


class SecLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="کەناڵی وارنینگ هەڵبژێرە...",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1, row=1
        )

    async def callback(self, interaction):
        get_sec(self.view.guild.id)["log_channel"] = self.values[0].id
        save_config()
        await interaction.response.edit_message(
            embed=sec_main_embed(self.view.guild),
            view=SecMainView(self.view.guild, self.view.author_id)
        )


class SecMainView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        s = get_sec(guild.id)
        self.add_item(SecModuleSelect(guild))
        self.add_item(SecLogChannelSelect())
        self.toggle.label = "Security: ON" if s["enabled"] else "Security: OFF"
        self.toggle.style = discord.ButtonStyle.success if s["enabled"] else discord.ButtonStyle.danger
        self.punish_btn.label = "Punishment: " + SEC_PUNISH_LABELS[s["punish"]]

    @discord.ui.button(label="Security", row=2)
    async def toggle(self, interaction, button):
        s = get_sec(self.guild.id)
        s["enabled"] = not s["enabled"]
        save_config()
        await interaction.response.edit_message(
            embed=sec_main_embed(self.guild), view=SecMainView(self.guild, self.author_id))

    @discord.ui.button(label="Punishment", style=discord.ButtonStyle.primary, row=2)
    async def punish_btn(self, interaction, button):
        s = get_sec(self.guild.id)
        i = SEC_PUNISH_ORDER.index(s["punish"])
        s["punish"] = SEC_PUNISH_ORDER[(i + 1) % len(SEC_PUNISH_ORDER)]
        save_config()
        await interaction.response.edit_message(
            embed=sec_main_embed(self.guild), view=SecMainView(self.guild, self.author_id))

    @discord.ui.button(label="Whitelist", style=discord.ButtonStyle.secondary, row=3)
    async def wl_btn(self, interaction, button):
        await interaction.response.edit_message(
            embed=sec_wl_embed(self.guild), view=SecWhitelistView(self.guild, self.author_id))


class SecLimitModal(discord.ui.Modal):
    def __init__(self, guild, author_id, key):
        super().__init__(title=f"Edit: {SEC_MODULES[key][0]}"[:45])
        m = get_sec(guild.id)["modules"][key]
        self.guild, self.author_id, self.key = guild, author_id, key
        self.limit = discord.ui.TextInput(label="Limit", default=str(m["limit"]), max_length=4)
        self.seconds = discord.ui.TextInput(label="Seconds (چرکە)", default=str(m["seconds"]), max_length=5)
        self.timeout_min = discord.ui.TextInput(label="Timeout (خولەک)", default=str(m["timeout"]), max_length=5)
        self.add_item(self.limit)
        self.add_item(self.seconds)
        self.add_item(self.timeout_min)

    async def on_submit(self, interaction):
        try:
            lim = int(self.limit.value)
            sec = int(self.seconds.value)
            tmo = int(self.timeout_min.value)
            assert lim >= 0 and sec >= 0 and 1 <= tmo <= 40320
        except Exception:
            await interaction.response.send_message(
                "❌ تەنها ژمارە بنووسە (Timeout لە 1 تا 40320 خولەک).", ephemeral=True)
            return
        m = get_sec(self.guild.id)["modules"][self.key]
        m["limit"], m["seconds"], m["timeout"] = lim, sec, tmo
        save_config()
        await interaction.response.edit_message(
            embed=sec_module_embed(self.guild, self.key),
            view=SecModuleView(self.guild, self.author_id, self.key))


class SecModuleView(SecBaseView):
    def __init__(self, guild, author_id, key):
        super().__init__(guild, author_id)
        self.key = key
        mm = get_sec(guild.id)["modules"][key]
        on = mm["enabled"]
        self.toggle.label = "Turn OFF" if on else "Turn ON"
        self.toggle.style = discord.ButtonStyle.danger if on else discord.ButtonStyle.success
        self.roles_btn.label = "Remove Roles: " + ("ON" if mm["remove_roles"] else "OFF")
        self.roles_btn.style = discord.ButtonStyle.success if mm["remove_roles"] else discord.ButtonStyle.secondary

    @discord.ui.button(label="Toggle")
    async def toggle(self, interaction, button):
        m = get_sec(self.guild.id)["modules"][self.key]
        m["enabled"] = not m["enabled"]
        save_config()
        await interaction.response.edit_message(
            embed=sec_module_embed(self.guild, self.key),
            view=SecModuleView(self.guild, self.author_id, self.key))

    @discord.ui.button(label="Remove Roles", row=1)
    async def roles_btn(self, interaction, button):
        m = get_sec(self.guild.id)["modules"][self.key]
        m["remove_roles"] = not m["remove_roles"]
        save_config()
        await interaction.response.edit_message(
            embed=sec_module_embed(self.guild, self.key),
            view=SecModuleView(self.guild, self.author_id, self.key))

    @discord.ui.button(label="Whitelist ›", style=discord.ButtonStyle.secondary, row=1)
    async def mod_wl_btn(self, interaction, button):
        await interaction.response.edit_message(
            embed=secmod_wl_embed(self.guild, self.key),
            view=SecModWLView(self.guild, self.author_id, self.key))

    @discord.ui.button(label="Edit Limit / Seconds / Timeout", style=discord.ButtonStyle.primary)
    async def edit_btn(self, interaction, button):
        await interaction.response.send_modal(SecLimitModal(self.guild, self.author_id, self.key))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=sec_main_embed(self.guild), view=SecMainView(self.guild, self.author_id))


class SecWLUsers(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Users", min_values=1, max_values=10, row=0)

    async def callback(self, interaction):
        s = get_sec(self.view.guild.id)
        for u in self.values:
            if u.id in s["wl_users"]:
                s["wl_users"].remove(u.id)
            else:
                s["wl_users"].append(u.id)
        save_config()
        await interaction.response.edit_message(
            embed=sec_wl_embed(self.view.guild),
            view=SecWhitelistView(self.view.guild, self.view.author_id))


class SecWLRoles(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="Roles", min_values=1, max_values=10, row=1)

    async def callback(self, interaction):
        s = get_sec(self.view.guild.id)
        for r in self.values:
            if r.id in s["wl_roles"]:
                s["wl_roles"].remove(r.id)
            else:
                s["wl_roles"].append(r.id)
        save_config()
        await interaction.response.edit_message(
            embed=sec_wl_embed(self.view.guild),
            view=SecWhitelistView(self.view.guild, self.view.author_id))


class SecWhitelistView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        self.add_item(SecWLUsers())
        self.add_item(SecWLRoles())

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=sec_main_embed(self.guild), view=SecMainView(self.guild, self.author_id))


@bot.tree.command(name="security", description="سیستمی پاراستن (Anti-Spam / Anti-Nuke)")
@app_commands.guild_only()
async def security_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=sec_main_embed(interaction.guild),
        view=SecMainView(interaction.guild, interaction.user.id),
        ephemeral=True
    )


# =========================================================
# 31. VOICE DISCONNECT HELPER (بۆ لۆگی ڤۆیس)
# =========================================================
# ئەم بەشە لە "# 30. RUN" ەوە بێنە سەرەوە (پێش RUN)

_vc_disc_seen = {}   # audit entry id -> count


async def find_voice_disconnector(guild):
    """ئەگەر کەسێک بە ڕاکێشان/Disconnect ئەندامێکی لە ڤۆیس دەرکرد، ئەو کەسە دەگەڕێنێتەوە."""
    await asyncio.sleep(1.5)
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_disconnect):
            count = int(getattr(entry.extra, "count", 1) or 1)
            prev = _vc_disc_seen.get(entry.id)
            _vc_disc_seen[entry.id] = count
            if prev is None:
                age = (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds()
                if age <= 15:
                    return entry.user
            elif count > prev:
                return entry.user
    except Exception:
        pass
    return None


async def vc_prime_cache():
    for g in bot.guilds:
        try:
            async for entry in g.audit_logs(limit=10, action=discord.AuditLogAction.member_disconnect):
                _vc_disc_seen[entry.id] = int(getattr(entry.extra, "count", 1) or 1)
        except Exception:
            pass


bot.add_listener(vc_prime_cache, "on_ready")


# =========================================================
# 32. SHARED HELPERS FOR /autoreact AND /reklam
# =========================================================

EMOJI_RX = re.compile(r"<a?:\w+:\d+>")


def parse_emojis(text):
    """<a:white:123> / ئیمۆجی ڕاستەوخۆ / ئایدی ئیمۆجی (ئەگەر بۆتەکە لەو سێرڤەرە بێت) — بە space جیا بکەرەوە"""
    out = []
    for tok in text.split():
        found = EMOJI_RX.findall(tok)
        if found:
            out.extend(found)
        elif tok.isdigit():
            e = bot.get_emoji(int(tok))
            if e:
                out.append(str(e))
        elif not tok.isascii():
            out.append(tok)
    return [e for i, e in enumerate(out) if e not in out[:i]]


async def panel_edit(interaction, ctx, kind):
    """ctx = view یان modal (guild و author_id ی هەیە)"""
    g, uid = ctx.guild, ctx.author_id
    if kind == "ar":
        await interaction.response.edit_message(embed=ar_embed(g), view=ArView(g, uid))
    elif kind == "rkp":
        await interaction.response.edit_message(embed=rkp_embed(g), view=RkPartnerView(g, uid))
    elif kind == "bl":
        await interaction.response.edit_message(embed=bl_embed(g), view=BlView(g, uid))
    else:
        await interaction.response.edit_message(embed=rk_embed(g), view=RkView(g, uid))


class PanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, kind, row=0):
        super().__init__(
            placeholder="کەناڵەکان هەڵبژێرە (چەند کەناڵ)...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.voice],
            min_values=1, max_values=25, row=row
        )
        self.kind = kind

    async def callback(self, interaction):
        g = self.view.guild
        getter = {"ar": get_ar, "rk": get_rk, "rkp": get_rk, "bl": get_bl}[self.kind]
        field = "partner_channels" if self.kind == "rkp" else "channels"
        picked = [c.id for c in self.values]
        if self.kind == "ar":
            # Auto React: کەناڵی نوێ دەخرێتە سەر کەناڵە پێشووەکان (هیچ شتێک ناسڕدرێتەوە)
            old = getter(g.id)[field]
            getter(g.id)[field] = old + [c for c in picked if c not in old]
        else:
            getter(g.id)[field] = picked
        save_config()
        await panel_edit(interaction, self.view, self.kind)


class PanelRoleSelect(discord.ui.RoleSelect):
    def __init__(self, kind, field, placeholder, row):
        super().__init__(placeholder=placeholder, min_values=1, max_values=25, row=row)
        self.kind, self.field = kind, field

    async def callback(self, interaction):
        g = self.view.guild
        get_rk(g.id)[self.field] = [r.id for r in self.values]
        save_config()
        await panel_edit(interaction, self.view, self.kind)


# =========================================================
# 33. AUTOREACT  (/autoreact)
# =========================================================

AR_MODE_ORDER = ["all", "image", "video", "text"]
AR_MODE_LABELS = {
    "all": "Text + Image + Video",
    "image": "Image / GIF only",
    "video": "Video only",
    "text": "Text only",
}
AR_MAX_EMOJIS = 20   # Discord: زۆرترین 20 ڕیاکت لەسەر هەر نامەیەک
IMG_LINK_RX = re.compile(r"https?://\S+\.(?:png|jpe?g|gif|webp)(?:\?\S*)?|tenor\.com/|giphy\.com/", re.I)


def get_ar(gid):
    a = cfg(gid).setdefault("autoreact", {})
    a.setdefault("enabled", True)
    a.setdefault("channels", [])
    a.setdefault("emojis", [])
    a.setdefault("mode", "all")
    if a["mode"] not in AR_MODE_LABELS:
        a["mode"] = "all"
    return a


def ar_embed(guild):
    a = get_ar(guild.id)
    chans = "\n".join(f"<#{c}>" for c in a["channels"]) or "❌"
    ems = " ".join(a["emojis"]) or "❌"
    e = discord.Embed(
        title="😀 Auto React " + ("(ON)" if a["enabled"] else "(OFF)"),
        color=discord.Color.green() if a["enabled"] else discord.Color.red()
    )
    e.add_field(name="کەناڵەکان", value=chans[:1000], inline=False)
    e.add_field(name=f"ئیمۆجیەکان ({len(a['emojis'])}/{AR_MAX_EMOJIS})", value=ems[:1000], inline=False)
    e.add_field(name="ڕیاکت لەسەر", value=AR_MODE_LABELS[a["mode"]], inline=False)
    e.set_footer(text="کەناڵی نوێ هەڵبژێریت زیاد دەبێت بۆ پێشووەکان ✅ | بۆ لابردنی یەک کەناڵ لیستی خوارەوە بەکاربهێنە")
    return e


def msg_has_image(m):
    for a in m.attachments:
        ct = (a.content_type or "").lower()
        if ct.startswith("image/") or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return True
    for e in m.embeds:
        if e.type in ("image", "gifv") or e.image.url or e.thumbnail.url:
            return True
    return bool(IMG_LINK_RX.search(m.content or ""))


VIDEO_LINK_RX = re.compile(
    r"https?://\S+\.(?:mp4|mov|webm|mkv)(?:\?\S*)?|youtu\.be/|youtube\.com/watch|streamable\.com/", re.I)


def msg_has_video(m):
    for a in m.attachments:
        ct = (a.content_type or "").lower()
        if ct.startswith("video/") or a.filename.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".avi")):
            return True
    for e in m.embeds:
        if e.type == "video":
            return True
    return bool(VIDEO_LINK_RX.search(m.content or ""))


def ar_has_image(m):
    """وەک msg_has_image، بەڵام وێنە بچووکەکەی ئیمبێدی بۆت (thumbnail) بە وێنە ناژمێردرێت"""
    for a in m.attachments:
        ct = (a.content_type or "").lower()
        if ct.startswith("image/") or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return True
    for e in m.embeds:
        if e.type in ("image", "gifv") or e.image.url:
            return True
        if e.type != "rich" and e.thumbnail.url:
            return True
    return bool(IMG_LINK_RX.search(m.content or ""))


def ar_has_text(m):
    """دەق لە نامەکە، یان لە ناو ئیمبێدی (وەک تێکستی گۆرانی)"""
    if (m.content or "").strip():
        return True
    for e in m.embeds:
        if e.type == "rich" and (e.title or e.description or e.fields):
            return True
    return False


async def ar_on_message(message):
    if message.guild is None:
        return
    # نامەی بۆت (وەک /song-texts) ڕیاکت وەردەگرێت، بەڵام پانێل و دووگمەکان نا
    if message.author.bot:
        if message.components or message.id in _ar_pick:
            return
    if message.type not in (discord.MessageType.default, discord.MessageType.reply):
        return
    a = get_ar(message.guild.id)
    if not a["enabled"] or not a["emojis"] or not a["channels"]:
        return
    ch = message.channel
    if ch.id not in a["channels"] and getattr(ch, "parent_id", None) not in a["channels"]:
        return

    has_vid = msg_has_video(message)
    has_img = ar_has_image(message) and not has_vid
    has_text = ar_has_text(message)
    has_file = bool(message.attachments)      # ئۆدیۆ / فایل / هەر هاوپێچێک
    mode = a["mode"]
    if mode == "image":
        ok = has_img
    elif mode == "video":
        ok = has_vid
    elif mode == "text":
        ok = has_text and not has_img and not has_vid
    else:
        ok = has_img or has_vid or has_text or has_file or bool(message.embeds)
    if not ok:
        return

    for e in list(a["emojis"]):
        try:
            await message.add_reaction(discord.PartialEmoji.from_str(e))
        except discord.Forbidden:
            print(f"autoreact: بۆتەکە مۆڵەتی Add Reactions / Read Message History ی نییە لە #{message.channel}", flush=True)
            return
        except discord.NotFound as ex:
            if ex.code == 10008:   # نامەکە سڕایەوە
                return
            print(f"autoreact: ئیمۆجی {e} نەدۆزرایەوە (بۆتەکە لەو سێرڤەرەدا نییە کە ئیمۆجییەکەی لێیە)", flush=True)
        except Exception as ex:
            print(f"autoreact error ({e}): {ex}", flush=True)
            continue


bot.add_listener(ar_on_message, "on_message")


class ArRemoveSelect(discord.ui.Select):
    def __init__(self, emojis):
        opts = []
        for i, e in enumerate(emojis[:25]):
            pe = discord.PartialEmoji.from_str(e)
            opts.append(discord.SelectOption(label=f"{i + 1}. {pe.name}"[:100], value=e))
        super().__init__(
            placeholder="ئیمۆجی هەڵبژێرە بۆ لابردن...",
            options=opts, min_values=1, max_values=len(opts), row=1
        )

    async def callback(self, interaction):
        a = get_ar(self.view.guild.id)
        a["emojis"] = [e for e in a["emojis"] if e not in self.values]
        save_config()
        await panel_edit(interaction, self.view, "ar")


class ArChannelRemoveSelect(discord.ui.Select):
    """لابردنی یەک یان چەند کەناڵ لە لیستەکە (بەبێ ئەوەی ئەوانی تر بسڕدرێنەوە)"""
    def __init__(self, guild, channels):
        opts = []
        for cid in channels[:25]:
            ch = guild.get_channel(cid) or guild.get_thread(cid)
            label = f"#{ch.name}" if ch else f"(کەناڵی سڕاوە) {cid}"
            opts.append(discord.SelectOption(label=label[:100], value=str(cid)))
        super().__init__(
            placeholder="کەناڵ هەڵبژێرە بۆ لابردن لە لیستەکە...",
            options=opts, min_values=1, max_values=len(opts), row=4
        )

    async def callback(self, interaction):
        a = get_ar(self.view.guild.id)
        gone = {int(v) for v in self.values}
        a["channels"] = [c for c in a["channels"] if c not in gone]
        save_config()
        await panel_edit(interaction, self.view, "ar")


class ArEmojiModal(discord.ui.Modal):
    def __init__(self, guild, author_id):
        super().__init__(title="Add Emojis")
        self.guild, self.author_id = guild, author_id
        self.box = discord.ui.TextInput(
            label="ئیمۆجیەکان (بە space جیا بکەرەوە)",
            style=discord.TextStyle.paragraph,
            placeholder="<a:white:1533233199457763338> 🔥 ❤️",
            max_length=2000
        )
        self.add_item(self.box)

    async def on_submit(self, interaction):
        a = get_ar(self.guild.id)
        for e in parse_emojis(self.box.value):
            if e not in a["emojis"] and len(a["emojis"]) < AR_MAX_EMOJIS:
                a["emojis"].append(e)
        save_config()
        await panel_edit(interaction, self, "ar")


class ArView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        a = get_ar(guild.id)
        self.add_item(PanelChannelSelect("ar", row=0))
        if a["emojis"]:
            self.add_item(ArRemoveSelect(a["emojis"]))
        if a["channels"]:
            self.add_item(ArChannelRemoveSelect(guild, a["channels"]))
        self.toggle.label = "Auto React: ON" if a["enabled"] else "Auto React: OFF"
        self.toggle.style = discord.ButtonStyle.success if a["enabled"] else discord.ButtonStyle.danger
        self.mode_btn.label = AR_MODE_LABELS[a["mode"]]

    @discord.ui.button(label="Toggle", row=2)
    async def toggle(self, interaction, button):
        a = get_ar(self.guild.id)
        a["enabled"] = not a["enabled"]
        save_config()
        await panel_edit(interaction, self, "ar")

    @discord.ui.button(label="Mode", style=discord.ButtonStyle.primary, row=2)
    async def mode_btn(self, interaction, button):
        a = get_ar(self.guild.id)
        i = AR_MODE_ORDER.index(a["mode"])
        a["mode"] = AR_MODE_ORDER[(i + 1) % len(AR_MODE_ORDER)]
        save_config()
        await panel_edit(interaction, self, "ar")

    @discord.ui.button(label="Add Emojis", style=discord.ButtonStyle.secondary, row=2)
    async def add_btn(self, interaction, button):
        await interaction.response.send_modal(ArEmojiModal(self.guild, self.author_id))

    @discord.ui.button(label="Clear Emojis", style=discord.ButtonStyle.secondary, row=2)
    async def clear_emojis(self, interaction, button):
        get_ar(self.guild.id)["emojis"] = []
        save_config()
        await panel_edit(interaction, self, "ar")

    @discord.ui.button(label="Clear Channels", style=discord.ButtonStyle.secondary, row=2)
    async def clear_channels(self, interaction, button):
        get_ar(self.guild.id)["channels"] = []
        save_config()
        await panel_edit(interaction, self, "ar")


    @discord.ui.button(label="Pick by Reacting", style=discord.ButtonStyle.success, row=3)
    async def pick_btn(self, interaction, button):
        try:
            view = ArPickView(self.guild, interaction.user.id)
            msg = await interaction.channel.send(
                f"{interaction.user.mention} 👇 ئیمۆجیەکان وەک ڕیاکت لەسەر ئەم نامەیە دابنێ "
                f"(لە پیکەری ئیمۆجی خۆت هەڵیانبژێرە)، پاشان **Done** دابگرە.",
                view=view
            )
        except Exception:
            await interaction.response.send_message(
                "❌ بۆتەکە ناتوانێت لەم کەناڵە بنووسێت.", ephemeral=True)
            return
        view.message = msg
        _ar_pick[msg.id] = {"uid": interaction.user.id, "emojis": []}
        await interaction.response.send_message(
            "✅ نامەیەک نێردرا لە چاتەکە، ئیمۆجیەکان وەک ڕیاکت لەسەری دابنێ و Done دابگرە.",
            ephemeral=True)


_ar_pick = {}   # message_id -> {"uid": ..., "emojis": [...]}


async def ar_on_raw_reaction(payload):
    p = _ar_pick.get(payload.message_id)
    if not p or payload.user_id != p["uid"]:
        return
    e = str(payload.emoji)
    if e not in p["emojis"]:
        p["emojis"].append(e)


bot.add_listener(ar_on_raw_reaction, "on_raw_reaction_add")


class ArPickView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        self.timeout = 180
        self.message = None

    async def on_timeout(self):
        if self.message:
            _ar_pick.pop(self.message.id, None)
            try:
                await self.message.delete()
            except Exception:
                pass

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success)
    async def done(self, interaction, button):
        p = _ar_pick.pop(interaction.message.id, None)
        a = get_ar(self.guild.id)
        added = 0
        for e in (p["emojis"] if p else []):
            if e not in a["emojis"] and len(a["emojis"]) < AR_MAX_EMOJIS:
                a["emojis"].append(e)
                added += 1
        save_config()
        await interaction.response.send_message(
            f"✅ `{added}` ئیمۆجی زیادکرا. `/autoreact` بکەرەوە بۆ بینین.", ephemeral=True)
        try:
            await interaction.message.delete()
        except Exception:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        _ar_pick.pop(interaction.message.id, None)
        await interaction.response.send_message("❌ هەڵوەشایەوە.", ephemeral=True)
        try:
            await interaction.message.delete()
        except Exception:
            pass


@bot.tree.command(name="autoreact", description="ڕیاکتی خۆکار لە چەند کەناڵێک")
@app_commands.guild_only()
async def autoreact_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=ar_embed(interaction.guild),
        view=ArView(interaction.guild, interaction.user.id),
        ephemeral=True
    )


# =========================================================
# 34. REKLAM  (/reklam)
# =========================================================

RK_DEFAULT_TRIGGERS = ["reklam", "ریکلام", "ڕیکلام"]
RK_LINK_WORD_RX = re.compile(r"(?<!\w)(?:link(?!\w)|لینک|لينك)", re.I)


RK_MEDIA_URL_RX = re.compile(
    r"https?://(?:\S*\.(?:gif|png|jpe?g|webp|mp4)(?:\?\S*)?|(?:www\.)?(?:tenor\.com|giphy\.com|media\.giphy\.com|imgur\.com|i\.imgur\.com|media\.discordapp\.net|cdn\.discordapp\.com)\S*)",
    re.I)


def rk_link_messages(parts):
    """Split the Link text at every GIF/image link, keeping the order you wrote it.
    Text chunks stay normal messages; a GIF link goes alone in its own message so Discord
    shows only the GIF (no link text)."""
    out, buf = [], ""
    for part in parts:
        pos = 0
        for m in RK_MEDIA_URL_RX.finditer(part):
            buf += part[pos:m.start()]
            if buf.strip():
                out.append(buf.strip())
            buf = ""
            out.append(m.group(0))
            pos = m.end()
        buf += part[pos:] + "\n"
    if buf.strip():
        out.append(buf.strip())
    return [x[:2000] for x in out]


async def rk_send_link(ch, parts):
    """Send the Link message as ONE normal message: text + server link (with its invite card),
    and the GIF attached to the same message."""
    texts, files = [], []
    for chunk in rk_link_messages(parts):
        if RK_MEDIA_URL_RX.fullmatch(chunk) and len(files) < 10:
            path = await rk_media_get(chunk)        # re-upload the GIF itself (no link text)
            if path:
                files.append(discord.File(path, filename=f"reklam{len(files)+1}" + os.path.splitext(path)[1]))
                continue
        texts.append(chunk)
    try:
        await ch.send("\n".join(texts)[:2000] or None, files=files,
                      allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        print(f"reklam link auto-send error: {e}", flush=True)


def get_rk(gid):
    rk = cfg(gid).setdefault("reklam", {})
    rk.setdefault("enabled", True)
    rk.setdefault("channels", [])
    rk.setdefault("tag_roles", [])
    rk.setdefault("blocked_roles", [])
    rk.setdefault("triggers", list(RK_DEFAULT_TRIGGERS))
    rk.setdefault("title", "Reklam")
    rk.setdefault("text", "{user}\n\n{roles}")
    rk.setdefault("image", None)
    rk.setdefault("thumb", "avatar")     # "avatar" = وێنەی ئەو کەسەی Reklam ی نووسی
    rk.setdefault("footer", None)
    rk.setdefault("reply", False)
    rk.setdefault("partner_enabled", True)
    rk.setdefault("partner_channels", [])
    # Auto-publish the server invite when someone types Link/link in a selected Reklam channel.
    rk.setdefault("server_link", "")
    rk.setdefault("link_before", "")
    rk.setdefault("link_after", "")
    rk.setdefault("link_gif", "")
    rk.setdefault("counting", {"partner_channel": None, "board_channel": None, "board_message": None})
    return rk


def rk_build_embed(guild, member):
    rk = get_rk(guild.id)
    roles_text = " ".join(f"<@&{r}>" for r in rk["tag_roles"] if guild.get_role(r))
    text = (rk["text"] or "").replace("{user}", member.mention).replace("{server}", guild.name)
    if "{roles}" in text:
        text = text.replace("{roles}", roles_text)
    elif roles_text:
        text += "\n\n" + roles_text

    embed = discord.Embed(
        title=rk["title"] or None,
        description=text[:4000] or None,
        color=discord.Color.blurple()
    )
    if rk["image"]:
        embed.set_image(url=rk["image"])
    th = rk["thumb"]
    if th == "avatar":
        embed.set_thumbnail(url=member.display_avatar.url)
    elif th:
        embed.set_thumbnail(url=th)
    if rk["footer"]:
        embed.set_footer(text=rk["footer"])
    return embed


async def rk_on_message(message):
    if message.author.bot or message.guild is None:
        return
    g = message.guild
    rk = get_rk(g.id)
    if not rk["enabled"] or not rk["channels"]:
        return
    ch = message.channel
    if ch.id not in rk["channels"] and getattr(ch, "parent_id", None) not in rk["channels"]:
        return
    trigger_text = (message.content or "").strip().casefold()
    content = message.content or ""
    invite = (rk.get("server_link") or "").strip()
    # Any message containing the word link / لینک (any case, with other words too) -> send the server link.
    # A message that already contains a real URL/invite is ignored.
    if invite and RK_LINK_WORD_RX.search(content) and not LINK_ANY_RX.search(content):
        if any(r.id in rk["blocked_roles"] for r in message.author.roles):
            return
        mute_role = get_mute_role(g)
        if mute_role and mute_role in message.author.roles:
            return
        parts = [x.strip() for x in (rk.get("link_before"), invite, rk.get("link_after")) if x and x.strip()]
        await rk_send_link(ch, parts)
        return  # no reply/reference: the link is sent as a normal new message
    if trigger_text not in {t.casefold() for t in rk["triggers"]}:
        return
    if any(r.id in rk["blocked_roles"] for r in message.author.roles):
        return
    mute_role = get_mute_role(g)
    if mute_role and mute_role in message.author.roles:
        return

    try:
        embed = rk_build_embed(g, message.author)
        if rk["reply"]:
            await message.reply(embed=embed, mention_author=False)
        else:
            await ch.send(embed=embed)
    except Exception as e:
        print(f"reklam error: {e}")


bot.add_listener(rk_on_message, "on_message")


def rk_embed(guild):
    rk = get_rk(guild.id)
    e = discord.Embed(
        title="📢 Reklam " + ("(ON)" if rk["enabled"] else "(OFF)"),
        color=discord.Color.green() if rk["enabled"] else discord.Color.red()
    )
    e.add_field(name="کەناڵەکان", value="\n".join(f"<#{c}>" for c in rk["channels"])[:1000] or "❌", inline=False)
    e.add_field(name="ڕۆڵەکانی تاگ (ناو بۆکسەکە)",
                value=" ".join(f"<@&{r}>" for r in rk["tag_roles"])[:1000] or "❌", inline=False)
    e.add_field(name="ڕۆڵە بلۆککراوەکان",
                value=" ".join(f"<@&{r}>" for r in rk["blocked_roles"])[:1000] or "❌", inline=False)
    e.add_field(name="وشەکانی Reklam", value=" , ".join(f"`{t}`" for t in rk["triggers"]), inline=False)
    e.add_field(name="Title", value=rk["title"] or "—")
    e.add_field(name="Image / GIF", value="✅" if rk["image"] else "❌")
    e.add_field(name="Link auto-send", value="✅" if rk.get("server_link") else "❌")
    e.add_field(name="Small image", value="avatar" if rk["thumb"] == "avatar" else ("✅" if rk["thumb"] else "❌"))
    e.set_footer(text="Edit Message ← دەق، ئیمۆجی، لینکی ڕەسم | {user} {roles} {server}")
    return e


class RkMessageModal(discord.ui.Modal):
    def __init__(self, guild, author_id):
        super().__init__(title="Reklam Message")
        self.guild, self.author_id = guild, author_id
        rk = get_rk(guild.id)
        self.title_in = discord.ui.TextInput(
            label="Title", default=rk["title"] or None, required=False, max_length=256)
        self.text_in = discord.ui.TextInput(
            label="Text ({user} {roles} {server})", style=discord.TextStyle.paragraph,
            default=rk["text"] or None, required=False, max_length=4000,
            placeholder="<a:white:123456> دەقەکەت لێرە بنووسە")
        self.image_in = discord.ui.TextInput(
            label="Image / GIF link", default=rk["image"] or None, required=False, max_length=500)
        self.thumb_in = discord.ui.TextInput(
            label="Small image (avatar = user avatar)", default=rk["thumb"] or None,
            required=False, max_length=500)
        self.footer_in = discord.ui.TextInput(
            label="Footer", default=rk["footer"] or None, required=False, max_length=200)
        for item in (self.title_in, self.text_in, self.image_in, self.thumb_in, self.footer_in):
            self.add_item(item)

    async def on_submit(self, interaction):
        image = self.image_in.value.strip()
        thumb = self.thumb_in.value.strip()
        if image and not image.lower().startswith(("http://", "https://")):
            await interaction.response.send_message("❌ لینکی ڕەسم دەبێت بە `https://` دەست پێبکات.", ephemeral=True)
            return
        if thumb and thumb.lower() != "avatar" and not thumb.lower().startswith(("http://", "https://")):
            await interaction.response.send_message("❌ Small image: `avatar` یان لینکی `https://`.", ephemeral=True)
            return
        rk = get_rk(self.guild.id)
        rk["title"] = self.title_in.value.strip() or None
        rk["text"] = self.text_in.value
        rk["image"] = image or None
        rk["thumb"] = "avatar" if thumb.lower() == "avatar" else (thumb or None)
        rk["footer"] = self.footer_in.value.strip() or None
        save_config()
        await panel_edit(interaction, self, "rk")


class RkTriggerModal(discord.ui.Modal):
    def __init__(self, guild, author_id):
        super().__init__(title="Reklam Words")
        self.guild, self.author_id = guild, author_id
        self.box = discord.ui.TextInput(
            label="وشەکان (بە کۆما جیا بکەرەوە)",
            default=", ".join(get_rk(guild.id)["triggers"]), max_length=300)
        self.add_item(self.box)

    async def on_submit(self, interaction):
        words = [w.strip().lower() for w in self.box.value.split(",") if w.strip()]
        if not words:
            await interaction.response.send_message("❌ لانیکەم یەک وشە بنووسە.", ephemeral=True)
            return
        get_rk(self.guild.id)["triggers"] = words
        save_config()
        await panel_edit(interaction, self, "rk")


class RkView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        rk = get_rk(guild.id)
        self.add_item(PanelChannelSelect("rk", row=0))
        self.add_item(PanelRoleSelect("rk", "tag_roles", "ڕۆڵەکانی تاگ (ناو بۆکسەکە)...", row=1))
        self.add_item(PanelRoleSelect("rk", "blocked_roles", "ڕۆڵە بلۆککراوەکان...", row=2))
        self.toggle.label = "Reklam: ON" if rk["enabled"] else "Reklam: OFF"
        self.toggle.style = discord.ButtonStyle.success if rk["enabled"] else discord.ButtonStyle.danger
        self.reply_btn.label = "Reply: " + ("ON" if rk["reply"] else "OFF")

    @discord.ui.button(label="Toggle", row=3)
    async def toggle(self, interaction, button):
        rk = get_rk(self.guild.id)
        rk["enabled"] = not rk["enabled"]
        save_config()
        await panel_edit(interaction, self, "rk")

    @discord.ui.button(label="Edit Message", style=discord.ButtonStyle.primary, row=3)
    async def edit_btn(self, interaction, button):
        await interaction.response.send_modal(RkMessageModal(self.guild, self.author_id))

    @discord.ui.button(label="Words", style=discord.ButtonStyle.secondary, row=3)
    async def words_btn(self, interaction, button):
        await interaction.response.send_modal(RkTriggerModal(self.guild, self.author_id))

    @discord.ui.button(label="Reply", style=discord.ButtonStyle.secondary, row=3)
    async def reply_btn(self, interaction, button):
        rk = get_rk(self.guild.id)
        rk["reply"] = not rk["reply"]
        save_config()
        await panel_edit(interaction, self, "rk")

    @discord.ui.button(label="Link", style=discord.ButtonStyle.primary, row=3)
    async def link_btn(self, interaction, button):
        await interaction.response.send_modal(ReklamLinkModal(self.guild))

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.success, row=4)
    async def preview_btn(self, interaction, button):
        try:
            await interaction.response.send_message(
                embed=rk_build_embed(self.guild, interaction.user), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="Clear Channels", style=discord.ButtonStyle.secondary, row=4)
    async def clear_ch(self, interaction, button):
        get_rk(self.guild.id)["channels"] = []
        save_config()
        await panel_edit(interaction, self, "rk")

    @discord.ui.button(label="Clear Tags", style=discord.ButtonStyle.secondary, row=4)
    async def clear_tags(self, interaction, button):
        get_rk(self.guild.id)["tag_roles"] = []
        save_config()
        await panel_edit(interaction, self, "rk")

    @discord.ui.button(label="Clear Blocked", style=discord.ButtonStyle.secondary, row=4)
    async def clear_blocked(self, interaction, button):
        get_rk(self.guild.id)["blocked_roles"] = []
        save_config()
        await panel_edit(interaction, self, "rk")


    @discord.ui.button(label="Partner ›", style=discord.ButtonStyle.primary, row=4)
    async def partner_btn(self, interaction, button):
        await interaction.response.edit_message(
            embed=rkp_embed(self.guild), view=RkPartnerView(self.guild, self.author_id))


@bot.tree.command(name="reklam", description="ڕێکخستنی نامەی Reklam")
@app_commands.guild_only()
async def reklam_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=rk_embed(interaction.guild),
        view=RkView(interaction.guild, interaction.user.id),
        ephemeral=True
    )


# =========================================================
# 35. PARTNER CHANNELS (لە /reklam ← Partner) + /blocklink
# =========================================================

LINK_ANY_RX = re.compile(r"https?://\S+|discord(?:app)?\.(?:gg|com/invite)/\S+|www\.\S+", re.I)


def chat_exempt(member):
    """Owner + Administrator + Developer roles are never touched by Partner / Blocklink."""
    try:
        return (member.id in (BOT_OWNER_ID, member.guild.owner_id)
                or member.guild_permissions.administrator
                or is_dev(member))
    except Exception:
        return False


def is_partner_channel(message):
    try:
        rk = get_rk(message.guild.id)
        if not rk["partner_enabled"]:
            return False
        ch = message.channel
        return ch.id in rk["partner_channels"] or getattr(ch, "parent_id", None) in rk["partner_channels"]
    except Exception:
        return False


def msg_has_attached_image(m):
    # Partner channel is link-only: reject every attachment/sticker, not just images.
    if getattr(m, "attachments", None) or getattr(m, "stickers", None):
        return True
    for snap in (getattr(m, "message_snapshots", None) or []):
        snap_msg = getattr(snap, "message", snap)
        if getattr(snap_msg, "attachments", None) or getattr(snap_msg, "stickers", None):
            return True
    return bool(IMG_LINK_RX.search(m.content or ""))


async def _delete_and_warn(message, text):
    try:
        await message.delete()
    except Exception:
        return
    try:
        await message.channel.send(f"{message.author.mention} ❌ {text}", delete_after=8)
    except Exception:
        pass


async def pt_check(message):
    if message.author.bot or message.guild is None:
        return
    if not is_partner_channel(message):
        return
    if msg_has_attached_image(message):
        await _delete_and_warn(message, "نابێت وێنە لێرە بنێریت.")
    elif not SEC_INVITE_RX.search(reklam_message_text(message) if "reklam_message_text" in globals() else (message.content or "")):
        await _delete_and_warn(
            message, "لێرە تەنها لینکی سێرڤەری Discord ڕێگەپێدراوە.")


async def pt_on_message(message):
    await pt_check(message)


async def pt_on_edit(before, after):
    await pt_check(after)


bot.add_listener(pt_on_message, "on_message")
bot.add_listener(pt_on_edit, "on_message_edit")


def rkp_embed(guild):
    rk = get_rk(guild.id)
    e = discord.Embed(
        title="🤝 Partner Channels " + ("(ON)" if rk["partner_enabled"] else "(OFF)"),
        description="\n".join(f"<#{c}>" for c in rk["partner_channels"])[:3000] or "❌ هیچ کەناڵێک دیاری نەکراوە",
        color=discord.Color.green() if rk["partner_enabled"] else discord.Color.red()
    )
    board_ch = (rk.get("counting") or {}).get("board_channel")
    e.add_field(name="📊 کەناڵی بۆردی Top 25",
                value=f"<#{board_ch}>" if board_ch else "❌ دیاری نەکراوە (لە هەمان چاتی ئێستا دەنێردرێت)",
                inline=False)
    e.set_footer(text="تەنها نامەی لەگەڵ لینکی سێرڤەر ڕێگەپێدراوە | وێنە قەدەغەیە | هەموو کەسێک دەژمێردرێت")
    return e


class RkBoardChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, row=2):
        super().__init__(
            placeholder="کەناڵی ناردنی بۆردی Top 25 هەڵبژێرە...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=1, row=row)

    async def callback(self, interaction):
        rk = get_rk(self.view.guild.id)
        rk.setdefault("counting", {})["board_channel"] = self.values[0].id
        save_config()
        await panel_edit(interaction, self.view, "rkp")


class RkPartnerView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        rk = get_rk(guild.id)
        self.add_item(PanelChannelSelect("rkp", row=0))
        self.add_item(RkBoardChannelSelect(row=2))
        self.toggle.label = "Partner: ON" if rk["partner_enabled"] else "Partner: OFF"
        self.toggle.style = discord.ButtonStyle.success if rk["partner_enabled"] else discord.ButtonStyle.danger

    @discord.ui.button(label="Toggle", row=1)
    async def toggle(self, interaction, button):
        rk = get_rk(self.guild.id)
        rk["partner_enabled"] = not rk["partner_enabled"]
        save_config()
        await panel_edit(interaction, self, "rkp")

    @discord.ui.button(label="Clear Channels", style=discord.ButtonStyle.secondary, row=1)
    async def clear_ch(self, interaction, button):
        get_rk(self.guild.id)["partner_channels"] = []
        save_config()
        await panel_edit(interaction, self, "rkp")

    @discord.ui.button(label="‹ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        await panel_edit(interaction, self, "rk")

    @discord.ui.button(label="Send Board", style=discord.ButtonStyle.success, row=3)
    async def send_board_btn(self, interaction, button):
        rk = get_rk(self.guild.id)
        target_id = (rk.get("counting") or {}).get("board_channel")
        target = self.guild.get_channel(int(target_id)) if target_id else None
        if target is None:
            target = interaction.channel
        try:
            embed = reklam_count_embed(self.guild)
            board = await target.send(embed=embed)
            reklam_count_db.setdefault("boards", []).append(
                {"g": self.guild.id, "c": target.id, "m": board.id})
            reklam_count_save()
            _reklam_board_state[board.id] = reklam_count_sig(embed)
            await interaction.response.send_message(
                f"✅ بۆردی Top 25 نێردرا بۆ {target.mention} و خۆکارانە نوێ دەبێتەوە.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ بۆتەکە مۆڵەتی Send Messages و Embed Links لەو کەناڵەدا نییە.", ephemeral=True)
        except Exception as ex:
            print(f"reklam board send error: {ex}", flush=True)
            await interaction.response.send_message("❌ نەتوانرا بۆردەکە بنێردرێت.", ephemeral=True)


# ---------------------------------------------------------
# /blocklink
# ---------------------------------------------------------

def get_bl(gid):
    b = cfg(gid).setdefault("blocklink", {})
    b.setdefault("enabled", True)
    b.setdefault("channels", [])
    return b


async def bl_check(message):
    if message.author.bot or message.guild is None:
        return
    if is_partner_channel(message):
        return
    b = get_bl(message.guild.id)
    if not b["enabled"] or not b["channels"]:
        return
    ch = message.channel
    if ch.id not in b["channels"] and getattr(ch, "parent_id", None) not in b["channels"]:
        return
    if chat_exempt(message.author):
        return
    if LINK_ANY_RX.search(message.content or ""):
        await _delete_and_warn(message, "ناتوانیت لینک لێرە دابنێیت.")


async def bl_on_message(message):
    await bl_check(message)


async def bl_on_edit(before, after):
    await bl_check(after)


bot.add_listener(bl_on_message, "on_message")
bot.add_listener(bl_on_edit, "on_message_edit")


def bl_embed(guild):
    b = get_bl(guild.id)
    e = discord.Embed(
        title="🚫 Block Link " + ("(ON)" if b["enabled"] else "(OFF)"),
        description="\n".join(f"<#{c}>" for c in b["channels"])[:3000] or "❌ هیچ کەناڵێک دیاری نەکراوە",
        color=discord.Color.green() if b["enabled"] else discord.Color.red()
    )
    e.set_footer(text="لەم کەناڵانە هەر لینکێک بنێردرێت نامەکە دەسڕدرێتەوە")
    return e


class BlView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        b = get_bl(guild.id)
        self.add_item(PanelChannelSelect("bl", row=0))
        self.toggle.label = "Block Link: ON" if b["enabled"] else "Block Link: OFF"
        self.toggle.style = discord.ButtonStyle.success if b["enabled"] else discord.ButtonStyle.danger

    @discord.ui.button(label="Toggle", row=1)
    async def toggle(self, interaction, button):
        b = get_bl(self.guild.id)
        b["enabled"] = not b["enabled"]
        save_config()
        await panel_edit(interaction, self, "bl")

    @discord.ui.button(label="Clear Channels", style=discord.ButtonStyle.secondary, row=1)
    async def clear_ch(self, interaction, button):
        get_bl(self.guild.id)["channels"] = []
        save_config()
        await panel_edit(interaction, self, "bl")


@bot.tree.command(name="blocklink", description="کەناڵەکانی قەدەغەکردنی لینک")
@app_commands.guild_only()
async def blocklink_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=bl_embed(interaction.guild),
        view=BlView(interaction.guild, interaction.user.id),
        ephemeral=True
    )


# =========================================================
# 36. VOICE MOVE (کێ موڤی کرد)
# =========================================================

_vc_move_seen = {}   # audit entry id -> count


async def find_voice_mover(guild, dest_id):
    """ئەگەر کەسێک (یان بۆتێک) ئەندامێکی موڤ کرد بۆ dest_id، ئەو کەسە دەگەڕێنێتەوە."""
    await asyncio.sleep(1.5)
    try:
        async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.member_move):
            count = int(getattr(entry.extra, "count", 1) or 1)
            ch = getattr(entry.extra, "channel", None)
            prev = _vc_move_seen.get(entry.id)
            _vc_move_seen[entry.id] = count
            if getattr(ch, "id", None) != dest_id:
                continue
            if prev is None:
                age = (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds()
                if age <= 15:
                    return entry.user
            elif count > prev:
                return entry.user
    except Exception:
        pass
    return None


async def vc_prime_move_cache():
    for g in bot.guilds:
        try:
            async for entry in g.audit_logs(limit=10, action=discord.AuditLogAction.member_move):
                _vc_move_seen[entry.id] = int(getattr(entry.extra, "count", 1) or 1)
        except Exception:
            pass


bot.add_listener(vc_prime_move_cache, "on_ready")


# =========================================================
# 37. /setstaff  (چەند ڕۆڵ بۆ Lady Staff و Boy Staff)
# =========================================================

def get_staff_cfg(gid):
    c = cfg(gid)
    if "staff_roles" not in c:
        # گواستنەوەی ڕۆڵە کۆنەکە (یەک ڕۆڵ) بۆ لیست
        c["staff_roles"] = {k: ([c["roles"][k]] if c["roles"].get(k) else []) for k in STAFF_LABELS}
    for k in STAFF_LABELS:
        c["staff_roles"].setdefault(k, [])
    return c["staff_roles"]


def get_staff_roles(gid, slot):
    return get_staff_cfg(gid)[slot]


def staff_embed(guild):
    e = discord.Embed(title="👮 Staff Roles", color=discord.Color.blurple())
    for slot, label in STAFF_LABELS.items():
        roles = " ".join(f"<@&{r}>" for r in get_staff_roles(guild.id, slot)) or "❌"
        e.add_field(name=label, value=roles[:1000], inline=False)
    e.set_footer(text="ڕۆڵەکان هەڵبژێرە، لیستی پێشوو دەگۆڕێت | /staff هەموو ڕۆڵەکان دەدات")
    return e


class StaffRoleSelect(discord.ui.RoleSelect):
    def __init__(self, slot, row):
        super().__init__(
            placeholder=f"{STAFF_LABELS[slot]} — ڕۆڵەکان هەڵبژێرە (چەند ڕۆڵ)...",
            min_values=1, max_values=25, row=row
        )
        self.slot = slot

    async def callback(self, interaction):
        g = self.view.guild
        get_staff_cfg(g.id)[self.slot] = [r.id for r in self.values]
        save_config()
        await interaction.response.edit_message(
            embed=staff_embed(g), view=StaffView(g, self.view.author_id))


class StaffView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        self.add_item(StaffRoleSelect("staff1", 0))
        self.add_item(StaffRoleSelect("staff2", 1))

    @discord.ui.button(label="Clear Lady Staff", style=discord.ButtonStyle.secondary, row=2)
    async def clear1(self, interaction, button):
        get_staff_cfg(self.guild.id)["staff1"] = []
        save_config()
        await interaction.response.edit_message(
            embed=staff_embed(self.guild), view=StaffView(self.guild, self.author_id))

    @discord.ui.button(label="Clear Boy Staff", style=discord.ButtonStyle.secondary, row=2)
    async def clear2(self, interaction, button):
        get_staff_cfg(self.guild.id)["staff2"] = []
        save_config()
        await interaction.response.edit_message(
            embed=staff_embed(self.guild), view=StaffView(self.guild, self.author_id))


@bot.tree.command(name="setstaff", description="دیاریکردنی ڕۆڵەکانی Lady Staff و Boy Staff بۆ /staff")
@app_commands.guild_only()
async def setstaff(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=staff_embed(interaction.guild),
        view=StaffView(interaction.guild, interaction.user.id),
        ephemeral=True
    )


# =========================================================
# 38. PERMISSION ROLE PANELS (مەڵتی ڕۆڵ بە یەکجار)
#     /rolemute /roleban /rolesafika /rolestaff /regri-roles
#     /regadan-ranggorin /setdev
# =========================================================

PERM_PANEL_LABELS = {
    "mute": "Mute",
    "ban": "Ban (Bfra / Unban)",
    "safika": "Safika (Clear)",
    "staff": "Staff (/staff)",
    "regri": "Regri (/regri)",
    "color": "Color (/rangi-role)",
    "dev": "Developer",
    "auto": "Autorole",
}


BL_KEYS = ("mute", "ban", "safika", "staff", "regri", "color")


def perm_list(gid, key):
    c = cfg(gid)
    if key in PERM_LABELS:
        return c["perm_roles"][key]
    return {
        "regri": c["regri_roles"], "color": c["color_roles"],
        "dev": c["dev_roles"], "auto": c["autoroles"],
    }[key]


def perm_embed(guild, key):
    c = cfg(guild.id)
    roles = " ".join(f"<@&{r}>" for r in perm_list(guild.id, key)) or "❌"
    e = discord.Embed(
        title=f"🔑 {PERM_PANEL_LABELS[key]} — ڕۆڵەکان",
        description=roles[:3500],
        color=discord.Color.blurple()
    )
    if key == "color":
        users = " ".join(f"<@{u}>" for u in c["color_users"]) or "❌"
        e.add_field(name="کەسەکان", value=users[:1000], inline=False)
    if key in BL_KEYS:
        bl = " ".join(f"<@{u}>" for u in blacklist_list(guild.id, key)) or "❌"
        e.add_field(name="🚫 Blacklist", value=bl[:1000], inline=False)
        e.set_footer(text="ڕۆڵەکان: هەڵبژاردنی نوێ لیستی پێشوو دەگۆڕێت | Blacklist: کەسێک هەڵبژێریت زیاد دەبێت، ئەگەر پێشتر هەبێت لادەچێت")
    else:
        e.set_footer(text="هەڵبژاردنی نوێ لیستی پێشوو دەگۆڕێت")
    return e


def perm_allowed(member, key):
    if key == "dev":
        return member.id in (BOT_OWNER_ID, member.guild.owner_id)
    return is_dev(member)


class PermRolesSelect(discord.ui.RoleSelect):
    def __init__(self, key):
        super().__init__(placeholder="ڕۆڵەکان هەڵبژێرە (چەند ڕۆڵ)...", min_values=1, max_values=25, row=0)
        self.key = key

    async def callback(self, interaction):
        g = self.view.guild
        perm_list(g.id, self.key)[:] = [r.id for r in self.values]
        save_config()
        await interaction.response.edit_message(
            embed=perm_embed(g, self.key), view=PermRolesView(g, self.view.author_id, self.key))


class PermUsersSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="کەسەکان هەڵبژێرە...", min_values=1, max_values=25, row=1)

    async def callback(self, interaction):
        g = self.view.guild
        cfg(g.id)["color_users"][:] = [u.id for u in self.values]
        save_config()
        await interaction.response.edit_message(
            embed=perm_embed(g, "color"), view=PermRolesView(g, self.view.author_id, "color"))


class PermBlacklistSelect(discord.ui.UserSelect):
    def __init__(self, key):
        super().__init__(
            placeholder="🚫 Blacklist — کەس هەڵبژێرە (زیاد / لابردن)...",
            min_values=1, max_values=25, row=2 if key == "color" else 1)
        self.key = key

    async def callback(self, interaction):
        g = self.view.guild
        _toggle_ids(blacklist_list(g.id, self.key), [u.id for u in self.values])
        save_config()
        await interaction.response.edit_message(
            embed=perm_embed(g, self.key), view=PermRolesView(g, self.view.author_id, self.key))


class PermRolesView(SecBaseView):
    def __init__(self, guild, author_id, key):
        super().__init__(guild, author_id)
        self.key = key
        self.add_item(PermRolesSelect(key))
        if key == "color":
            self.add_item(PermUsersSelect())
        else:
            self.remove_item(self.clear_users)
        if key in BL_KEYS:
            self.add_item(PermBlacklistSelect(key))
        else:
            self.remove_item(self.clear_bl)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id or not perm_allowed(interaction.user, self.key):
            await deny_interaction(interaction)
            return False
        return True

    async def _refresh(self, interaction):
        await interaction.response.edit_message(
            embed=perm_embed(self.guild, self.key), view=PermRolesView(self.guild, self.author_id, self.key))

    @discord.ui.button(label="Clear Roles", style=discord.ButtonStyle.secondary, row=3)
    async def clear_roles(self, interaction, button):
        perm_list(self.guild.id, self.key)[:] = []
        save_config()
        await self._refresh(interaction)

    @discord.ui.button(label="Clear Users", style=discord.ButtonStyle.secondary, row=3)
    async def clear_users(self, interaction, button):
        cfg(self.guild.id)["color_users"][:] = []
        save_config()
        await self._refresh(interaction)

    @discord.ui.button(label="Clear Blacklist", style=discord.ButtonStyle.danger, row=3)
    async def clear_bl(self, interaction, button):
        blacklist_list(self.guild.id, self.key)[:] = []
        save_config()
        await self._refresh(interaction)


async def open_perm_panel(interaction, key):
    if not perm_allowed(interaction.user, key):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=perm_embed(interaction.guild, key),
        view=PermRolesView(interaction.guild, interaction.user.id, key),
        ephemeral=True
    )


@bot.tree.command(name="rolemute", description="ئەو ڕۆڵانەی دەتوانن Mute بکەن")
@app_commands.guild_only()
async def rolemute(interaction: discord.Interaction):
    await open_perm_panel(interaction, "mute")


@bot.tree.command(name="roleban", description="ئەو ڕۆڵانەی دەتوانن Bfra / Unban بکەن")
@app_commands.guild_only()
async def roleban(interaction: discord.Interaction):
    await open_perm_panel(interaction, "ban")


@bot.tree.command(name="rolesafika", description="ئەو ڕۆڵانەی دەتوانن Safika (کلێر) بکەن")
@app_commands.guild_only()
async def rolesafika(interaction: discord.Interaction):
    await open_perm_panel(interaction, "safika")


@bot.tree.command(name="rolestaff", description="ئەو ڕۆڵانەی دەتوانن /staff بەکاربهێنن")
@app_commands.guild_only()
async def rolestaff(interaction: discord.Interaction):
    await open_perm_panel(interaction, "staff")


@bot.tree.command(name="regri-roles", description="ئەو ڕۆڵانەی دەتوانن /regri بەکاربهێنن")
@app_commands.guild_only()
async def regri_roles(interaction: discord.Interaction):
    await open_perm_panel(interaction, "regri")


@bot.tree.command(name="regadan-ranggorin", description="ڕۆڵ و کەسانی ڕێگەپێدراو بۆ گۆڕینی ڕەنگی ڕۆڵ")
@app_commands.guild_only()
async def regadan_ranggorin(interaction: discord.Interaction):
    await open_perm_panel(interaction, "color")


@bot.tree.command(name="setdev", description="ڕۆڵەکانی دیڤیلۆپەر (تەنها خاوەنی سێرڤەر)")
@app_commands.guild_only()
async def setdev(interaction: discord.Interaction):
    await open_perm_panel(interaction, "dev")


# =========================================================
# 39. COUNTING  (/counting)
# =========================================================

def get_ct(gid):
    b = cfg(gid).setdefault("counting", {})
    b.setdefault("enabled", True)
    b.setdefault("channel", None)
    b.setdefault("last", 0)            # کۆتا ژمارەی ڕاست
    b.setdefault("last_user", None)
    b.setdefault("delete_text", False)  # نامەی نا-ژمارە بسڕدرێتەوە؟
    b.setdefault("no_double", False)    # یەک کەس دوو جار لەسەر یەک نەنووسێت؟
    return b


def ct_embed(guild):
    b = get_ct(guild.id)
    e = discord.Embed(
        title="🔢 Counting " + ("(ON)" if b["enabled"] else "(OFF)"),
        color=discord.Color.green() if b["enabled"] else discord.Color.red()
    )
    e.add_field(name="کەناڵ", value=f"<#{b['channel']}>" if b["channel"] else "❌", inline=False)
    e.add_field(name="کۆتا ژمارە", value=f"`{b['last']}`")
    e.add_field(name="ژمارەی داهاتوو", value=f"`{b['last'] + 1}`")
    e.add_field(name="نامەی نا-ژمارە دەسڕدرێتەوە", value="✅" if b["delete_text"] else "❌", inline=False)
    e.add_field(name="دوو جار لەسەر یەک قەدەغەیە", value="✅" if b["no_double"] else "❌", inline=False)
    return e


async def ct_on_message(message):
    if message.author.bot or message.guild is None:
        return
    b = get_ct(message.guild.id)
    if not b["enabled"] or not b["channel"] or message.channel.id != b["channel"]:
        return

    text = (message.content or "").strip()
    num = int(text) if (text.isdecimal() and len(text) <= 18) else None

    if num is None:
        if b["delete_text"]:
            await _delete_and_warn(message, "لێرە تەنها ژمارە ڕێگەپێدراوە.")
        return

    double = b["no_double"] and b["last_user"] == message.author.id
    if num == b["last"] + 1 and not double:
        # یەکسەر state نوێ دەکرێتەوە، بۆ ئەوەی دوو کەس بە یەک ژمارە نەنووسن
        b["last"] = num
        b["last_user"] = message.author.id
        save_config()
        return

    if double:
        await _delete_and_warn(message, "ناتوانیت دوو جار لەسەر یەک ژمارە بنووسیت.")
    else:
        await _delete_and_warn(
            message, "ناتوانیت ژمارەی کەم یان زیاد لە ئاستی ژمارەکەی ئێستا دابنێیت.")


bot.add_listener(ct_on_message, "on_message")


class CountChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="کەناڵی Counting هەڵبژێرە...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=1, row=0
        )

    async def callback(self, interaction):
        g = self.view.guild
        get_ct(g.id)["channel"] = self.values[0].id
        save_config()
        await interaction.response.edit_message(
            embed=ct_embed(g), view=CountView(g, self.view.author_id))


class CountNumberModal(discord.ui.Modal):
    def __init__(self, guild, author_id):
        super().__init__(title="Set Last Number")
        self.guild, self.author_id = guild, author_id
        self.num = discord.ui.TextInput(
            label="کۆتا ژمارەی نێردراو", default=str(get_ct(guild.id)["last"]), max_length=18)
        self.add_item(self.num)

    async def on_submit(self, interaction):
        v = self.num.value.strip()
        if not v.isdecimal():
            await interaction.response.send_message("❌ تەنها ژمارە بنووسە.", ephemeral=True)
            return
        b = get_ct(self.guild.id)
        b["last"] = int(v)
        b["last_user"] = None
        save_config()
        await interaction.response.edit_message(
            embed=ct_embed(self.guild), view=CountView(self.guild, self.author_id))


class CountView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        b = get_ct(guild.id)
        self.add_item(CountChannelSelect())
        self.toggle.label = "Counting: ON" if b["enabled"] else "Counting: OFF"
        self.toggle.style = discord.ButtonStyle.success if b["enabled"] else discord.ButtonStyle.danger
        self.text_btn.label = "Delete Text: " + ("ON" if b["delete_text"] else "OFF")
        self.double_btn.label = "No Double: " + ("ON" if b["no_double"] else "OFF")

    async def _refresh(self, interaction):
        await interaction.response.edit_message(
            embed=ct_embed(self.guild), view=CountView(self.guild, self.author_id))

    @discord.ui.button(label="Toggle", row=1)
    async def toggle(self, interaction, button):
        b = get_ct(self.guild.id)
        b["enabled"] = not b["enabled"]
        save_config()
        await self._refresh(interaction)

    @discord.ui.button(label="Set Last Number", style=discord.ButtonStyle.primary, row=1)
    async def number_btn(self, interaction, button):
        await interaction.response.send_modal(CountNumberModal(self.guild, self.author_id))

    @discord.ui.button(label="Delete Text", style=discord.ButtonStyle.secondary, row=2)
    async def text_btn(self, interaction, button):
        b = get_ct(self.guild.id)
        b["delete_text"] = not b["delete_text"]
        save_config()
        await self._refresh(interaction)

    @discord.ui.button(label="No Double", style=discord.ButtonStyle.secondary, row=2)
    async def double_btn(self, interaction, button):
        b = get_ct(self.guild.id)
        b["no_double"] = not b["no_double"]
        save_config()
        await self._refresh(interaction)

    @discord.ui.button(label="Clear Channel", style=discord.ButtonStyle.secondary, row=2)
    async def clear_ch(self, interaction, button):
        get_ct(self.guild.id)["channel"] = None
        save_config()
        await self._refresh(interaction)


@bot.tree.command(name="counting", description="کەناڵی ژماردن (Counting)")
@app_commands.guild_only()
async def counting_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=ct_embed(interaction.guild),
        view=CountView(interaction.guild, interaction.user.id),
        ephemeral=True
    )


# =========================================================
# 40. SECURITY: وایت لیستی تایبەت بە هەر بەشێک
# =========================================================

SEC_MSG_MODULES = {"spam", "mention", "invite", "link"}


def sec_mod_exempt(guild, uid, key, channel=None):
    """وایت لیستی ئەم بەشە: کەس / ڕۆڵ / کەناڵ (یان کاتێگۆری ناو کەناڵ)"""
    try:
        m = get_sec(guild.id)["modules"][key]
        if uid in m["wl_users"]:
            return True
        if channel is not None and m["wl_channels"]:
            ids = {getattr(channel, "id", None),
                   getattr(channel, "parent_id", None),
                   getattr(channel, "category_id", None)}
            if any(i in m["wl_channels"] for i in ids if i is not None):
                return True
        mem = guild.get_member(uid)
        if mem and any(r.id in m["wl_roles"] for r in mem.roles):
            return True
    except Exception:
        pass
    return False


def secmod_wl_embed(guild, key):
    m = get_sec(guild.id)["modules"][key]
    us = " ".join(f"<@{u}>" for u in m["wl_users"]) or "—"
    rs = " ".join(f"<@&{r}>" for r in m["wl_roles"]) or "—"
    desc = f"**Users:** {us}\n**Roles:** {rs}"
    if key in SEC_MSG_MODULES:
        chs = " ".join(f"<#{c}>" for c in m["wl_channels"]) or "—"
        desc += f"\n**Channels / Categories:** {chs}"
    desc += (
        "\n\nئەوەی هەڵیدەبژێریت: ئەگەر لە لیستدا بێت لادەچێت، ئەگەر نەبێت زیاد دەبێت.\n"
        "ئەم وایت لیستە تەنها بۆ ئەم بەشەیە. Owner، Developer و Whitelist ی گشتی هەمیشە ڕزگارن."
    )
    return discord.Embed(
        title=f"✅ Whitelist — {SEC_MODULES[key][0]}",
        description=desc[:4000],
        color=discord.Color.blurple()
    )


def _toggle_ids(lst, items):
    for i in items:
        if i in lst:
            lst.remove(i)
        else:
            lst.append(i)


class SecModWLUsers(discord.ui.UserSelect):
    def __init__(self, key):
        super().__init__(placeholder="Users", min_values=1, max_values=10, row=0)
        self.key = key

    async def callback(self, interaction):
        g = self.view.guild
        _toggle_ids(get_sec(g.id)["modules"][self.key]["wl_users"], [u.id for u in self.values])
        save_config()
        await interaction.response.edit_message(
            embed=secmod_wl_embed(g, self.key), view=SecModWLView(g, self.view.author_id, self.key))


class SecModWLRoles(discord.ui.RoleSelect):
    def __init__(self, key):
        super().__init__(placeholder="Roles", min_values=1, max_values=10, row=1)
        self.key = key

    async def callback(self, interaction):
        g = self.view.guild
        _toggle_ids(get_sec(g.id)["modules"][self.key]["wl_roles"], [r.id for r in self.values])
        save_config()
        await interaction.response.edit_message(
            embed=secmod_wl_embed(g, self.key), view=SecModWLView(g, self.view.author_id, self.key))


class SecModWLChannels(discord.ui.ChannelSelect):
    def __init__(self, key):
        super().__init__(
            placeholder="Channels / Categories (سپام لەوێ ئاساییە)",
            channel_types=[
                discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.voice,
                discord.ChannelType.stage_voice, discord.ChannelType.forum, discord.ChannelType.category,
            ],
            min_values=1, max_values=25, row=2
        )
        self.key = key

    async def callback(self, interaction):
        g = self.view.guild
        _toggle_ids(get_sec(g.id)["modules"][self.key]["wl_channels"], [c.id for c in self.values])
        save_config()
        await interaction.response.edit_message(
            embed=secmod_wl_embed(g, self.key), view=SecModWLView(g, self.view.author_id, self.key))


class SecModWLView(SecBaseView):
    def __init__(self, guild, author_id, key):
        super().__init__(guild, author_id)
        self.key = key
        self.add_item(SecModWLUsers(key))
        self.add_item(SecModWLRoles(key))
        if key in SEC_MSG_MODULES:
            self.add_item(SecModWLChannels(key))

    @discord.ui.button(label="Clear All", style=discord.ButtonStyle.danger, row=3)
    async def clear_all(self, interaction, button):
        m = get_sec(self.guild.id)["modules"][self.key]
        m["wl_users"], m["wl_roles"], m["wl_channels"] = [], [], []
        save_config()
        await interaction.response.edit_message(
            embed=secmod_wl_embed(self.guild, self.key),
            view=SecModWLView(self.guild, self.author_id, self.key))

    @discord.ui.button(label="‹ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=sec_module_embed(self.guild, self.key),
            view=SecModuleView(self.guild, self.author_id, self.key))


# =========================================================
# 41. /welcome  (چەند کەناڵ بۆ بەخێرهاتن)
# =========================================================

def get_welcome_channels(gid):
    c = cfg(gid)
    if "welcome_channels" not in c:
        old = c["channels"].get("welcome")
        c["welcome_channels"] = [old] if old else []
    return c["welcome_channels"]


def build_welcome_embed(member):
    c = cfg(member.guild.id)
    text = c["welcome_text"].replace("{server}", member.guild.name)
    embed = discord.Embed(title="WELCOME", description=f"{member.mention}\n{text}")
    embed.set_thumbnail(url=member.display_avatar.url)
    if c.get("welcome_image"):
        embed.set_image(url=c["welcome_image"])
    return embed


def welcome_panel_embed(guild):
    c = cfg(guild.id)
    chans = "\n".join(f"<#{x}>" for x in get_welcome_channels(guild.id)) or "❌"
    e = discord.Embed(title="👋 Welcome", color=discord.Color.blurple())
    e.add_field(name="کەناڵەکان", value=chans[:1000], inline=False)
    e.add_field(name="دەق", value=(c["welcome_text"] or "—")[:1000], inline=False)
    e.add_field(name="Image / GIF", value=c.get("welcome_image") or "❌", inline=False)
    e.set_footer(text="چەند کەناڵ هەڵبژێریت، لیستی پێشوو دەگۆڕێت | {server} = ناوی سێرڤەر")
    return e


def welcome_sync(gid):
    """کەناڵی یەکەم لە channels["welcome"] هەڵدەگیرێت بۆ ئەوەی ڕێکخستنە کۆنەکان نەشکێن"""
    lst = get_welcome_channels(gid)
    cfg(gid)["channels"]["welcome"] = lst[0] if lst else None


class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="کەناڵەکانی بەخێرهاتن هەڵبژێرە (چەند کەناڵ)...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=25, row=0
        )

    async def callback(self, interaction):
        g = self.view.guild
        get_welcome_channels(g.id)[:] = [c.id for c in self.values]
        welcome_sync(g.id)
        save_config()
        await interaction.response.edit_message(
            embed=welcome_panel_embed(g), view=WelcomeView(g, self.view.author_id))


class WelcomeModal(discord.ui.Modal):
    def __init__(self, guild, author_id):
        super().__init__(title="Welcome Message")
        self.guild, self.author_id = guild, author_id
        c = cfg(guild.id)
        self.text_in = discord.ui.TextInput(
            label="دەق ({server} = ناوی سێرڤەر)", style=discord.TextStyle.paragraph,
            default=c["welcome_text"] or None, required=False, max_length=1500)
        self.image_in = discord.ui.TextInput(
            label="Image / GIF link (بەتاڵ = لابردن)", default=c.get("welcome_image") or None,
            required=False, max_length=500)
        self.add_item(self.text_in)
        self.add_item(self.image_in)

    async def on_submit(self, interaction):
        img = self.image_in.value.strip()
        if img and not img.lower().startswith(("http://", "https://")):
            await interaction.response.send_message(
                "❌ لینکی ڕەسم/گیف دەبێت بە `https://` دەست پێبکات.", ephemeral=True)
            return
        c = cfg(self.guild.id)
        if self.text_in.value.strip():
            c["welcome_text"] = self.text_in.value
        c["welcome_image"] = img or None
        save_config()
        await interaction.response.edit_message(
            embed=welcome_panel_embed(self.guild), view=WelcomeView(self.guild, self.author_id))


class WelcomeView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        self.add_item(WelcomeChannelSelect())

    @discord.ui.button(label="Edit Message", style=discord.ButtonStyle.primary, row=1)
    async def edit_btn(self, interaction, button):
        await interaction.response.send_modal(WelcomeModal(self.guild, self.author_id))

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.success, row=1)
    async def preview_btn(self, interaction, button):
        await interaction.response.send_message(
            embed=build_welcome_embed(interaction.user), ephemeral=True)

    @discord.ui.button(label="Clear Channels", style=discord.ButtonStyle.secondary, row=1)
    async def clear_btn(self, interaction, button):
        get_welcome_channels(self.guild.id)[:] = []
        welcome_sync(self.guild.id)
        save_config()
        await interaction.response.edit_message(
            embed=welcome_panel_embed(self.guild), view=WelcomeView(self.guild, self.author_id))


@bot.tree.command(name="welcome", description="کەناڵەکانی بەخێرهاتن (چەند کەناڵ)")
@app_commands.guild_only()
async def welcome_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=welcome_panel_embed(interaction.guild),
        view=WelcomeView(interaction.guild, interaction.user.id),
        ephemeral=True
    )


# =========================================================
# 29b. XP SYSTEM  (/xp  +  /setxp)
# =========================================================
# - XP دەدرێت بۆ نامەی چات و کاتی ڤۆیس
# - ڕۆژانە / هەفتانە / مانگانە / ساڵانە (بە کاتی عێراق UTC+3)
# - /xp  → جۆر (چات/ڤۆیس) → ماوە → بۆردێکی پەبلیک دەنێرێت و خۆکار نوێ دەبێتەوە
# - /setxp → کێ و لە کوێ بتوانێت /xp بەکاربهێنێت + Blacklist
# - داتاکە لە xp_data.json هەڵدەگیرێت (لە تەنیشت guild_config.json)

import atexit as _atexit
import signal as _signal
import datetime as _dt
from discord.ext import tasks as _tasks

# ---- ڕێکخستنەکان (دەتوانیت ژمارەکان بگۆڕیت) ----
XP_TZ = _dt.timezone(_dt.timedelta(hours=3))   # کاتی عێراق
XP_CHAT_MIN, XP_CHAT_MAX = 8, 14               # XP بۆ هەر نامەیەک
XP_CHAT_COOLDOWN = 8                           # چرکە: لە ماوەی ئەمەدا نامەی دووەم XP نادات (دژی سپام)
XP_VOICE_PER_SEC = 1                           # XP بۆ هەر چرکەیەک لە ڤۆیس
XP_VOICE_DEAF_MULT = 0.7                       # ئەگەر deaf بوو چەند XP وەربگرێت (0.7 = 70% | 1 = وەک ئاسایی | 0 = هیچ)
XP_VOICE_SKIP_AFK = True                      # True = چەناڵی AFK ی سێرڤەر XP نادات | False = ئەویش XP بدات
XP_VOICE_MIN_HUMANS = 1                       # کەمترین ژمارەی کەس لە ڤۆیس (2 = تەنیا نابێت XP وەربگرێت)
XP_TOP = 30                                    # چەند کەس لە بۆردەکە
XP_REFRESH = 1.0                               # هەر چەند چرکە بۆردەکە نوێ بکرێتەوە (1 = کەمترین ڕێگەپێدراو لەلایەن Discord)
XP_SAVE_EVERY = 15                             # هەر چەند چرکە داتا لەسەر دیسک هەڵبگیرێت
XP_MAX_BOARDS_PER_GUILD = 12

XP_FILE = os.path.join(os.path.dirname(CONFIG_FILE) or ".", "xp_data.json")

XP_TYPES = {
    "chat": ("چات", "💬"),
    "voice": ("ڤۆیس", "🎙️"),
}
XP_PERIODS = {
    "d": "ڕۆژانە",
    "w": "هەفتانە",
    "m": "مانگانە",
    "y": "ساڵانە",
}
XP_KEEP = {"d": 45, "w": 20, "m": 26, "y": 10}   # چەند ماوەی کۆن هەڵبگیرێت

try:
    with open(XP_FILE, "r", encoding="utf-8") as f:
        xp_db = json.load(f)
except Exception:
    xp_db = {}
xp_db.setdefault("users", {})    # users[guild][kind][period][period_key][user_id] = xp
xp_db.setdefault("boards", [])   # [{"g","c","m","k","p"}]

_xp_dirty = False
_xp_board_state = {}             # message_id -> {"sig", "busy", "fails"}
_xp_chat_last = {}
_xp_tasks = set()                # نیشاندەری task ـەکان تا garbage collect نەکرێن


# ---------- داتا ----------

def xp_period_keys(now=None):
    now = now or _dt.datetime.now(XP_TZ)
    iso = now.isocalendar()
    return {
        "d": now.strftime("%Y-%m-%d"),
        "w": f"{iso[0]}-W{iso[1]:02d}",
        "m": now.strftime("%Y-%m"),
        "y": now.strftime("%Y"),
    }


def xp_add(gid, uid, kind, amount, keys):
    global _xp_dirty
    g = xp_db["users"].setdefault(str(gid), {}).setdefault(kind, {})
    u = str(uid)
    for p, k in keys.items():
        bucket = g.setdefault(p, {}).setdefault(k, {})
        bucket[u] = bucket.get(u, 0.0) + amount
    _xp_dirty = True


def xp_bucket(gid, kind, period):
    k = xp_period_keys()[period]
    return xp_db["users"].get(str(gid), {}).get(kind, {}).get(period, {}).get(k, {})


def xp_prune():
    for g in xp_db["users"].values():
        for kind in g.values():
            for p, buckets in kind.items():
                keep = XP_KEEP.get(p, 10)
                for old in sorted(buckets.keys())[:-keep]:
                    buckets.pop(old, None)


def xp_save_now():
    global _xp_dirty
    try:
        xp_prune()
        tmp = XP_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(xp_db, f, ensure_ascii=False)
        os.replace(tmp, XP_FILE)
        _xp_dirty = False
    except Exception as e:
        print(f"xp save error: {e}", flush=True)


_atexit.register(xp_save_now)


def _xp_on_sigterm(*_):
    xp_save_now()
    raise SystemExit(0)


try:
    _signal.signal(_signal.SIGTERM, _xp_on_sigterm)
except Exception:
    pass


# ---------- وەرگرتنی XP ----------

async def xp_on_message(message):
    if message.author.bot or message.guild is None:
        return
    try:
        mute_role = get_mute_role(message.guild)
        if mute_role and mute_role in message.author.roles:
            return
    except Exception:
        pass
    now = time.time()
    key = (message.guild.id, message.author.id)
    if now - _xp_chat_last.get(key, 0) < XP_CHAT_COOLDOWN:
        return
    _xp_chat_last[key] = now
    xp_add(message.guild.id, message.author.id, "chat",
           random.randint(XP_CHAT_MIN, XP_CHAT_MAX), xp_period_keys())


bot.add_listener(xp_on_message, "on_message")


@_tasks.loop(seconds=1)
async def xp_voice_loop():
    try:
        keys = xp_period_keys()
        per_sec = XP_VOICE_PER_SEC
        for guild in bot.guilds:
            afk = guild.afk_channel if XP_VOICE_SKIP_AFK else None
            for vc in list(guild.voice_channels) + list(guild.stage_channels):
                if afk and vc.id == afk.id:
                    continue
                humans = [m for m in vc.members if not m.bot]
                if len(humans) < XP_VOICE_MIN_HUMANS:
                    continue
                for m in humans:
                    vs = m.voice
                    if vs is None:
                        continue
                    amount = per_sec
                    if vs.self_deaf or vs.deaf:
                        amount *= XP_VOICE_DEAF_MULT
                    xp_add(guild.id, m.id, "voice", amount, keys)
                    xp_add(guild.id, m.id, "voice_time", 1, keys)   # کاتی ڤۆیس بە چرکە (deaf یش دەژمێردرێت)
    except Exception as e:
        print(f"xp voice loop error: {e}", flush=True)


@_tasks.loop(seconds=XP_SAVE_EVERY)
async def xp_save_loop():
    if _xp_dirty:
        xp_save_now()


# ---------- بۆردی XP ----------

def xp_top(guild, kind, period):
    bucket = xp_bucket(guild.id, kind, period)
    out = []
    for uid, val in sorted(bucket.items(), key=lambda kv: kv[1], reverse=True):
        if int(val) <= 0:
            continue
        m = guild.get_member(int(uid))
        if m is None:
            continue
        secs = None
        if kind == "voice":
            secs = xp_bucket(guild.id, "voice_time", period).get(uid, 0)
        out.append((m, int(val), secs))
        if len(out) >= XP_TOP:
            break
    return out


def xp_fmt_time(secs):
    """11 کاتژمێر و 30 خولەک -> 11:30"""
    mins = int(secs) // 60
    return f"{mins // 60}:{mins % 60:02d}"


def xp_board_embed(guild, kind, period):
    label, emoji = XP_TYPES[kind]
    plabel = XP_PERIODS[period]
    rows = xp_top(guild, kind, period)

    lines = [f"✧･ﾟ:  {plabel}  :･ﾟ✧", ""]
    if not rows:
        lines.append("هێشتا کەس XP ی نییە ♡")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (m, v, secs) in enumerate(rows, 1):
        name = discord.utils.escape_markdown(m.display_name)[: (12 if secs is not None else 20)]
        # کاتی ڤۆیس ڕێک لە تەنیشت XP، لە هەمان ڕیز: XP ✦ ⏱ `کات`
        tail = f" ✦ `{xp_fmt_time(secs)}`" if secs is not None else " ✦"
        if i <= 3:
            xp_txt = f"{v:,}" if secs is not None else f"**{v:,}**"
            lines.append(f"{medals[i]} **{name}** ⋆ {xp_txt}{tail}")
            if i == 3 and len(rows) > 3:
                lines.append("┈┈┈┈┈┈┈┈┈┈┈┈")
        else:
            lines.append(f"`{i:02d}` {name} ⋅ {v:,}{tail}")

    e = discord.Embed(
        title=f"{emoji}  {label} XP  ♡  Top {XP_TOP}",
        description="\n".join(lines)[:4000],
        color=discord.Color.from_rgb(244, 208, 238),   # pastel pink-lilac
    )
    foot = "⟡ نوێ دەبێتەوە هەر چرکەیەک ⟡"
    if kind == "voice":
        foot += "\nکات = کاتژمێر:خولەک لە ڤۆیس"
    e.set_footer(text=foot, icon_url=guild.icon.url if guild.icon else None)
    return e


def _xp_sig(embed):
    return json.dumps(embed.to_dict(), sort_keys=True, ensure_ascii=False)


def xp_remove_board(b):
    try:
        xp_db["boards"].remove(b)
    except ValueError:
        pass
    _xp_board_state.pop(b["m"], None)
    xp_save_now()


async def xp_delete_board_message(b):
    try:
        await bot.get_partial_messageable(b["c"]).get_partial_message(b["m"]).delete()
    except Exception:
        pass


async def xp_edit_board(b, st, embed, sig):
    try:
        pm = bot.get_partial_messageable(b["c"]).get_partial_message(b["m"])
        t0 = time.time()
        await pm.edit(embed=embed)
        took = time.time() - t0
        st["sig"] = sig
        st["fails"] = 0
        # لۆگی دواکەوتن: ئەگەر Discord هێواش بوو یان Rate Limit بوو لە Railway Logs دەردەکەوێت
        if took > 1.0 and time.time() - st.get("last_warn", 0) > 10:
            st["last_warn"] = time.time()
            print(f"[XP] board edit took {took:.1f}s (Discord rate limit / slow API)", flush=True)
    except discord.NotFound:
        xp_remove_board(b)
    except Exception as e:
        st["fails"] += 1
        if st["fails"] in (1, 30):
            print(f"xp board edit error ({st['fails']}): {e}", flush=True)
        if st["fails"] >= 30 and isinstance(e, discord.Forbidden):
            xp_remove_board(b)
    finally:
        st["busy"] = False


@_tasks.loop(seconds=XP_REFRESH)
async def xp_board_loop():
    for b in list(xp_db["boards"]):
        st = _xp_board_state.setdefault(b["m"], {"sig": None, "busy": False, "fails": 0})
        if st["busy"]:
            continue
        guild = bot.get_guild(b["g"])
        if guild is None:
            continue
        try:
            embed = xp_board_embed(guild, b["k"], b["p"])
            sig = _xp_sig(embed)
        except Exception as e:
            print(f"xp board render error: {e}", flush=True)
            continue
        if sig == st["sig"]:
            continue          # گۆڕانکاری نییە، پێویست بە edit نییە
        st["busy"] = True
        t = asyncio.create_task(xp_edit_board(b, st, embed, sig))
        _xp_tasks.add(t)
        t.add_done_callback(_xp_tasks.discard)


async def xp_create_board(channel, guild, kind, period):
    # ئەگەر هەمان بۆرد لەم کەناڵەدا هەبوو، کۆنەکە بسڕەوە
    for old in [x for x in xp_db["boards"]
                if x["g"] == guild.id and x["c"] == channel.id and x["k"] == kind and x["p"] == period]:
        xp_remove_board(old)
        await xp_delete_board_message(old)

    embed = xp_board_embed(guild, kind, period)
    msg = await channel.send(embed=embed)          # پەبلیک، هەموو کەس دەیبینێت
    b = {"g": guild.id, "c": channel.id, "m": msg.id, "k": kind, "p": period}
    xp_db["boards"].append(b)
    _xp_board_state[msg.id] = {"sig": _xp_sig(embed), "busy": False, "fails": 0}

    mine = [x for x in xp_db["boards"] if x["g"] == guild.id]
    while len(mine) > XP_MAX_BOARDS_PER_GUILD:
        xp_remove_board(mine.pop(0))
    xp_save_now()
    return msg


async def xp_on_ready():
    for loop_ in (xp_voice_loop, xp_save_loop, xp_board_loop):
        if not loop_.is_running():
            loop_.start()


bot.add_listener(xp_on_ready, "on_ready")


# ---------- دەسەڵات ----------

def xp_denied_reason(interaction):
    """None = دەتوانێت | 'deny' = دەسەڵات نییە | 'channel' = ئەم کەناڵە نابێت"""
    m = interaction.user
    g = interaction.guild
    c = cfg(g.id)

    chans = c["xp_channels"]
    if chans:
        ids = {interaction.channel_id, getattr(interaction.channel, "parent_id", None)}
        if not (ids & set(chans)):
            return "channel"

    if m.id == g.owner_id:
        return None
    if is_blacklisted(m, "xp"):
        return "deny"
    if is_dev(m):
        return None
    roles = c["xp_roles"]
    if roles and not any(r.id in roles for r in m.roles):
        return "deny"
    return None


async def xp_deny(interaction, why):
    if why == "channel":
        chans = " ".join(f"<#{x}>" for x in cfg(interaction.guild.id)["xp_channels"])
        try:
            await interaction.response.send_message(
                f"ئەم فەرمانە لێرە ناکرێت، لەم کەناڵانە بەکاری بهێنە:\n{chans}",
                ephemeral=True, delete_after=10)
        except Exception:
            pass
    else:
        await deny_interaction(interaction)


# ---------- /xp ----------

def xp_step_embed(kind=None):
    if kind is None:
        return discord.Embed(
            title="✦ XP ✦",
            description="جۆری XP هەڵبژێرە ♡",
            color=discord.Color.from_rgb(244, 208, 238))
    label, emoji = XP_TYPES[kind]
    return discord.Embed(
        title=f"{emoji} {label} XP",
        description="ماوەکە هەڵبژێرە ♡",
        color=discord.Color.from_rgb(244, 208, 238))


class XpKindView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=120)
        self.author_id = author_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await deny_interaction(interaction)
            return False
        return True

    async def _pick(self, interaction, kind):
        await interaction.response.edit_message(
            embed=xp_step_embed(kind), view=XpPeriodView(self.author_id, kind))

    @discord.ui.button(label="چات", emoji="💬", style=discord.ButtonStyle.secondary)
    async def chat_btn(self, interaction, button):
        await self._pick(interaction, "chat")

    @discord.ui.button(label="ڤۆیس", emoji="🎙️", style=discord.ButtonStyle.secondary)
    async def voice_btn(self, interaction, button):
        await self._pick(interaction, "voice")


class XpPeriodView(discord.ui.View):
    def __init__(self, author_id, kind):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.kind = kind
        for p, label in XP_PERIODS.items():
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=0)
            btn.callback = self._make_cb(p)
            self.add_item(btn)
        back = discord.ui.Button(label="گەڕانەوە", emoji="↩️", style=discord.ButtonStyle.primary, row=1)
        back.callback = self._back
        self.add_item(back)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await deny_interaction(interaction)
            return False
        return True

    def _make_cb(self, period):
        async def cb(interaction):
            why = xp_denied_reason(interaction)
            if why:
                await xp_deny(interaction, why)
                return
            await interaction.response.edit_message(
                embed=discord.Embed(
                    description=f"✅ بۆردی **{XP_TYPES[self.kind][0]} · {XP_PERIODS[period]}** نێردرا",
                    color=discord.Color.from_rgb(244, 208, 238)),
                view=None)
            try:
                await xp_create_board(interaction.channel, interaction.guild, self.kind, period)
            except discord.Forbidden:
                await interaction.followup.send(
                    "نەمتوانی لەم کەناڵە بنێرم، دەسەڵاتی Send Messages و Embed Links بدە بە بۆتەکە.",
                    ephemeral=True)
            except Exception as e:
                print(f"xp create board error: {e}", flush=True)
                await interaction.followup.send("هەڵەیەک ڕوویدا، دووبارە هەوڵ بدەوە.", ephemeral=True)
        return cb

    async def _back(self, interaction):
        await interaction.response.edit_message(embed=xp_step_embed(), view=XpKindView(self.author_id))


@bot.tree.command(name="xp", description="تۆپی XP ی چات و ڤۆیس پیشان بدە")
@app_commands.guild_only()
async def xp_cmd(interaction: discord.Interaction):
    why = xp_denied_reason(interaction)
    if why:
        await xp_deny(interaction, why)
        return
    await interaction.response.send_message(
        embed=xp_step_embed(), view=XpKindView(interaction.user.id), ephemeral=True)


# ---------- /setxp ----------

def xpset_embed(guild):
    c = cfg(guild.id)
    roles = " ".join(f"<@&{r}>" for r in c["xp_roles"]) or "🌍 هەموو کەسێک"
    chans = " ".join(f"<#{x}>" for x in c["xp_channels"]) or "🌍 هەموو شوێنێک"
    bl = " ".join(f"<@{u}>" for u in blacklist_list(guild.id, "xp")) or "❌"
    e = discord.Embed(title="✦ XP Settings", color=discord.Color.from_rgb(244, 208, 238))
    e.add_field(name="ڕۆڵەکان (کێ بتوانێت)", value=roles[:1000], inline=False)
    e.add_field(name="کەناڵەکان (لە کوێ بتوانرێت)", value=chans[:1000], inline=False)
    e.add_field(name="🚫 Blacklist", value=bl[:1000], inline=False)
    e.set_footer(text="ڕۆڵ/کەناڵ: هەڵبژاردنی نوێ لیستی پێشوو دەگۆڕێت | Blacklist: زیاد / لابردن | بەتاڵ = هەموو شوێن و کەس")
    return e


class XpRolesSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="ڕۆڵەکان هەڵبژێرە (کێ بتوانێت /xp بەکاربهێنێت)...",
                         min_values=1, max_values=25, row=0)

    async def callback(self, interaction):
        g = self.view.guild
        cfg(g.id)["xp_roles"][:] = [r.id for r in self.values]
        save_config()
        await interaction.response.edit_message(
            embed=xpset_embed(g), view=XpSetView(g, self.view.author_id))


class XpChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="کەناڵەکان هەڵبژێرە (لە کوێ بتوانرێت)...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.news],
            min_values=1, max_values=25, row=1)

    async def callback(self, interaction):
        g = self.view.guild
        cfg(g.id)["xp_channels"][:] = [ch.id for ch in self.values]
        save_config()
        await interaction.response.edit_message(
            embed=xpset_embed(g), view=XpSetView(g, self.view.author_id))


class XpBlacklistSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="🚫 Blacklist — کەس هەڵبژێرە (زیاد / لابردن)...",
                         min_values=1, max_values=25, row=2)

    async def callback(self, interaction):
        g = self.view.guild
        _toggle_ids(blacklist_list(g.id, "xp"), [u.id for u in self.values])
        save_config()
        await interaction.response.edit_message(
            embed=xpset_embed(g), view=XpSetView(g, self.view.author_id))


class XpSetView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        self.add_item(XpRolesSelect())
        self.add_item(XpChannelsSelect())
        self.add_item(XpBlacklistSelect())

    async def _refresh(self, interaction):
        await interaction.response.edit_message(
            embed=xpset_embed(self.guild), view=XpSetView(self.guild, self.author_id))

    @discord.ui.button(label="هەموو کەسێک", emoji="🌍", style=discord.ButtonStyle.secondary, row=3)
    async def all_people(self, interaction, button):
        cfg(self.guild.id)["xp_roles"][:] = []
        save_config()
        await self._refresh(interaction)

    @discord.ui.button(label="هەموو شوێنێک", emoji="🌍", style=discord.ButtonStyle.secondary, row=3)
    async def all_places(self, interaction, button):
        cfg(self.guild.id)["xp_channels"][:] = []
        save_config()
        await self._refresh(interaction)

    @discord.ui.button(label="Clear Blacklist", style=discord.ButtonStyle.danger, row=3)
    async def clear_bl(self, interaction, button):
        blacklist_list(self.guild.id, "xp")[:] = []
        save_config()
        await self._refresh(interaction)


@bot.tree.command(name="setxp", description="ڕێکخستنی /xp: کێ و لە کوێ بتوانێت بەکاری بهێنێت")
@app_commands.guild_only()
async def setxp_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=xpset_embed(interaction.guild),
        view=XpSetView(interaction.guild, interaction.user.id),
        ephemeral=True)


# =========================================================
# 29c. LOVE + ACTIONS  (ship / kiss / hug / pat)
# =========================================================
# - بنووسە:  ship @کەس   (یان وەڵامی نامەی کەسێک بدەوە بە ship)
#   ڕێژەی خۆشەویستی نێوان تۆ و ئەو کەسە پیشان دەدات
# - ڕێژەکە بۆ هەر دووکەس هەموو ڕۆژێک نوێ دەبێتەوە (بە کاتی عێراق)،
#   لە هەمان ڕۆژدا هەر جارێک بپرسیت هەمان ڕێژە دەدات
# - ship @a @b  → ڕێژەی نێوان ئەو دوو کەسە
# - kiss / hug / pat @کەس → ماچ / باوەش / نازدان
# ناوی فەرمانەکان لێرە دەتوانیت بیانگۆڕیت:

LOVE_WORDS = ["ship"]
LOVE_ACTIONS = {
    "kiss": {
        "words": ["kiss", "mach"],
        "emoji": "💋",
        "title": "ماچ",
        "color": (255, 205, 222),
        "lines": [
            "ماچێکی ناسک لەسەر ڕوومەت 🤍",
            "ماچێکی بچووک و بێدەنگ ✨",
            "ماچێک وەک پەپولەیەک نیشتەوە 🦋",
            "ماچێکی شیرین و شەرمنانە 🌷",
        ],
        "count": "جار ماچی کردووە",
    },
    "hug": {
        "words": ["hug", "bawesh"],
        "emoji": "🫶",
        "title": "باوەش",
        "color": (224, 208, 250),
        "lines": [
            "باوەشێکی گەرم و ئارام ☁️",
            "باوەشێک کە هەموو شتێک ئارام دەکاتەوە 🤍",
            "باوەشێکی توند و پڕ لە خۆشەویستی 💗",
            "باوەشێکی نەرم وەک هەور ☁️",
        ],
        "count": "جار باوەشی پێداکردووە",
    },
    "pat": {
        "words": ["pat", "naz"],
        "emoji": "🎀",
        "title": "نازدان",
        "color": (255, 226, 212),
        "lines": [
            "دەستێکی نەرم بەسەر سەریدا هات 🌷",
            "نازێکی بچووک و شیرین 🎀",
            "بە ناسکی ناز کرا ✨",
            "دەستێکی ئارامکەرەوە 🤍",
        ],
        "count": "جار نازی کردووە",
    },
}

LOVE_COOLDOWN = 3          # چرکە: لە نێوان دوو فەرمانی یەک کەس
LOVE_LEVELS = [            # (تا چەند %, ستێت)
    (9,   "One-Sided Love 💔"),
    (19,  "Toxic Love 🥀"),
    (29,  "Forbidden Love 🖤"),
    (39,  "Secret Love 🤫"),
    (49,  "Platonic Love 🫂"),
    (59,  "Family Love 🏡"),
    (69,  "First Love 🌷"),
    (79,  "Romantic Love ❤️"),
    (89,  "True Love 🤍"),
    (99,  "Eternal Love 💍"),
    (100, "Unconditional Love ♾️"),
]
LOVE_SELF = "Self Love 🖤"

xp_db.setdefault("love", {})     # love[guild]["a>b"][action] = ژمارە
_love_last = {}

_LOVE_ACTION_WORDS = {w: k for k, v in LOVE_ACTIONS.items() for w in v["words"]}


def love_percent(a_id, b_id):
    """ڕێژەی نێوان دوو کەس، هەموو ڕۆژێک نوێ دەبێتەوە، A&B و B&A هەمان ڕێژەیان هەیە"""
    import hashlib
    x, y = sorted((int(a_id), int(b_id)))
    day = xp_period_keys()["d"]
    h = hashlib.sha256(f"{x}:{y}:{day}".encode()).digest()
    return int.from_bytes(h[:4], "big") % 101


def love_status(p, gid=None):
    custom = cfg(gid)["love_texts"] if gid else {}
    for limit, label in LOVE_LEVELS:
        if p <= limit:
            return custom.get(str(limit)) or label
    return LOVE_LEVELS[-1][1]


def love_self_text(gid=None):
    custom = cfg(gid)["love_texts"] if gid else {}
    return custom.get("self") or LOVE_SELF


def love_bar(p):
    full = round(p / 10)
    return "🩷" * full + "🤍" * (10 - full)


def love_embed(a, b, gid=None, p=None):
    if p is None:
        p = 100 if a.id == b.id else love_percent(a.id, b.id)
    text = love_self_text(gid) if a.id == b.id else love_status(p, gid)
    desc = (
        "₊˚⊹ ♡ ⋆｡˚ ✧ ˚｡⋆ ♡ ⊹˚₊\n\n"
        f"{a.mention}  ˖ ♡ ˖  {b.mention}\n\n"
        f"## ♡ {p}% ♡\n"
        f"{love_bar(p)}\n\n"
        f"**{text}**\n\n"
        "-# ⋆ ڕێژەکە هەموو ڕۆژێک نوێ دەبێتەوە ⋆"
    )
    e = discord.Embed(description=desc, color=discord.Color.from_rgb(250, 205, 235))
    e.set_author(name="ڕێژەی خۆشەویستی", icon_url=a.display_avatar.url)
    e.set_thumbnail(url=b.display_avatar.url)
    return e


def love_count(gid, a_id, b_id, action):
    """ژمارەی جارەکان، A بۆ B (لە یەک ئاراستەدا) و دەیگەڕێنێتەوە"""
    global _xp_dirty
    g = xp_db["love"].setdefault(str(gid), {})
    rec = g.setdefault(f"{a_id}>{b_id}", {})
    rec[action] = rec.get(action, 0) + 1
    _xp_dirty = True
    return rec[action]


def action_embed(a, b, action, n):
    spec = LOVE_ACTIONS[action]
    desc = (
        "₊˚⊹ ♡ ⋆｡˚ ✧ ˚｡⋆ ♡ ⊹˚₊\n\n"
        f"{a.mention}  {spec['emoji']}  {b.mention}\n\n"
        f"{random.choice(spec['lines'])}\n\n"
        f"-# ⋆ {n} {spec['count']} ⋆"
    )
    e = discord.Embed(description=desc, color=discord.Color.from_rgb(*spec["color"]))
    e.set_author(name=spec["title"], icon_url=a.display_avatar.url)
    e.set_thumbnail(url=b.display_avatar.url)
    return e


async def love_on_message(message):
    if message.author.bot or message.guild is None or not message.content:
        return
    parts = message.content.strip().split()
    if not parts:
        return
    word = parts[0].lower()
    is_love = word in LOVE_WORDS
    action = _LOVE_ACTION_WORDS.get(word)
    if not is_love and not action:
        return

    allowed_ch = cfg(message.guild.id)["love_channels"]
    if allowed_ch and not ({message.channel.id, getattr(message.channel, "parent_id", None)} & set(allowed_ch)):
        return

    # کەسەکان: mention ـەکان، یان ئەو کەسەی وەڵامی نامەکەی دراوەتەوە
    targets = [u for u in message.mentions if not u.bot]
    if not targets and message.reference and message.reference.message_id:
        try:
            ref = message.reference.resolved
            if ref is None or isinstance(ref, discord.DeletedReferencedMessage):
                ref = await message.channel.fetch_message(message.reference.message_id)
            if ref and not ref.author.bot:
                targets = [ref.author]
        except Exception:
            pass

    async def hint(text):
        try:
            await message.channel.send(f"{message.author.mention} {text}", delete_after=8)
        except Exception:
            pass

    if not targets:
        if len(parts) == 1:        # تەنها وشەکە بەتەنیا، ڕێنمایی بکە
            await hint("کەسێک mention بکە 🌷")
        return

    now = time.time()
    if now - _love_last.get(message.author.id, 0) < LOVE_COOLDOWN:
        return
    _love_last[message.author.id] = now

    me = message.author
    try:
        if is_love:
            a, b = (targets[0], targets[1]) if len(targets) >= 2 else (me, targets[0])
            embed = love_embed(a, b, message.guild.id)
        else:
            b = targets[0]
            if b.id == me.id:
                await hint("ناتوانیت ئەمە بۆ خۆت بکەیت 🥺")
                return
            n = love_count(message.guild.id, me.id, b.id, action)
            embed = action_embed(me, b, action, n)
        await message.reply(embed=embed, mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        print(f"love command error: {e}", flush=True)


bot.add_listener(love_on_message, "on_message")


# ---------- /setlove ----------

def love_tier_ranges():
    out, lo = [], 0
    for limit, label in LOVE_LEVELS:
        out.append((str(limit), f"{lo}-{limit}%" if lo != limit else f"{limit}%", label))
        lo = limit + 1
    return out


def loveset_embed(guild):
    c = cfg(guild.id)
    chans = " ".join(f"<#{x}>" for x in c["love_channels"]) or "🌍 هەموو شوێنێک"
    lines = []
    for key, rng, default in love_tier_ranges():
        cur = c["love_texts"].get(key)
        lines.append(f"`{rng:>7}`  {cur or default}" + ("  ✏️" if cur else ""))
    cur_self = c["love_texts"].get("self")
    lines.append(f"`   خۆی`  {cur_self or LOVE_SELF}" + ("  ✏️" if cur_self else ""))
    e = discord.Embed(title="🎀 Ship / Kiss / Hug / Pat — Settings",
                      color=discord.Color.from_rgb(250, 205, 235))
    e.add_field(name="کەناڵەکان (لە کوێ کار بکات)", value=chans[:1000], inline=False)
    e.add_field(name="نووسینی ڕێژەکان", value="\n".join(lines)[:1000], inline=False)
    e.set_footer(text="✏️ = گۆڕدراوە | ڕێژەیەک هەڵبژێرە بۆ گۆڕینی نووسینەکەی | بەتاڵ بنێرە = دیفەڵت")
    return e


class LoveTextModal(discord.ui.Modal):
    def __init__(self, guild, author_id, key, title_txt, current):
        super().__init__(title=f"نووسینی {title_txt}"[:45])
        self.guild = guild
        self.author_id = author_id
        self.key = key
        self.text = discord.ui.TextInput(
            label="نووسینی نوێ (بەتاڵ = دیفەڵت)", default=current, required=False,
            max_length=40, placeholder="بۆ نموونە: Romantic Love ❤️")
        self.add_item(self.text)

    async def on_submit(self, interaction):
        if not is_dev(interaction.user):
            await deny_interaction(interaction)
            return
        val = self.text.value.strip()
        texts = cfg(self.guild.id)["love_texts"]
        if val:
            texts[self.key] = val
        else:
            texts.pop(self.key, None)
        save_config()
        await interaction.response.edit_message(
            embed=loveset_embed(self.guild), view=LoveSetView(self.guild, self.author_id))


class LoveChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="کەناڵەکان هەڵبژێرە (لە کوێ کار بکات)...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.news],
            min_values=1, max_values=25, row=0)

    async def callback(self, interaction):
        g = self.view.guild
        cfg(g.id)["love_channels"][:] = [ch.id for ch in self.values]
        save_config()
        await interaction.response.edit_message(
            embed=loveset_embed(g), view=LoveSetView(g, self.view.author_id))


class LoveTierSelect(discord.ui.Select):
    def __init__(self, guild):
        c = cfg(guild.id)["love_texts"]
        opts = []
        for key, rng, default in love_tier_ranges():
            opts.append(discord.SelectOption(label=f"{rng}", value=key,
                                             description=(c.get(key) or default)[:100]))
        opts.append(discord.SelectOption(label="خۆی (Self)", value="self",
                                         description=(c.get("self") or LOVE_SELF)[:100]))
        super().__init__(placeholder="✏️ ڕێژەیەک هەڵبژێرە بۆ گۆڕینی نووسینەکەی...", options=opts, row=1)

    async def callback(self, interaction):
        g = self.view.guild
        key = self.values[0]
        if key == "self":
            title_txt, default = "Self", LOVE_SELF
        else:
            rng = {k: r for k, r, _ in love_tier_ranges()}[key]
            title_txt = rng
            default = dict((k, d) for k, _, d in love_tier_ranges())[key]
        current = cfg(g.id)["love_texts"].get(key) or default
        await interaction.response.send_modal(
            LoveTextModal(g, self.view.author_id, key, title_txt, current))


class LoveSetView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        self.add_item(LoveChannelsSelect())
        self.add_item(LoveTierSelect(guild))

    async def _refresh(self, interaction):
        await interaction.response.edit_message(
            embed=loveset_embed(self.guild), view=LoveSetView(self.guild, self.author_id))

    @discord.ui.button(label="Preview", emoji="👁", style=discord.ButtonStyle.primary, row=2)
    async def preview_btn(self, interaction, button):
        me = interaction.user
        other = interaction.guild.me or me
        e1 = love_embed(me, other, self.guild.id, p=73)
        e2 = action_embed(me, other, "kiss", 5)
        await interaction.response.send_message(
            content="👁 Preview — ship  +  kiss", embeds=[e1, e2], ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label="هەموو شوێنێک", emoji="🌍", style=discord.ButtonStyle.secondary, row=2)
    async def all_places(self, interaction, button):
        cfg(self.guild.id)["love_channels"][:] = []
        save_config()
        await self._refresh(interaction)

    @discord.ui.button(label="Reset Texts", style=discord.ButtonStyle.danger, row=2)
    async def reset_texts(self, interaction, button):
        cfg(self.guild.id)["love_texts"].clear()
        save_config()
        await self._refresh(interaction)


@bot.tree.command(name="setlove", description="ڕێکخستنی ship / kiss / hug: کەناڵەکان و نووسینی ڕێژەکان")
@app_commands.guild_only()
async def setlove_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=loveset_embed(interaction.guild),
        view=LoveSetView(interaction.guild, interaction.user.id),
        ephemeral=True)


# =========================================================
# 29d. SERVER COPY  (/create_channels)  — تەنها خاوەنی بۆت
# =========================================================
# - لە سێرڤەری سەرچاوە: /create_channels → "Copy this server"
#   (ڕۆڵ، کاتێگۆری، کەناڵ، Permission ـەکان، ئیمۆجی و ڕێکخستنی سێرڤەر هەڵدەگیرێت)
# - لە هەر سێرڤەرێکی تر: /create_channels → تێمپلەیتەکە هەڵبژێرە → Paste
# - تێمپلەیتەکان لە فۆڵدەری server_templates هەڵدەگیرێن (لە تەنیشت guild_config.json)
# - ڕێکخستنەکانی بۆتەکەش کۆپی دەکرێن (Safika/Mute/Staff، Auto React، Security، Reklam، Welcome ...)
#   و ئایدی ڕۆڵ و کەناڵ و ئیمۆجییەکان دەگۆڕدرێن بۆ ئەوانەی سێرڤەری نوێ
# - کۆپی ناکرێت: ئەندام، نامە، بۆت، Webhook، Invite، ستیکەر، Permission ـی تایبەت بە ئەندام
# - سەلامەتی: هیچ شتێک ناسڕدرێتەوە و هیچ شتێک لە سێرڤەری سەرچاوە دەستکاری ناکرێت.
#   سێرڤەری سەرچاوە پارێزراوە و ناتوانرێت Paste ی تێدا بکرێت.
# - بۆتەکە لە سێرڤەری نوێ دەبێت Administrator ی هەبێت (یان Manage Roles/Channels/Emojis)

import base64 as _b64

CC_OWNER_ID = 1130455970494025860      # ئایدی ئەکاونتی تۆ، تەنها تۆ دەتوانیت بەکاری بهێنیت
CC_DIR = os.path.join(os.path.dirname(CONFIG_FILE) or ".", "server_templates")
CC_PROTECTED_GUILDS = [1556323391143813130]               # ئایدی سێرڤەرە سەرەکییەکەت لێرە دابنێ، Paste ی تێدا ناکرێت هەرگیز
CC_MAX_EMOJIS = 250
CC_COLOR = discord.Color.from_rgb(224, 208, 250)
_cc_running = set()


# ---------- هەڵگرتنی تێمپلەیت ----------

def cc_valid_key(key):
    return bool(re.fullmatch(r"[0-9_]+", key or ""))


def cc_meta_list():
    out = []
    try:
        names = os.listdir(CC_DIR)
    except FileNotFoundError:
        return out
    for fn in names:
        if fn.endswith(".meta.json"):
            try:
                with open(os.path.join(CC_DIR, fn), "r", encoding="utf-8") as f:
                    out.append(json.load(f))
            except Exception:
                pass
    out.sort(key=lambda m: m.get("saved_at", 0), reverse=True)
    return out[:25]


def cc_load(key):
    if not cc_valid_key(key):
        raise ValueError("bad key")
    with open(os.path.join(CC_DIR, f"{key}.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def cc_load_meta(key):
    if not cc_valid_key(key):
        raise ValueError("bad key")
    with open(os.path.join(CC_DIR, f"{key}.meta.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def cc_delete(key):
    if not cc_valid_key(key):
        return
    for suffix in (".json", ".meta.json"):
        try:
            os.remove(os.path.join(CC_DIR, key + suffix))
        except FileNotFoundError:
            pass


def cc_save(key, data, meta):
    os.makedirs(CC_DIR, exist_ok=True)
    for suffix, obj in ((".json", data), (".meta.json", meta)):
        path = os.path.join(CC_DIR, key + suffix)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(path + ".tmp", path)


def cc_sources():
    """ئایدی ئەو سێرڤەرانەی لێیانەوە کۆپی کراوە، هەمیشە پارێزراون (Paste ی تێدا ناکرێت)"""
    try:
        with open(os.path.join(CC_DIR, "sources.json"), "r", encoding="utf-8") as f:
            return {int(x) for x in json.load(f)}
    except Exception:
        return set()


def cc_add_source(gid):
    s = cc_sources()
    s.add(int(gid))
    os.makedirs(CC_DIR, exist_ok=True)
    path = os.path.join(CC_DIR, "sources.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(sorted(s), f)
    os.replace(path + ".tmp", path)


_CC_ID_RE = re.compile(r"(?<!\d)\d{17,20}(?!\d)")


def cc_remap(obj, idmap):
    """هەموو ئایدییەکی کۆن (ڕۆڵ/کەناڵ/ئیمۆجی/سێرڤەر) دەگۆڕێت بۆ نوێیەکەی. ئایدی ئەندامەکان وەک خۆیان دەمێنن"""
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return idmap.get(obj, obj)
    if isinstance(obj, str):
        return _CC_ID_RE.sub(lambda m: str(idmap.get(int(m.group()), m.group())), obj)
    if isinstance(obj, list):
        return [cc_remap(x, idmap) for x in obj]
    if isinstance(obj, dict):
        return {(cc_remap(k, idmap) if isinstance(k, str) else k): cc_remap(v, idmap)
                for k, v in obj.items()}
    return obj


def cc_updater(interaction, title):
    state = {"t": 0.0}

    async def upd(text, force=False):
        now = time.time()
        if not force and now - state["t"] < 1.5:
            return
        state["t"] = now
        try:
            await interaction.edit_original_response(
                embed=discord.Embed(title=title, description=text, color=CC_COLOR), view=None)
        except Exception:
            pass
    return upd


# ---------- کۆپیکردن ----------

def cc_overwrites(ch):
    """تەنها Permission ی ڕۆڵەکان (ئەندامەکان لە سێرڤەری تر نین)"""
    out = []
    for target, ow in ch.overwrites.items():
        if isinstance(target, discord.Role):
            a, d = ow.pair()
            out.append({"id": target.id, "a": a.value, "d": d.value})
    return out


def cc_channel_type(ch):
    if isinstance(ch, discord.ForumChannel):
        return "forum"
    if isinstance(ch, discord.StageChannel):
        return "stage"
    if isinstance(ch, discord.VoiceChannel):
        return "voice"
    if isinstance(ch, discord.TextChannel):
        return "news" if ch.is_news() else "text"
    return None


async def cc_copy(guild, upd):
    await upd("ڕۆڵەکان...", force=True)
    roles = [{
        "id": r.id, "name": r.name, "color": r.colour.value, "hoist": r.hoist,
        "mentionable": r.mentionable, "perms": r.permissions.value, "pos": r.position,
    } for r in guild.roles if not r.is_default() and not r.managed]

    await upd("کاتێگۆری و کەناڵەکان...", force=True)
    cats = [{
        "id": c.id, "name": c.name, "pos": c.position, "ow": cc_overwrites(c),
    } for c in guild.categories]

    chans = []
    for ch in guild.channels:
        t = cc_channel_type(ch)
        if t is None:
            continue
        chans.append({
            "id": ch.id, "name": ch.name, "type": t,
            "cat": ch.category_id, "pos": ch.position,
            "topic": getattr(ch, "topic", None),
            "nsfw": bool(getattr(ch, "nsfw", False)),
            "slow": getattr(ch, "slowmode_delay", 0) or 0,
            "bitrate": getattr(ch, "bitrate", None),
            "limit": getattr(ch, "user_limit", 0) or 0,
            "ow": cc_overwrites(ch),
        })

    settings = {
        "name": guild.name,
        "verification": guild.verification_level.value,
        "notifications": guild.default_notifications.value,
        "content_filter": guild.explicit_content_filter.value,
        "afk_timeout": guild.afk_timeout,
        "afk_channel": guild.afk_channel.id if guild.afk_channel else None,
        "system_channel": guild.system_channel.id if guild.system_channel else None,
        "icon": None,
    }
    try:
        if guild.icon:
            settings["icon"] = _b64.b64encode(await guild.icon.read()).decode()
    except Exception:
        pass

    emojis = []
    for i, e in enumerate(list(guild.emojis)[:CC_MAX_EMOJIS], 1):
        await upd(f"ئیمۆجییەکان... {i}/{min(len(guild.emojis), CC_MAX_EMOJIS)}")
        try:
            emojis.append({"id": e.id, "n": e.name, "d": _b64.b64encode(await e.read()).decode()})
        except Exception:
            pass

    # ڕێکخستنەکانی بۆت (تەنها دەخوێنرێتەوە، دەستکاری ناکرێت)
    await upd("⚙️ ڕێکخستنەکانی بۆت...", force=True)
    bot_cfg = json.loads(json.dumps(config.get(str(guild.id), {}), ensure_ascii=False))

    key = f"{int(time.time())}_{guild.id}"
    data = {
        "src_id": guild.id, "bot_cfg": bot_cfg,
        "name": guild.name, "everyone_id": guild.default_role.id,
        "everyone_perms": guild.default_role.permissions.value,
        "settings": settings, "roles": roles, "cats": cats, "chans": chans, "emojis": emojis,
    }
    meta = {
        "key": key, "name": guild.name, "saved_at": int(time.time()), "src_id": guild.id,
        "roles": len(roles), "cats": len(cats), "chans": len(chans), "emojis": len(emojis),
    }
    cc_save(key, data, meta)
    cc_add_source(guild.id)
    return meta


# ---------- دانانەوە ----------

async def cc_paste(guild, tpl, upd):
    res = {"roles": 0, "cats": 0, "chans": 0, "emojis": 0, "fallback": 0, "cfg": 0, "fail": []}
    me = guild.me
    bot_admin = me.guild_permissions.administrator
    bot_perms = me.guild_permissions.value
    reason = "Server copy"

    def fail(what, ex):
        res["fail"].append(f"{what}: {str(ex)[:80]}")

    # ---- ڕۆڵەکان ----
    role_map = {tpl["everyone_id"]: guild.default_role}
    if not tpl.get("skip_everyone"):
        try:
            ev = tpl["everyone_perms"] if bot_admin else tpl["everyone_perms"] & bot_perms
            await guild.default_role.edit(permissions=discord.Permissions(ev), reason=reason)
        except Exception as ex:
            fail("@everyone", ex)

    existing = {r.name: r for r in guild.roles if not r.is_default() and not r.managed}

    # لە بەرزەوە بۆ خوارەوە دروست دەکرێن، چونکە ڕۆڵی نوێ دەکەوێتە خوار ئەوانی پێشوو
    roles_sorted = sorted(tpl["roles"], key=lambda r: -r["pos"])
    for i, rd in enumerate(roles_sorted, 1):
        await upd(f"🎭 ڕۆڵەکان... {i}/{len(roles_sorted)}")
        if rd["name"] in existing:
            role_map[rd["id"]] = existing[rd["name"]]
            continue
        perms = rd["perms"] if bot_admin else rd["perms"] & bot_perms
        try:
            role = await guild.create_role(
                name=rd["name"], permissions=discord.Permissions(perms),
                colour=discord.Colour(rd["color"]), hoist=rd["hoist"],
                mentionable=rd["mentionable"], reason=reason)
            role_map[rd["id"]] = role
            res["roles"] += 1
        except Exception as ex:
            fail(f"@{rd['name']}", ex)

    def ow_map(items):
        out = {}
        for o in items:
            role = role_map.get(o["id"])
            if role is None:
                continue
            allow = o["a"] if bot_admin else o["a"] & bot_perms
            out[role] = discord.PermissionOverwrite.from_pair(
                discord.Permissions(allow), discord.Permissions(o["d"]))
        return out

    # ---- کاتێگۆریەکان ----
    cat_map = {}
    cats_sorted = sorted(tpl["cats"], key=lambda c: c["pos"])
    for i, cd in enumerate(cats_sorted, 1):
        await upd(f"📁 کاتێگۆریەکان... {i}/{len(cats_sorted)}")
        try:
            cat_map[cd["id"]] = await guild.create_category(
                cd["name"], overwrites=ow_map(cd["ow"]), reason=reason)
            res["cats"] += 1
        except Exception as ex:
            fail(f"category {cd['name']}", ex)

    # ---- کەناڵەکان ----
    chan_map = {}
    bit_limit = getattr(guild, "bitrate_limit", 96000)
    chans_sorted = sorted(tpl["chans"], key=lambda c: c["pos"])

    async def make(cd, t, cat, ow):
        kw = {"overwrites": ow, "reason": reason}
        if cat is not None:
            kw["category"] = cat
        if t in ("text", "news"):
            extra = {"news": True} if t == "news" else {}
            return await guild.create_text_channel(
                cd["name"], topic=cd.get("topic") or None, nsfw=cd.get("nsfw", False),
                slowmode_delay=cd.get("slow", 0) or 0, **extra, **kw)
        if t == "voice":
            return await guild.create_voice_channel(
                cd["name"], bitrate=min(cd.get("bitrate") or 64000, bit_limit),
                user_limit=cd.get("limit", 0) or 0, **kw)
        if t == "stage":
            return await guild.create_stage_channel(
                cd["name"], topic=cd.get("topic") or cd["name"], **kw)
        if t == "forum":
            return await guild.create_forum(
                cd["name"], topic=cd.get("topic") or None, nsfw=cd.get("nsfw", False),
                slowmode_delay=cd.get("slow", 0) or 0, **kw)
        raise ValueError(f"unknown type {t}")

    fallback_type = {"news": "text", "forum": "text", "stage": "voice"}
    for i, cd in enumerate(chans_sorted, 1):
        await upd(f"💬 کەناڵەکان... {i}/{len(chans_sorted)}")
        cat = cat_map.get(cd["cat"])
        ow = ow_map(cd["ow"])
        try:
            try:
                ch = await make(cd, cd["type"], cat, ow)
            except (discord.HTTPException, TypeError) as ex:
                fb = fallback_type.get(cd["type"])
                if fb is None:
                    raise
                ch = await make(cd, fb, cat, ow)     # Community چالاک نییە → جۆری ئاسایی
                res["fallback"] += 1
            chan_map[cd["id"]] = ch
            res["chans"] += 1
        except Exception as ex:
            fail(f"#{cd['name']}", ex)

    # ---- ڕێکخستنی سێرڤەر ----
    if not tpl.get("skip_settings"):
        await upd("⚙️ ڕێکخستنی سێرڤەر...", force=True)
        st = tpl["settings"]
        base = {"name": st["name"]}
        for k, attr, enum in (("verification", "verification_level", discord.VerificationLevel),
                              ("notifications", "default_notifications", discord.NotificationLevel),
                              ("content_filter", "explicit_content_filter", discord.ContentFilter)):
            try:
                base[attr] = enum(st[k])
            except Exception:
                pass
        base["afk_timeout"] = st.get("afk_timeout", 300)
        if st.get("afk_channel") in chan_map and isinstance(chan_map[st["afk_channel"]], discord.VoiceChannel):
            base["afk_channel"] = chan_map[st["afk_channel"]]
        if st.get("system_channel") in chan_map and isinstance(chan_map[st["system_channel"]], discord.TextChannel):
            base["system_channel"] = chan_map[st["system_channel"]]
        try:
            kw = dict(base)
            if st.get("icon"):
                kw["icon"] = _b64.b64decode(st["icon"])
            await guild.edit(reason=reason, **kw)
        except Exception as ex:
            try:
                await guild.edit(reason=reason, name=st["name"])
            except Exception as ex2:
                fail("server settings", ex2)

    # ---- ئیمۆجی ----
    bad = 0
    emoji_map = {}
    for i, ed in enumerate(tpl.get("emojis", []), 1):
        await upd(f"😀 ئیمۆجییەکان... {i}/{len(tpl['emojis'])}")
        try:
            new_e = await guild.create_custom_emoji(
                name=ed["n"], image=_b64.b64decode(ed["d"]), reason=reason)
            if ed.get("id"):
                emoji_map[ed["id"]] = new_e.id
            res["emojis"] += 1
            bad = 0
        except Exception as ex:
            bad += 1
            if bad >= 5:                       # لیمیتی ئیمۆجی پڕ بووە
                fail("emojis", "limit reached / stopped")
                break

    # ---- ڕێکخستنەکانی بۆت: ئایدی کۆن → نوێ ----
    await upd("⚙️ ڕێکخستنەکانی بۆت...", force=True)
    try:
        idmap = {}
        idmap.update({int(k): v.id for k, v in role_map.items()})
        idmap.update({int(k): v.id for k, v in cat_map.items()})
        idmap.update({int(k): v.id for k, v in chan_map.items()})
        idmap.update({int(k): int(v) for k, v in emoji_map.items()})
        if tpl.get("src_id"):
            idmap[int(tpl["src_id"])] = guild.id
        old_cfg = tpl.get("bot_cfg") or {}
        blob = json.dumps(old_cfg, ensure_ascii=False)
        res["cfg"] = sum(1 for k in idmap if str(k) in blob)
        new_cfg = cc_remap(old_cfg, idmap)
        ct = new_cfg.get("counting")
        if isinstance(ct, dict):                 # ژمارەکە لە سەرەتاوە دەست پێ بکات
            ct["last"] = 0
            ct["last_user"] = None
        config.setdefault(str(guild.id), {}).update(new_cfg)
        save_config()
    except Exception as ex:
        fail("bot settings", ex)
    return res


def cc_summary_embed(title, res):
    desc = (f"🎭 ڕۆڵ: **{res['roles']}**\n"
            f"📁 کاتێگۆری: **{res['cats']}**\n"
            f"💬 کەناڵ: **{res['chans']}**\n"
            f"😀 ئیمۆجی: **{res['emojis']}**\n"
            f"⚙️ ڕێکخستنی بۆت: **کۆپی کرا** ({res['cfg']} ئایدی گۆڕدرا)")
    if res["fallback"]:
        desc += f"\n\nℹ️ {res['fallback']} کەناڵ (Announcement/Forum/Stage) وەک کەناڵی ئاسایی دروست کرا، چونکە Community لەم سێرڤەرە چالاک نییە."
    if res["fail"]:
        desc += f"\n\n⚠️ **{len(res['fail'])} هەڵە:**\n" + "\n".join(f"• {x}" for x in res["fail"][:8])
    return discord.Embed(title=title, description=desc[:4000], color=CC_COLOR)


# ---------- پانێل ----------

def cc_main_embed():
    metas = cc_meta_list()
    e = discord.Embed(
        title="🪞 Server Copy",
        description=("**📥 Copy this server** → ئەم سێرڤەرە هەڵدەگرێت\n"
                     "**تێمپلەیتێک هەڵبژێرە** → لە سێرڤەری ئێستا دایبنێوە"),
        color=CC_COLOR)
    if metas:
        lines = [f"**{m['name']}** ⋅ 🎭 {m['roles']} ⋅ 📁 {m['cats']} ⋅ 💬 {m['chans']} ⋅ 😀 {m['emojis']}"
                 for m in metas]
        e.add_field(name="تێمپلەیتە هەڵگیراوەکان", value="\n".join(lines)[:1000], inline=False)
    else:
        e.add_field(name="تێمپلەیتە هەڵگیراوەکان", value="هێشتا هیچ نییە", inline=False)
    return e


def cc_tpl_embed(meta):
    return discord.Embed(
        title=f"📦 {meta['name']}",
        description=(f"🎭 ڕۆڵ: **{meta['roles']}**\n📁 کاتێگۆری: **{meta['cats']}**\n"
                     f"💬 کەناڵ: **{meta['chans']}**\n😀 ئیمۆجی: **{meta['emojis']}**\n\n"
                     "**📤 Paste** → ڕۆڵ و کەناڵ و ڕێکخستنی بۆت دادەنێت\n"
                     "هیچ شتێک ناسڕدرێتەوە، تەنها زیاد دەکرێت"),
        color=CC_COLOR)


class CcBaseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction):
        if interaction.user.id != CC_OWNER_ID:
            await deny_interaction(interaction)
            return False
        return True


class CcTemplateSelect(discord.ui.Select):
    def __init__(self, metas):
        opts = [discord.SelectOption(
            label=m["name"][:100], value=m["key"],
            description=f"{m['roles']} ڕۆڵ ⋅ {m['cats']} کاتێگۆری ⋅ {m['chans']} کەناڵ ⋅ {m['emojis']} ئیمۆجی")
            for m in metas]
        super().__init__(placeholder="📦 تێمپلەیتێک هەڵبژێرە...", options=opts, row=1)

    async def callback(self, interaction):
        key = self.values[0]
        try:
            meta = cc_load_meta(key)
        except Exception:
            await interaction.response.edit_message(embed=cc_main_embed(), view=CcMainView())
            return
        await interaction.response.edit_message(embed=cc_tpl_embed(meta), view=CcTplView(key))


class CcMainView(CcBaseView):
    def __init__(self):
        super().__init__()
        metas = cc_meta_list()
        if metas:
            self.add_item(CcTemplateSelect(metas))

    @discord.ui.button(label="Copy this server", emoji="📥", style=discord.ButtonStyle.primary, row=0)
    async def copy_btn(self, interaction, button):
        g = interaction.guild
        if g.id in _cc_running:
            await interaction.response.send_message("کارێک لەم سێرڤەرە بەردەوامە، چاوەڕێ بکە.", ephemeral=True)
            return
        _cc_running.add(g.id)
        await interaction.response.edit_message(
            embed=discord.Embed(title="📥 کۆپیکردن", description="دەستی پێکرد...", color=CC_COLOR), view=None)
        upd = cc_updater(interaction, "📥 کۆپیکردن")
        try:
            meta = await cc_copy(g, upd)
            note = discord.Embed(
                title="✅ هەڵگیرا",
                description=(f"**{meta['name']}**\n🎭 {meta['roles']} ⋅ 📁 {meta['cats']} ⋅ "
                             f"💬 {meta['chans']} ⋅ 😀 {meta['emojis']}"),
                color=CC_COLOR)
        except Exception as ex:
            print(f"cc copy error: {ex}", flush=True)
            note = discord.Embed(title="❌ هەڵە", description=str(ex)[:500], color=discord.Color.red())
        finally:
            _cc_running.discard(g.id)
        try:
            await interaction.edit_original_response(embeds=[note, cc_main_embed()], view=CcMainView())
        except Exception:
            pass


class CcTplView(CcBaseView):
    def __init__(self, key):
        super().__init__()
        self.key = key

    @discord.ui.button(label="Paste", emoji="📤", style=discord.ButtonStyle.primary, row=0)
    async def paste_btn(self, interaction, button):
        await self._ask(interaction, "paste")

    @discord.ui.button(label="Choose what to paste", emoji="🎯", style=discord.ButtonStyle.success, row=0)
    async def pick_btn(self, interaction, button):
        try:
            tpl = cc_load(self.key)
        except Exception:
            await interaction.response.edit_message(embed=cc_main_embed(), view=CcMainView())
            return
        pv = CcPickView(self.key, tpl)
        await interaction.response.edit_message(embed=pv.embed(), view=pv)

    @discord.ui.button(label="Delete saved copy", emoji="🗑", style=discord.ButtonStyle.secondary, row=1)
    async def del_btn(self, interaction, button):
        await self._ask(interaction, "delete")

    @discord.ui.button(label="Back", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction, button):
        await interaction.response.edit_message(embed=cc_main_embed(), view=CcMainView())

    async def _ask(self, interaction, mode):
        try:
            meta = cc_load_meta(self.key)
        except Exception:
            await interaction.response.edit_message(embed=cc_main_embed(), view=CcMainView())
            return
        g = interaction.guild
        if mode == "delete":
            text = (f"کۆپییە هەڵگیراوەکەی **{meta['name']}** لە بۆتەکە بسڕدرێتەوە؟\n"
                    "(ئەمە هیچ کاریگەرییەکی لەسەر هیچ سێرڤەرێک نییە)")
        else:
            text = f"تێمپلەیتی **{meta['name']}** لە **{g.name}** دابنرێت؟ (هیچ شتێک ناسڕدرێتەوە)"
        await interaction.response.edit_message(
            embed=discord.Embed(title="دڵنیایت؟", description=text, color=discord.Color.orange()),
            view=CcConfirmView(self.key, mode))


class CcConfirmView(CcBaseView):
    def __init__(self, key, mode, tpl=None, pick=None):
        super().__init__()
        self.key = key
        self.mode = mode
        self.tpl = tpl          # فلتەرکراو (تەنها ئەوەی هەڵت بژاردووە)
        self.pick = pick

    @discord.ui.button(label="بەڵێ", emoji="✅", style=discord.ButtonStyle.success, row=0)
    async def yes_btn(self, interaction, button):
        if self.mode == "delete":
            cc_delete(self.key)
            await interaction.response.edit_message(embed=cc_main_embed(), view=CcMainView())
            return
        await self._run(interaction)

    @discord.ui.button(label="نەخێر", emoji="✖️", style=discord.ButtonStyle.secondary, row=0)
    async def no_btn(self, interaction, button):
        if self.pick is not None:
            pv = self.pick.clone()
            await interaction.response.edit_message(embed=pv.embed(), view=pv)
            return
        try:
            meta = cc_load_meta(self.key)
            await interaction.response.edit_message(embed=cc_tpl_embed(meta), view=CcTplView(self.key))
        except Exception:
            await interaction.response.edit_message(embed=cc_main_embed(), view=CcMainView())

    async def _run(self, interaction):
        g = interaction.guild
        user = interaction.user
        # سێرڤەری سەرچاوە هەمیشە پارێزراوە، هیچ شتێکی تێدا دانانرێت
        try:
            src_id = cc_load_meta(self.key).get("src_id")
        except Exception:
            src_id = None
        if g.id in cc_sources() or g.id == src_id or g.id in CC_PROTECTED_GUILDS:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="🛡 پارێزراوە",
                    description="ئەم سێرڤەرە سەرچاوەی کۆپییە و Paste ی تێدا ناکرێت. لە سێرڤەرێکی نوێ بەکاری بهێنە.",
                    color=discord.Color.orange()),
                view=CcMainView())
            return
        # دەبێت لەو سێرڤەرە Administrator بیت (یان خاوەن)
        if g.owner_id != user.id and user.id != BOT_OWNER_ID and not user.guild_permissions.administrator:
            await deny_interaction(interaction)
            return
        perms = g.me.guild_permissions
        if not (perms.administrator or (perms.manage_channels and perms.manage_roles)):
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ دەسەڵات نییە",
                    description="بۆتەکە پێویستی بە **Administrator** (یان Manage Channels + Manage Roles) هەیە لەم سێرڤەرە.",
                    color=discord.Color.red()),
                view=CcMainView())
            return
        if g.id in _cc_running:
            await interaction.response.send_message("کارێک لەم سێرڤەرە بەردەوامە، چاوەڕێ بکە.", ephemeral=True)
            return
        try:
            tpl = self.tpl if self.tpl is not None else cc_load(self.key)
        except Exception:
            await interaction.response.edit_message(embed=cc_main_embed(), view=CcMainView())
            return

        _cc_running.add(g.id)
        title = "📤 Paste"
        await interaction.response.edit_message(
            embed=discord.Embed(title=title, description="دەستی پێکرد...", color=CC_COLOR), view=None)
        upd = cc_updater(interaction, title)
        try:
            res = await cc_paste(g, tpl, upd)
            note = cc_summary_embed("✅ تەواو بوو", res)
        except Exception as ex:
            print(f"cc paste error: {ex}", flush=True)
            note = discord.Embed(title="❌ هەڵە", description=str(ex)[:500], color=discord.Color.red())
        finally:
            _cc_running.discard(g.id)
        try:
            await interaction.edit_original_response(embeds=[note, cc_main_embed()], view=CcMainView())
        except Exception:
            # کەناڵی فەرمانەکە ڕەنگە سڕابێتەوە / تۆکنی ئینتەراکشن بەسەرچووبێت
            pass


# ---------- هەڵبژاردنی کاتێگۆری و شتەکان بۆ Paste ----------

CC_NOCAT = 0          # "کەناڵی بێ کاتێگۆری"
CC_ROLE_MODES = {"all": "هەموو", "needed": "تەنها پێویست", "none": "هیچ"}


def cc_filter_tpl(tpl, sel, roles_mode, emojis_on, cfg_on, settings_on):
    cats = [c for c in tpl["cats"] if c["id"] in sel]
    cat_ids = {c["id"] for c in cats}
    chans = [c for c in tpl["chans"]
             if c["cat"] in cat_ids or (c["cat"] is None and CC_NOCAT in sel)]
    if roles_mode == "all":
        roles = list(tpl["roles"])
    elif roles_mode == "needed":
        need = set()
        for x in cats + chans:
            need.update(o["id"] for o in x.get("ow", []))
        roles = [r for r in tpl["roles"] if r["id"] in need]
    else:
        roles = []
    out = dict(tpl)
    out.update(
        cats=cats, chans=chans, roles=roles,
        emojis=list(tpl.get("emojis", [])) if emojis_on else [],
        bot_cfg=tpl.get("bot_cfg", {}) if cfg_on else {},
        skip_settings=not settings_on,
        skip_everyone=(roles_mode != "all"),
    )
    return out


class CcPickSelect(discord.ui.Select):
    def __init__(self, pv, chunk, row):
        opts = [discord.SelectOption(label=label[:100], value=str(cid), description=desc[:100],
                                     default=(cid in pv.sel))
                for cid, label, desc in chunk]
        super().__init__(placeholder="📁 کاتێگۆریەکان هەڵبژێرە...", options=opts,
                         min_values=0, max_values=len(opts), row=row)
        self.pv = pv
        self.chunk_ids = {c[0] for c in chunk}

    async def callback(self, interaction):
        self.pv.sel -= self.chunk_ids
        self.pv.sel |= {int(v) for v in self.values}
        await self.pv.refresh(interaction)


class CcPickView(CcBaseView):
    def __init__(self, key, tpl, sel=None, roles_mode="all", emojis_on=True, cfg_on=True, settings_on=True):
        super().__init__()
        self.key, self.tpl = key, tpl
        self.sel = set(sel or ())
        self.roles_mode, self.emojis_on = roles_mode, emojis_on
        self.cfg_on, self.settings_on = cfg_on, settings_on

        counts = {}
        for ch in tpl["chans"]:
            counts[ch["cat"]] = counts.get(ch["cat"], 0) + 1
        entries = []
        if counts.get(None):
            entries.append((CC_NOCAT, "📂 کەناڵی بێ کاتێگۆری", f"{counts[None]} کەناڵ"))
        for c in sorted(tpl["cats"], key=lambda c: c["pos"]):
            entries.append((c["id"], "📁 " + (c["name"] or "-"), f"{counts.get(c['id'], 0)} کەناڵ"))
        entries = entries[:75]
        chunks = [entries[i:i + 25] for i in range(0, len(entries), 25)]
        for r, chunk in enumerate(chunks):
            self.add_item(CcPickSelect(self, chunk, r))
        r0 = len(chunks)

        def btn(label, style, row, cb, emoji=None):
            b = discord.ui.Button(label=label, style=style, row=row, emoji=emoji)
            b.callback = cb
            self.add_item(b)

        sec, suc, pri = discord.ButtonStyle.secondary, discord.ButtonStyle.success, discord.ButtonStyle.primary
        on = lambda v: suc if v else sec
        btn("Select all", sec, r0, self.all_cb, "✅")
        btn("Clear", sec, r0, self.none_cb, "✖️")
        btn(f"Roles: {CC_ROLE_MODES[roles_mode]}", on(roles_mode != "none"), r0, self.roles_cb, "🎭")
        btn("Emojis: " + ("ON" if emojis_on else "OFF"), on(emojis_on), r0, self.emoji_cb, "😀")
        btn("Bot settings: " + ("ON" if cfg_on else "OFF"), on(cfg_on), r0 + 1, self.cfg_cb, "⚙️")
        btn("Server name/icon: " + ("ON" if settings_on else "OFF"), on(settings_on), r0 + 1, self.set_cb, "🖼")
        btn("Paste", pri, r0 + 1, self.paste_cb, "📤")
        btn("Back", sec, r0 + 1, self.back_cb, "↩️")

    def clone(self):
        return CcPickView(self.key, self.tpl, self.sel, self.roles_mode,
                          self.emojis_on, self.cfg_on, self.settings_on)

    def filtered(self):
        return cc_filter_tpl(self.tpl, self.sel, self.roles_mode, self.emojis_on, self.cfg_on, self.settings_on)

    def embed(self):
        f = self.filtered()
        names = [c["name"] for c in f["cats"]]
        if CC_NOCAT in self.sel:
            names.insert(0, "کەناڵی بێ کاتێگۆری")
        listing = "\n".join(f"• {n}" for n in names[:15]) or "هیچ نییە"
        if len(names) > 15:
            listing += f"\n... +{len(names) - 15}"
        desc = (f"**ئەمەی هەڵت بژاردووە:**\n{listing}\n\n"
                f"📁 کاتێگۆری: **{len(f['cats'])}** ⋅ 💬 کەناڵ: **{len(f['chans'])}**\n"
                f"🎭 ڕۆڵ: **{len(f['roles'])}** ⋅ 😀 ئیمۆجی: **{len(f['emojis'])}**\n"
                f"⚙️ ڕێکخستنی بۆت: **{'بەڵێ' if self.cfg_on else 'نەخێر'}** ⋅ "
                f"🖼 ناو/ئایکۆنی سێرڤەر: **{'بەڵێ' if self.settings_on else 'نەخێر'}**")
        return discord.Embed(title=f"🎯 {self.tpl.get('name', '')} — هەڵبژاردن", description=desc[:4000],
                             color=CC_COLOR)

    async def refresh(self, interaction):
        pv = self.clone()
        await interaction.response.edit_message(embed=pv.embed(), view=pv)

    async def all_cb(self, interaction):
        ids = {c["id"] for c in self.tpl["cats"]}
        if any(c["cat"] is None for c in self.tpl["chans"]):
            ids.add(CC_NOCAT)
        self.sel = ids
        await self.refresh(interaction)

    async def none_cb(self, interaction):
        self.sel = set()
        await self.refresh(interaction)

    async def roles_cb(self, interaction):
        order = ["all", "needed", "none"]
        self.roles_mode = order[(order.index(self.roles_mode) + 1) % 3]
        await self.refresh(interaction)

    async def emoji_cb(self, interaction):
        self.emojis_on = not self.emojis_on
        await self.refresh(interaction)

    async def cfg_cb(self, interaction):
        self.cfg_on = not self.cfg_on
        await self.refresh(interaction)

    async def set_cb(self, interaction):
        self.settings_on = not self.settings_on
        await self.refresh(interaction)

    async def back_cb(self, interaction):
        try:
            meta = cc_load_meta(self.key)
            await interaction.response.edit_message(embed=cc_tpl_embed(meta), view=CcTplView(self.key))
        except Exception:
            await interaction.response.edit_message(embed=cc_main_embed(), view=CcMainView())

    async def paste_cb(self, interaction):
        f = self.filtered()
        if not (f["cats"] or f["chans"] or f["roles"] or f["emojis"] or self.cfg_on or self.settings_on):
            await interaction.response.send_message("هیچ شتێک هەڵنەبژێردراوە.", ephemeral=True)
            return
        g = interaction.guild
        text = (f"ئەمە لە **{g.name}** دابنرێت؟ (هیچ شتێک ناسڕدرێتەوە)\n\n"
                f"📁 {len(f['cats'])} کاتێگۆری ⋅ 💬 {len(f['chans'])} کەناڵ ⋅ "
                f"🎭 {len(f['roles'])} ڕۆڵ ⋅ 😀 {len(f['emojis'])} ئیمۆجی")
        await interaction.response.edit_message(
            embed=discord.Embed(title="دڵنیایت؟", description=text, color=discord.Color.orange()),
            view=CcConfirmView(self.key, "paste", tpl=f, pick=self))


@bot.tree.command(name="create_channels", description="کۆپیکردن و دانانەوەی سێرڤەر (تەنها خاوەنی بۆت)")
@app_commands.guild_only()
async def create_channels_cmd(interaction: discord.Interaction):
    if interaction.user.id != CC_OWNER_ID:
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(embed=cc_main_embed(), view=CcMainView(), ephemeral=True)


# =========================================================
# 29e. SONG TEXTS  (/song-texts)  — هەموو کەسێک دەتوانێت بەکاری بهێنێت
# =========================================================
# پانێلێک (تەنها بۆ خۆی دیارە):
#   🎤 ناوی گۆرانیبێژ + ناوی گۆرانی  |  📝 تێکست  |  🖼 وێنە  |  🎧 فایل (MP3 / ئۆدیۆ / ڤیدیۆ)
#   🔤 فۆنتی ناوی گۆرانیبێژ  |  👁 Preview  |  📤 Send
# Send → بۆردێکی جوان + وێنە + فایلی MP3 بە شێوەی پەبلیک دەنێرێت بۆ ناو چاتەکە
# ڤیدیۆ یان ئۆدیۆی تر خۆکار دەگۆڕدرێت بۆ MP3 (پێویستی بە ffmpeg هەیە):
#   Railway: لە requirements.txt بنووسە  imageio-ffmpeg  (یان ffmpeg لە nixpacks زیاد بکە)

import io as _io
import shutil as _shutil
import tempfile as _tempfile

SONG_COLOR = discord.Color.from_rgb(250, 205, 235)
SONG_COOLDOWN = 30                    # چرکە لە نێوان دوو ناردنی یەک کەس
SONG_WAIT = 120                       # چرکە بۆ ناردنی وێنە/فایل
SONG_MAX_IMG = 8 * 1024 * 1024
SONG_MAX_IN = 100 * 1024 * 1024       # گەورەترین فایلی ڤیدیۆ/ئۆدیۆ کە وەربگیرێت
SONG_AUDIO_EXT = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus", ".wma", ".oga", ".amr"}
SONG_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp", ".flv", ".wmv"}
SONG_IMG_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
_song_last = {}


# ---------- فۆنتەکان (پیتی لاتینی) ----------

def _song_range(up, low):
    def f(ch):
        o = ord(ch)
        if 65 <= o <= 90:
            return chr(up + o - 65)
        if 97 <= o <= 122:
            return chr(low + o - 97)
        return ch
    return f


_SMALLCAPS = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"))

SONG_FONTS = {
    "script":     ("Script",      _song_range(0x1D4D0, 0x1D4EA)),
    "fraktur":    ("Fraktur",     _song_range(0x1D56C, 0x1D586)),
    "bold":       ("Bold",        _song_range(0x1D400, 0x1D41A)),
    "bolditalic": ("Bold Italic", _song_range(0x1D468, 0x1D482)),
    "mono":       ("Mono",        _song_range(0x1D670, 0x1D68A)),
    "smallcaps":  ("Small Caps",  lambda ch: _SMALLCAPS.get(ch.lower(), ch) if ch.isascii() and ch.isalpha() else ch),
    "normal":     ("Normal",      lambda ch: ch),
}


def song_style(text, font):
    fn = SONG_FONTS.get(font, SONG_FONTS["script"])[1]
    return "".join(fn(c) for c in text)


# ---------- یارمەتیدەرەکان ----------

class SongSession:
    def __init__(self):
        self.artist = ""
        self.title = ""
        self.lyrics = ""
        self.cover = None
        self.cover_fn = None
        self.audio = None
        self.audio_ext = ".mp3"
        self.font = "script"
        self.note = ""
        self.friends = []                 # مێنشنی کەسانی تر (تەنها وەک تاگ، بێ وێنە)

    def clear_files(self):
        self.cover = None
        self.audio = None


def song_filename(s):
    base = f"{s.artist} - {s.title}" if s.artist else s.title
    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", base)
    base = re.sub(r"\s+", " ", base).strip()[:80] or "song"
    return base + s.audio_ext


def song_split(text, limit=3500):
    pages, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                pages.append(cur)
                cur = ""
            pages.append(line[:limit])
            line = line[limit:]
        add = (cur + "\n" + line) if cur else line
        if len(add) > limit:
            pages.append(cur)
            cur = line
        else:
            cur = add
    if cur:
        pages.append(cur)
    return pages or [""]


def song_size(n):
    return f"{n / 1024 / 1024:.1f} MB"


SONG_CENTER_W = 26      # پانی دیاریکراوی دیزاینەکە بۆ ناوەڕاست کردن (ئەگەر کەم/زۆر لە ناوەڕاست بوو ئەمە بگۆڕە)
SONG_BLANK = "\u2800"   # بۆشایی نادیار بۆ ناوەڕاست کردن (Discord بۆشایی ئاسایی دەسڕێتەوە)


def song_signature(s, user):
    """ئیمزا: مێنشنی خۆت + کەسانی تر، لە ناوەڕاستدا بە شێوازی جوان، لەناو هەمان بۆکس"""
    members = [(user.mention, user.display_name)]
    for uid, name, mention in s.friends:
        if uid != user.id:
            members.append((mention, name))
    width = sum(len(n) + 1 for _, n in members) + 3 * len(members) + 2 * (len(members) - 1)
    pad = max(0, int((SONG_CENTER_W - 1.5 * width) / 3))
    body = " ✧ ".join(m for m, _ in members)
    return f"### {SONG_BLANK * pad}♡ {body} ♡"


def song_build(s, user):
    """بۆرد(ەکان): یەکەم بۆرد = سەر + ئیمزا (مێنشن) + تێکست، ئەگەر تێکست درێژ بوو بۆردی زیاتر"""
    text = re.sub(r"\n{3,}", "\n\n", s.lyrics.strip())
    pages = song_split(discord.utils.escape_markdown(text))
    head = "₊˚⊹ ♡ ⋆｡˚ ✧ ˚｡⋆ ♡ ⊹˚₊"
    # ئیمزا پێش تێکستەکە دادەنرێت، چونکە >>> هەموو شتێکی دوای خۆی دەخاتە ناو quote
    desc = head + "\n" + song_signature(s, user) + (f"\n\n>>> {pages[0]}" if text else "")
    e = discord.Embed(title=f"♪ {s.title}"[:250], description=desc[:4000], color=SONG_COLOR)
    if s.artist:
        e.set_author(name=song_style(s.artist, s.font)[:250])
    # وێنەی خۆت: ئەگەر وێنەی گۆرانی نەبوو وەک thumbnail، ئەگەر هەبوو لە footer
    if s.cover_fn:
        e.set_thumbnail(url=f"attachment://{s.cover_fn}")
        e.set_footer(text=song_style(user.display_name, s.font)[:100], icon_url=user.display_avatar.url)
    else:
        e.set_thumbnail(url=user.display_avatar.url)
    embeds = [e]
    if text:
        for p in pages[1:]:
            embeds.append(discord.Embed(description=f">>> {p}"[:4000], color=SONG_COLOR))
    return embeds


def song_files(s, with_audio):
    files = []
    if s.cover and s.cover_fn:
        files.append(discord.File(_io.BytesIO(s.cover), filename=s.cover_fn))
    if with_audio and s.audio:
        files.append(discord.File(_io.BytesIO(s.audio), filename=song_filename(s)))
    return files


def song_panel_embed(s):
    ok, no = "✅", "⬜"
    artist = song_style(s.artist, s.font) if s.artist else no
    lines = [
        f"🎤 **گۆرانیبێژ:** {artist}",
        f"🎵 **گۆرانی:** {s.title or no}",
        f"📝 **تێکست:** {f'{ok} {len(s.lyrics):,} پیت' if s.lyrics else no}",
        f"🖼 **وێنە:** {f'{ok} {song_size(len(s.cover))}' if s.cover else no}",
        f"🎧 **فایل:** {f'{ok} {song_filename(s)} ⋅ {song_size(len(s.audio))}' if s.audio else no}",
        f"🔤 **فۆنت:** {SONG_FONTS[s.font][0]}",
        f"👥 **مێنشن:** {' '.join(m for _, _, m in s.friends) if s.friends else no}",
    ]
    e = discord.Embed(
        title="🎶 Song Texts",
        description="\n".join(lines) + "\n\n-# هەموو بەشەکان ئارەزوومەندانەن، تەنها ناوی گۆرانی پێویستە ⋆ پاشان 👁 Preview و 📤 Send",
        color=SONG_COLOR)
    if s.note:
        e.add_field(name="ℹ️", value=s.note[:500], inline=False)
    return e


# ---------- ffmpeg ----------

def song_ffmpeg():
    p = _shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


async def song_to_mp3(data, in_name, limit):
    """(bytes, None) یان (None, هۆکار)"""
    ff = song_ffmpeg()
    if not ff:
        return None, "no-ffmpeg"
    ext = os.path.splitext(in_name)[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
        ext = ".bin"
    with _tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in" + ext)
        dst = os.path.join(d, "out.mp3")
        with open(src, "wb") as f:
            f.write(data)
        for br in ("128k", "96k", "64k"):
            proc = await asyncio.create_subprocess_exec(
                ff, "-y", "-i", src, "-vn", "-map", "0:a:0", "-c:a", "libmp3lame",
                "-b:a", br, "-ar", "44100", dst,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(proc.wait(), timeout=300)
            except asyncio.TimeoutError:
                proc.kill()
                return None, "timeout"
            if proc.returncode != 0 or not os.path.exists(dst):
                return None, "ffmpeg-fail"
            with open(dst, "rb") as f:
                out = f.read()
            if len(out) <= limit:
                return out, None
        return None, "too-big"


# ---------- مۆدالەکان ----------

class SongInfoModal(discord.ui.Modal, title="ناوی گۆرانیبێژ و گۆرانی"):
    def __init__(self, view):
        super().__init__()
        self.sv = view
        self.artist = discord.ui.TextInput(
            label="ناوی گۆرانیبێژ", default=view.s.artist, required=False, max_length=60)
        self.song = discord.ui.TextInput(
            label="ناوی گۆرانی", default=view.s.title, required=True, max_length=80)
        self.add_item(self.artist)
        self.add_item(self.song)

    async def on_submit(self, interaction):
        s = self.sv.s
        s.artist = self.artist.value.strip()
        s.title = self.song.value.strip()
        s.note = ""
        await interaction.response.edit_message(embed=song_panel_embed(s), view=self.sv)


class SongLyricsModal(discord.ui.Modal, title="تێکستی گۆرانی"):
    def __init__(self, view):
        super().__init__()
        self.sv = view
        self.text = discord.ui.TextInput(
            label="تێکست (بەتاڵ = لابردن)", style=discord.TextStyle.paragraph,
            default=view.s.lyrics or None, required=False, max_length=4000)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        s = self.sv.s
        s.lyrics = self.text.value.strip()
        s.note = ""
        await interaction.response.edit_message(embed=song_panel_embed(s), view=self.sv)


class SongFontSelect(discord.ui.Select):
    def __init__(self, current):
        opts = [discord.SelectOption(label=name, value=k, description=song_style("Marsa", k),
                                     default=(k == current))
                for k, (name, _) in SONG_FONTS.items()]
        super().__init__(placeholder="🔤 فۆنتی ناوی گۆرانیبێژ...", options=opts, row=1)

    async def callback(self, interaction):
        sv = self.view
        sv.s.font = self.values[0]
        for o in self.options:
            o.default = (o.value == sv.s.font)
        await interaction.response.edit_message(embed=song_panel_embed(sv.s), view=sv)


class SongMentionSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="👥 مێنشنی کەسانی تر (ئارەزوومەندانە، تا ٥ کەس)...",
                         min_values=0, max_values=5, row=3)

    async def callback(self, interaction):
        sv = self.view
        sv.s.friends = [(u.id, u.display_name, u.mention) for u in self.values if not u.bot]
        sv.s.note = ""
        await interaction.response.edit_message(embed=song_panel_embed(sv.s), view=sv)


# ---------- پانێل ----------

class SongView(discord.ui.View):
    def __init__(self, root, session):
        super().__init__(timeout=14 * 60)
        self.root = root                      # ئینتەراکشنی /song-texts بۆ نوێکردنەوەی پانێل
        self.s = session
        self.author_id = root.user.id
        self.add_item(SongFontSelect(session.font))
        self.add_item(SongMentionSelect())

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            try:
                await interaction.response.send_message(
                    "ئەمە پانێلی کەسێکی ترە، خۆت /song-texts بکەرەوە 🌷", ephemeral=True, delete_after=8)
            except Exception:
                pass
            return False
        return True

    async def on_timeout(self):
        self.s.clear_files()
        try:
            await self.root.edit_original_response(
                embed=discord.Embed(description="⏱ کاتەکە بەسەرچوو، دووبارە /song-texts بکەرەوە", color=SONG_COLOR),
                view=None)
        except Exception:
            pass

    async def _refresh(self):
        try:
            await self.root.edit_original_response(embed=song_panel_embed(self.s), view=self)
        except Exception:
            pass

    async def _ask_upload(self, interaction, prompt):
        """چاوەڕێی ناردنی فایل دەکات لەم کەناڵە. (message, attachment) یان None"""
        await interaction.response.send_message(prompt, ephemeral=True)

        def check(m):
            return (m.author.id == self.author_id and m.channel.id == interaction.channel_id
                    and m.attachments)
        try:
            m = await bot.wait_for("message", check=check, timeout=SONG_WAIT)
        except asyncio.TimeoutError:
            await interaction.edit_original_response(content="⏱ کات بەسەرچوو، دووبارە هەوڵ بدەوە")
            return None
        return m, m.attachments[0]

    async def _done(self, interaction, text):
        self.s.note = text
        await self._refresh()
        try:
            await interaction.edit_original_response(content=text)
            await asyncio.sleep(4)
            await interaction.delete_original_response()
        except Exception:
            pass

    @discord.ui.button(label="Artist & Song", emoji="🎤", style=discord.ButtonStyle.primary, row=0)
    async def info_btn(self, interaction, button):
        await interaction.response.send_modal(SongInfoModal(self))

    @discord.ui.button(label="Lyrics", emoji="📝", style=discord.ButtonStyle.secondary, row=0)
    async def lyrics_btn(self, interaction, button):
        await interaction.response.send_modal(SongLyricsModal(self))

    @discord.ui.button(label="Cover", emoji="🖼", style=discord.ButtonStyle.secondary, row=0)
    async def cover_btn(self, interaction, button):
        got = await self._ask_upload(
            interaction, f"🖼 وێنەی گۆرانییەکە لەم کەناڵە بنێرە ({SONG_WAIT} چرکە)")
        if not got:
            return
        m, att = got
        ct = (att.content_type or "").split(";")[0].lower()
        if ct not in SONG_IMG_EXT:
            await self._done(interaction, "❌ تەنها وێنە (PNG / JPG / WEBP / GIF) قبوڵ دەکرێت")
            return
        if att.size > SONG_MAX_IMG:
            await self._done(interaction, f"❌ وێنەکە گەورەترە لە {song_size(SONG_MAX_IMG)}")
            return
        data = await att.read()
        try:
            await m.delete()                 # نامەی وێنەکەی خۆت دەسڕێتەوە (ئەگەر دەسەڵات هەبوو)
        except Exception:
            pass
        self.s.cover = data
        self.s.cover_fn = f"cover.{SONG_IMG_EXT[ct]}"
        await self._done(interaction, "✅ وێنە وەرگیرا")

    @discord.ui.button(label="Audio / Video", emoji="🎧", style=discord.ButtonStyle.secondary, row=0)
    async def audio_btn(self, interaction, button):
        got = await self._ask_upload(
            interaction,
            f"🎧 فایلی گۆرانی (MP3 / ئۆدیۆ) یان ڤیدیۆ لەم کەناڵە بنێرە ({SONG_WAIT} چرکە)\n"
            "-# ڤیدیۆ خۆکار دەگۆڕدرێت بۆ MP3")
        if not got:
            return
        m, att = got
        name = att.filename or "file"
        ext = os.path.splitext(name)[1].lower()
        ct = (att.content_type or "").split(";")[0].lower()
        is_audio = ct.startswith("audio/") or ext in SONG_AUDIO_EXT
        is_video = ct.startswith("video/") or ext in SONG_VIDEO_EXT
        if not (is_audio or is_video):
            await self._done(interaction, "❌ تەنها ئۆدیۆ (MP3...) یان ڤیدیۆ قبوڵ دەکرێت")
            return
        if att.size > SONG_MAX_IN:
            await self._done(interaction, f"❌ فایلەکە گەورەترە لە {song_size(SONG_MAX_IN)}")
            return
        limit = interaction.guild.filesize_limit
        try:
            await interaction.edit_original_response(content="⏳ فایلەکە وەردەگیرێت...")
            data = await att.read()
        except Exception:
            await self._done(interaction, "❌ نەتوانرا فایلەکە وەربگیرێت")
            return
        try:
            await m.delete()
        except Exception:
            pass

        is_mp3 = (ext == ".mp3" or ct == "audio/mpeg") and not is_video
        if is_mp3 and len(data) <= limit:
            self.s.audio, self.s.audio_ext = data, ".mp3"
            await self._done(interaction, "✅ فایلی MP3 وەرگیرا")
            return

        await interaction.edit_original_response(content="⏳ دەگۆڕدرێت بۆ MP3 ...")
        out, err = await song_to_mp3(data, name, limit)
        if out:
            self.s.audio, self.s.audio_ext = out, ".mp3"
            await self._done(interaction, "✅ گۆڕدرا بۆ MP3 و وەرگیرا")
        elif err == "no-ffmpeg":
            if len(data) > limit:
                await self._done(interaction, "❌ فایلەکە گەورەترە لە سنووری ئەم سێرڤەرە و ffmpeg نییە بۆ بچووککردنەوەی")
                return
            self.s.audio = data
            self.s.audio_ext = ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext) else ".mp3"
            await self._done(interaction, "⚠️ ffmpeg نییە، فایلەکە وەک خۆی دەنێردرێت (نەگۆڕدرا بۆ MP3)")
        elif err == "too-big":
            await self._done(interaction, "❌ تەنانەت دوای بچووککردنەوەش گەورەترە لە سنووری سێرڤەر")
        else:
            await self._done(interaction, "❌ نەتوانرا بگۆڕدرێت بۆ MP3، فایلەکە دڵنیا بکەرەوە ئۆدیۆی تێدایە")

    @discord.ui.button(label="Preview", emoji="👁", style=discord.ButtonStyle.secondary, row=2)
    async def preview_btn(self, interaction, button):
        s = self.s
        if not s.title:
            await interaction.response.send_message("سەرەتا ناوی گۆرانی بنووسە 🎤", ephemeral=True, delete_after=8)
            return
        extra = ""
        if s.audio:
            extra = f"\n🎧 `{song_filename(s)}` ⋅ {song_size(len(s.audio))}"
        await interaction.response.send_message(
            content=f"👁 Preview{extra}",
            embeds=song_build(s, interaction.user)[:1],
            files=song_files(s, with_audio=False), ephemeral=True)

    @discord.ui.button(label="Send", emoji="📤", style=discord.ButtonStyle.success, row=2)
    async def send_btn(self, interaction, button):
        s = self.s
        if not s.title:
            await interaction.response.send_message("سەرەتا ناوی گۆرانی بنووسە 🎤", ephemeral=True, delete_after=8)
            return
        if not (s.lyrics or s.audio or s.cover):
            await interaction.response.send_message(
                "لانیکەم تێکست، وێنە یان فایلێک زیاد بکە 🌷", ephemeral=True, delete_after=8)
            return
        wait = SONG_COOLDOWN - (time.time() - _song_last.get(interaction.user.id, 0))
        if wait > 0:
            await interaction.response.send_message(
                f"چاوەڕێ بکە {int(wait) + 1} چرکە 🌷", ephemeral=True, delete_after=8)
            return
        limit = interaction.guild.filesize_limit
        if len(s.cover or b"") + len(s.audio or b"") > limit:
            await interaction.response.send_message(
                f"❌ کۆی فایلەکان گەورەترە لە سنووری سێرڤەر ({song_size(limit)})", ephemeral=True, delete_after=10)
            return

        _song_last[interaction.user.id] = time.time()
        await interaction.response.edit_message(
            embed=discord.Embed(description="📤 دەنێردرێت...", color=SONG_COLOR), view=None)
        try:
            embeds = song_build(s, interaction.user)
            nomention = discord.AllowedMentions.none()      # مێنشن تەنها لەناو ئیمبێد دەردەکەوێت، بێ نوتیفیکەیشن
            await interaction.channel.send(
                embed=embeds[0], files=song_files(s, with_audio=True), allowed_mentions=nomention)
            for extra in embeds[1:]:
                await interaction.channel.send(embed=extra, allowed_mentions=nomention)
            result = discord.Embed(description="✅ ناردرا ♡", color=SONG_COLOR)
        except discord.Forbidden:
            _song_last.pop(interaction.user.id, None)
            result = discord.Embed(
                description="❌ بۆتەکە دەسەڵاتی Send Messages / Embed Links / Attach Files لەم کەناڵە نییە",
                color=discord.Color.red())
        except Exception as ex:
            _song_last.pop(interaction.user.id, None)
            print(f"song send error: {ex}", flush=True)
            result = discord.Embed(description="❌ هەڵەیەک ڕوویدا، دووبارە هەوڵ بدەوە", color=discord.Color.red())
        s.clear_files()
        self.stop()
        try:
            await interaction.edit_original_response(embed=result, view=None)
        except Exception:
            pass

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def cancel_btn(self, interaction, button):
        self.s.clear_files()
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(description="✖️ هەڵوەشایەوە", color=SONG_COLOR), view=None)


@bot.tree.command(name="song-texts", description="تێکست، وێنە و فایلی گۆرانی بە شێوازێکی جوان بنێرە")
@app_commands.guild_only()
async def song_texts_cmd(interaction: discord.Interaction):
    s = SongSession()
    await interaction.response.send_message(
        embed=song_panel_embed(s), view=SongView(interaction, s), ephemeral=True)



# =========================================================
# 42. /help  +  BIO ی بۆتەکە
# =========================================================

HELP_COLOR = discord.Color.from_rgb(250, 205, 235)

BOT_BIO = (
    "Server Management & Activity Bot\n"
    "\n"
    "🛡 **Moderation:** Mute ⋆ Bfra ⋆ Safika\n"
    "🔐 **Security:** Anti-Nuke ⋆ Logs\n"
    "✨ **Fun:** XP ⋆ Ship ⋆ Song Texts\n"
    "📖 **Help:** /help\n"
    "\n"
    "👑 **Developer:** 𝗱𝘂𝗱𝘂𝘂"
)[:400]

HELP_SECTIONS = {
    "home": ("📖", "سەرەتا"),
    "mod": ("🛡", "مۆدەراسیۆن"),
    "setup": ("⚙️", "ڕێکخستنی سێرڤەر"),
    "roles": ("👑", "دەسەڵات و ڕۆڵەکان"),
    "protect": ("🔐", "پاراستن و چاودێری"),
    "fun": ("🎉", "چالاکی و خۆشی"),
    "owner": ("🧰", "تایبەت"),
}

HELP_TEXT = {
    "mod": (
        "**ئەم کۆمانانە بێ `/` ـن، تەنها لە چات بیاننووسە** (تاگی کەسەکە بکە یان ڕیپلەی نامەکەی بکە)\n\n"
        "🔇 **`mute @کەس`**\n└ ئەندام Mute دەکات: ڕۆڵی Muted دەدرێت و نامەکانی دەسڕدرێنەوە.\n"
        "🔊 **`unmute @کەس`**\n└ Mute لادەبات.\n"
        "🔨 **`bfra @کەس`**\n└ ئەندام Ban دەکات (دەردەچێت لە سێرڤەر).\n"
        "♻️ **`unban ئایدی`**\n└ Ban لادەبات، ئایدی ئەندامەکە بنووسە، وەک `unban 123456789012345678`.\n"
        "🧹 **`safika 10`**\n└ ژمارەیەک نامە دەسڕێتەوە لە کەناڵەکە (تا 1000).\n"
        "🔒 **`lock`** / 🔓 **`unlock`**\n└ کەناڵەکە دادەخات یان دەیکاتەوە بۆ نووسین (پێویستی بە Manage Channels هەیە).\n\n"
        "-# کێ دەتوانێت: ڕۆڵی Mute بە `/rolemute` ، Bfra بە `/roleban` ، Safika بە `/rolesafika` دیاری دەکرێت."
    ),
    "setup": (
        "**تەنها Administrator / دیڤیلۆپەر**\n\n"
        "📜 **`/setlog`**\n└ کەناڵی هەر جۆرە لۆگێک دیاری دەکات (Chat، Voice، Ban، Role، Channel ...).\n"
        "📚 **`/setlogall`**\n└ هەموو لۆگەکان دەخاتە یەک کەناڵەوە.\n"
        "🔇 **`/setmuterole`**\n└ ئەو ڕۆڵە دیاری دەکات کە لە کاتی Mute دەدرێت.\n"
        "🎁 **`/autorole`**\n└ چەند ڕۆڵێک کە خۆکار دەدرێن بە ئەندامی نوێ.\n"
        "👋 **`/welcome`**\n└ کەناڵەکانی بەخێرهاتن و نامەی بەخێرهاتن.\n"
        "🔢 **`/counting`**\n└ کەناڵی ژماردن (1، 2، 3 ...) و یاساکانی.\n"
        "🗂 **`/config`**\n└ هەموو ڕێکخستنەکانی ئەم سێرڤەرە پیشان دەدات."
    ),
    "roles": (
        "**کێ بتوانێت چی بکات**\n\n"
        "🧑‍💻 **`/setdev`**\n└ ڕۆڵی دیڤیلۆپەر (تەنها خاوەنی سێرڤەر).\n"
        "🔇 **`/rolemute`** ⋅ 🔨 **`/roleban`** ⋅ 🧹 **`/rolesafika`**\n└ ئەو ڕۆڵانەی دەتوانن Mute / Bfra / Safika بکەن.\n"
        "⭐ **`/rolestaff`**\n└ ئەو ڕۆڵانەی دەتوانن `/staff` بەکاربهێنن.\n"
        "🛠 **`/setstaff`**\n└ ڕۆڵەکانی Lady Staff و Boy Staff دیاری دەکات.\n"
        "🎖 **`/staff`**\n└ ڕۆڵی ستاف دەدات بە ئەندام (Lady / Boy Staff).\n"
        "🎨 **`/rangi-role`**\n└ ڕەنگی ڕۆڵ دەگۆڕێت، کۆدی ڕەنگ بنووسە وەک `#FF0000`.\n"
        "✅ **`/regadan-ranggorin`**\n└ ڕۆڵ و کەسانی ڕێگەپێدراو بۆ گۆڕینی ڕەنگ.\n"
        "🚫 **`/regri`**\n└ قەدەغەکردن یان ڕێگەپێدانی گۆڕینی ڕەنگ بۆ ئەندامێک.\n"
        "🔑 **`/regri-roles`**\n└ ئەو ڕۆڵانەی دەتوانن `/regri` بەکاربهێنن."
    ),
    "protect": (
        "🛡 **`/security`**\n└ سیستمی پاراستن: Anti-Spam و Anti-Nuke (دژی سپام و تێکدانی سێرڤەر)، سزا، وایت لیست و لۆگ.\n\n"
        "🔗 **`/blocklink`**\n└ کەناڵەکانێک دیاری دەکەیت کە لینکی تێدا قەدەغەیە (نامەکە دەسڕدرێتەوە).\n\n"
        "📢 **`/reklam`**\n└ کاتێک کەسێک وشەی Reklam دەنووسێت، بۆتەکە نامەی جوانی ڕێکلام دەنێرێت و ڕۆڵەکانی دیاریکراو تاگ دەکات. "
        "بەشی **Partner**یش هەیە: لە کەناڵی پارتنەر تەنها نامەی لینکی سێرڤەر ڕێگەپێدراوە.\n\n"
        "😀 **`/autoreact`**\n└ ڕیاکتی خۆکار لە کەناڵە دیاریکراوەکان: هەر نامەیەک (دەق، وێنە، ڤیدیۆ، نامەی بۆت و تێکستی گۆرانی) ئیمۆجییەکان وەرگرێت.\n"
        "   ⋅ کەناڵی نوێ هەڵبژێریت زیاد دەبێت بۆ پێشووەکان\n"
        "   ⋅ لیستی لابردن بۆ لابردنی یەک کەناڵ\n"
        "   ⋅ **Mode**: هەموو / تەنها وێنە / تەنها ڤیدیۆ / تەنها دەق\n"
        "   ⋅ **Pick by Reacting**: ئیمۆجی وەک ڕیاکت دابنێ و بۆتەکە خۆی زیادیان بکات"
    ),
    "fun": (
        "✨ **`/xp`**\n└ تۆپی XP: چات و ڤۆیس، ڕۆژانە / هەفتانە / مانگانە / ساڵانە، خۆکار نوێ دەبێتەوە.\n"
        "⚙️ **`/setxp`**\n└ دیاری دەکات کێ و لە کوێ دەتوانێت `/xp` بەکاربهێنێت.\n\n"
        "💞 **`ship @کەس`**\n└ ڕێژەی خۆشەویستی نێوان تۆ و ئەو کەسە (هەموو ڕۆژێک نوێ دەبێتەوە).\n"
        "💋 **`kiss`** / `mach` ⋅ 🫶 **`hug`** / `bawesh` ⋅ 🎀 **`pat`** / `naz` + `@کەس`\n└ ماچ، باوەش و نازدان.\n"
        "🛠 **`/setlove`**\n└ کەناڵەکان و نووسینی ship / kiss / hug ڕێکدەخات.\n\n"
        "🎶 **`/song-texts`** (هەموو کەسێک)\n└ تێکست، وێنە و فایلی گۆرانی بە شێوازێکی جوان دەنێرێت:\n"
        "   ⋅ 🎤 ناوی گۆرانیبێژ و گۆرانی ⋅ 📝 تێکست ⋅ 🖼 وێنە ⋅ 🎧 فایل (ڤیدیۆ خۆکار دەبێتە MP3)\n"
        "   ⋅ 🔤 فۆنتی ناوی گۆرانیبێژ ⋅ 👁 Preview ⋅ 📤 Send"
    ),
    "owner": (
        "🧬 **`/create_channels`**\n└ **تەنها خاوەنی بۆت.** سێرڤەرێک کۆپی دەکات (ڕۆڵ، کەناڵ، Permission، ئیمۆجی و ڕێکخستنەکانی بۆت) و لە سێرڤەرێکی تر دایدەنێتەوە (Paste).\n"
        "-# سێرڤەری سەرچاوە دەپارێزرێت و هیچ شتێکی تێدا ناسڕدرێتەوە."
    ),
}


HELP_SHORT = {
    "mod": "mute ⋅ unmute ⋅ bfra ⋅ unban ⋅ safika ⋅ lock ⋅ unlock",
    "setup": "/setlog ⋅ /setlogall ⋅ /setlogcategory ⋅ /setmuterole ⋅ /autorole ⋅ /welcome ⋅ /counting ⋅ /config",
    "roles": "/setdev ⋅ /rolemute ⋅ /roleban ⋅ /rolesafika ⋅ /rolestaff ⋅ /staff ⋅ /rangi-role ⋅ /regri",
    "protect": "/security ⋅ /blocklink ⋅ /reklam ⋅ /autoreact",
    "fun": "/xp ⋅ /setxp ⋅ ship ⋅ kiss ⋅ hug ⋅ pat ⋅ /setlove ⋅ /song-texts",
    "owner": "/create_channels",
}


def help_embed(key):
    icon, name = HELP_SECTIONS[key]
    if key == "home":
        e = discord.Embed(
            title="📖 یارمەتی بۆتەکە",
            description="لە لیستی خوارەوە بەشێک هەڵبژێرە، هەموو کۆمانەکان و بۆچوونیان و چۆنیەتی بەکارهێنانیان پیشان دەدرێت 🌸",
            color=HELP_COLOR)
        for k, (ic, nm) in HELP_SECTIONS.items():
            if k != "home":
                e.add_field(name=f"{ic} {nm}", value=HELP_SHORT[k], inline=False)
        e.set_footer(text="کۆمانی بێ / (وەک mute) تەنها بە نووسین لە چات کار دەکات")
        return e
    return discord.Embed(title=f"{icon} {name}", description=HELP_TEXT[key], color=HELP_COLOR)


class HelpSelect(discord.ui.Select):
    def __init__(self, current):
        opts = [discord.SelectOption(label=nm, value=k, emoji=ic, default=(k == current))
                for k, (ic, nm) in HELP_SECTIONS.items()]
        super().__init__(placeholder="بەشێک هەڵبژێرە...", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction):
        await interaction.response.edit_message(
            embed=help_embed(self.values[0]), view=HelpView(interaction.user.id, self.values[0]))


class HelpView(discord.ui.View):
    def __init__(self, author_id, current="home"):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.add_item(HelpSelect(current))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "ئەمە پانێلی کەسێکی ترە، خۆت `/help` بنووسە 🌷", ephemeral=True)
            return False
        return True


@bot.tree.command(name="help", description="ڕوونکردنەوەی هەموو کۆمان و بەشەکانی بۆتەکە")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=help_embed("home"), view=HelpView(interaction.user.id), ephemeral=True)


_bio_done = False


async def set_bot_bio():
    """بیۆی بۆتەکە (About Me) نوێ دەکاتەوە، تێیدا /help ی نووسراوە"""
    global _bio_done
    if _bio_done:
        return
    _bio_done = True
    try:
        from discord.http import Route
        await bot.http.request(Route("PATCH", "/applications/@me"), json={"description": BOT_BIO})
        print(f"Bot bio updated [build v3] first line: {BOT_BIO.splitlines()[0]}", flush=True)
    except Exception as ex:
        print(f"bio update failed: {ex}", flush=True)


bot.add_listener(set_bot_bio, "on_ready")


async def set_bot_presence():
    """بۆتەکە دەخاتە Do Not Disturb (سووری) لەگەڵ Listening to"""
    try:
        await bot.change_presence(
            status=discord.Status.dnd,
            activity=discord.Activity(type=discord.ActivityType.listening, name="!help | /help"),
        )
        print("Bot presence set to DND [build v3]", flush=True)
    except Exception as ex:
        print(f"presence update failed: {ex}", flush=True)


bot.add_listener(set_bot_presence, "on_ready")


# =========================================================
# 43. TEXT TO VOICE (ElevenLabs)  —  !! دەقەکەت
# =========================================================
# - تەنها ئایدی خۆت (TTS_OWNER_ID) دەتوانێت بەکاری بهێنێت
# - بنووسە:  !! nmwn bam shewaya ba piti englizi qsa bkam
#   بۆتەکە نامەکەت دەسڕێتەوە و دەنگی کچێکی ناسک دەنێرێت (فایلی MP3)
# - API Key هەرگیز لەناو کۆدەکەدا نانووسرێت، لە Railway > Variables:
#       ELEVENLABS_API_KEY   = کلیلەکەت (پێویستە)
#       ELEVENLABS_VOICE_ID  = ئایدی دەنگ (ئارەزوومەندانە)
#       ELEVENLABS_MODEL     = مۆدێل (ئارەزوومەندانە، دیفەڵت eleven_v4)
#       ELEVENLABS_LANG      = کۆدی زمان (ئارەزوومەندانە، بەتاڵ = خۆکار)
# - هیچ پاکێجێکی نوێ پێویست نییە (aiohttp لەگەڵ discord.py دێت)

import aiohttp as _aiohttp

TTS_OWNER_ID = 1130455970494025860          # تەنها ئەم ئەکاونتە
TTS_TRIGGER = "!!"
TTS_MAX_CHARS = 2500
TTS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID") or "EXAVITQu4vr4xnSDxMaL"   # Sarah: دەنگی کچێکی ناسک و گەنج
TTS_MODEL = os.getenv("ELEVENLABS_MODEL") or "eleven_v4"
TTS_LANG = os.getenv("ELEVENLABS_LANG") or None
_tts_busy = False


async def tts_generate(text):
    """(mp3 bytes, None) یان (None, هۆکاری هەڵە)"""
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        return None, "ELEVENLABS_API_KEY لە Railway Variables دانەنراوە."

    models = []
    for m in (TTS_MODEL, "eleven_v3", "eleven_multilingual_v2"):
        if m not in models:
            models.append(m)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{TTS_VOICE_ID}"
    last_err = "هەڵەی نەزانراو"
    timeout = _aiohttp.ClientTimeout(total=90)
    async with _aiohttp.ClientSession(timeout=timeout) as http:
        for model in models:
            body = {
                "text": text,
                "model_id": model,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
            if TTS_LANG:
                body["language_code"] = TTS_LANG
            try:
                async with http.post(
                    url, params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": key, "Content-Type": "application/json",
                             "Accept": "audio/mpeg"},
                    json=body,
                ) as r:
                    if r.status == 200:
                        return await r.read(), None
                    detail = (await r.text())[:300]
                    if r.status == 401:
                        return None, "API Key هەڵەیە یان لابراوە (401)."
                    if r.status == 402 or "quota" in detail.lower():
                        return None, "بالانسی ElevenLabs تەواو بووە (quota)."
                    if r.status == 429:
                        return None, "زۆر داواکاری نێردرا، کەمێک چاوەڕێ بکە (429)."
                    last_err = f"{model}: {r.status} {detail}"
                    print(f"tts error {last_err}", flush=True)
            except asyncio.TimeoutError:
                last_err = "کاتەکە بەسەرچوو (timeout)."
            except Exception as ex:
                last_err = f"{model}: {ex}"
                print(f"tts exception {last_err}", flush=True)
    return None, last_err


async def tts_on_message(message):
    global _tts_busy
    if message.author.bot or message.guild is None:
        return
    if message.author.id != TTS_OWNER_ID:
        return
    content = (message.content or "").strip()
    if not content.startswith(TTS_TRIGGER):
        return

    text = content[len(TTS_TRIGGER):].strip()
    if not text:
        return
    if len(text) > TTS_MAX_CHARS:
        await message.channel.send(
            f"❌ دەقەکە زۆر درێژە ({len(text)}). زۆرترین `{TTS_MAX_CHARS}` پیت.", delete_after=8)
        return

    if _tts_busy:
        await message.channel.send("⏳ چاوەڕێ بکە، دەنگێکی تر دروست دەکرێت.", delete_after=5)
        return
    _tts_busy = True
    try:
        async with message.channel.typing():
            audio, err = await tts_generate(text)

        if not audio:
            # نامەکە ناسڕدرێتەوە تا دەقەکەت نەفەوتێت
            await message.channel.send(f"❌ {err}", delete_after=12)
            return

        # ئەگەر وەڵامی نامەی کەسێکت دابێتەوە، دەنگەکەش وەڵامی هەمان نامە دەبێت
        ref = None
        if message.reference and message.reference.message_id:
            ref = discord.MessageReference(
                message_id=message.reference.message_id,
                channel_id=message.channel.id, fail_if_not_exists=False)

        file = discord.File(_io.BytesIO(audio), filename="voice.mp3")
        try:
            await message.channel.send(
                file=file, reference=ref, mention_author=False,
                allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە دەسەڵاتی Attach Files ی نییە لەم کەناڵە.", delete_after=10)
            return

        try:
            await message.delete()
        except Exception:
            pass   # بۆتەکە پێویستی بە Manage Messages ە
    except Exception as ex:
        print(f"tts handler error: {ex}", flush=True)
        try:
            await message.channel.send(f"❌ هەڵە: {ex}", delete_after=10)
        except Exception:
            pass
    finally:
        _tts_busy = False


bot.add_listener(tts_on_message, "on_message")


# =========================================================
# 29f. DATA BACKUP / RESTORE  (/get-data  &  /upload-data)
# =========================================================
# /get-data     → هەموو داتای بۆتەکە (guild_config + xp_data + server_templates) دەکاتە یەک ZIP و بۆت دەنێرێت
# /upload-data  → ZIP ەکە وەردەگرێت و لەگەڵ داتای ئێستا Tێکەڵی دەکات (هیچ شتێک ناسڕێتەوە)
#   - هەر سێرڤەرەو داتای خۆی (بەپێی ئایدی سێرڤەر) دەگەڕێتەوە، تێکەڵ نابن
#   - ئەگەر server بنووسیت (ئایدی سێرڤەر) تەنها داتای ئەو سێرڤەرە دەگەڕێتەوە
#   - پێش تێکەڵکردن backup ی داتای ئێستا هەڵدەگیرێت (فۆڵدەری backups)
# تەنها خاوەنی بۆت (CC_OWNER_ID) بەکاری دەهێنێت

import zipfile as _zipfile

DATA_DIR = os.path.dirname(CONFIG_FILE) or "."
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DATA_MAX_ZIP = 25 * 1024 * 1024          # گەورەترین ZIP ی ڕێگەپێدراو بۆ Upload
DATA_MAX_UNZIPPED = 300 * 1024 * 1024    # دژی zip-bomb
DATA_KEEP_BACKUPS = 5


def _dt_build_zip(include_templates=True, only_guild=None):
    """ZIP دروست دەکات و bytes دەگەڕێنێتەوە"""
    save_config()
    xp_save_now()
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, arc in ((CONFIG_FILE, "guild_config.json"), (XP_FILE, "xp_data.json")):
            if os.path.isfile(path):
                z.write(path, arc)
        if include_templates and os.path.isdir(CC_DIR):
            for fn in sorted(os.listdir(CC_DIR)):
                full = os.path.join(CC_DIR, fn)
                if os.path.isfile(full) and fn.endswith(".json"):
                    z.write(full, "server_templates/" + fn)
        z.writestr("manifest.json", json.dumps({
            "app": "gorani-bot-data", "version": 1,
            "created": _dt.datetime.utcnow().isoformat() + "Z",
            "templates": bool(include_templates),
        }))
    return buf.getvalue()


def _dt_merge(cur, inc, num_max=False):
    """تێکەڵکردنی قووڵ، cur لە شوێنی خۆی نوێ دەکرێتەوە.
    dict → recursive | list → union (بێ دووبارەبوونەوە) | ژمارە → num_max ? max : inc | تر → inc
    inc ی بەتاڵ (None / "" / [] / {}) هەرگیز شتێکی پڕ ناگۆڕێت."""
    if isinstance(cur, dict) and isinstance(inc, dict):
        for k, v in inc.items():
            if k in cur:
                cur[k] = _dt_merge(cur[k], v, num_max)
            else:
                cur[k] = v
        return cur
    if isinstance(cur, list) and isinstance(inc, list):
        for item in inc:
            if item not in cur:
                cur.append(item)
        return cur
    if inc is None or inc == "" or inc == [] or inc == {}:
        return cur if cur not in (None, "", [], {}) else inc
    if (num_max and isinstance(cur, (int, float)) and isinstance(inc, (int, float))
            and not isinstance(cur, bool) and not isinstance(inc, bool)):
        return max(cur, inc)
    return inc


def _dt_read_zip(raw):
    """ZIP ەکە دەخوێنێتەوە و پشکنینی ئەمنی دەکات. دەگەڕێتەوە: (config, xp, templates{name: bytes})"""
    z = _zipfile.ZipFile(_io.BytesIO(raw))
    infos = z.infolist()
    if sum(i.file_size for i in infos) > DATA_MAX_UNZIPPED:
        raise ValueError("فایلەکە زۆر گەورەیە (zip-bomb؟)")
    cfg_in, xp_in, tpls = {}, {}, {}
    found = False
    for i in infos:
        name = i.filename
        if name.endswith("/") or name == "manifest.json":
            continue
        if name == "guild_config.json":
            cfg_in = json.loads(z.read(i).decode("utf-8")); found = True
        elif name == "xp_data.json":
            xp_in = json.loads(z.read(i).decode("utf-8")); found = True
        elif name.startswith("server_templates/"):
            base = name[len("server_templates/"):]
            if "/" in base or "\\" in base or ".." in base or not base.endswith(".json"):
                raise ValueError(f"ناوی نادروست لە ZIP: {name}")
            tpls[base] = z.read(i)
        else:
            raise ValueError(f"فایلی نەناسراو لە ZIP: {name}")
    if not found:
        raise ValueError("guild_config.json یان xp_data.json لەناو ZIP نییە")
    if not isinstance(cfg_in, dict) or not isinstance(xp_in, dict):
        raise ValueError("ناوەڕۆکی JSON نادروستە")
    return cfg_in, xp_in, tpls


def _dt_backup_now():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = _dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUP_DIR, f"pre-upload-{stamp}.zip")
    with open(path, "wb") as f:
        f.write(_dt_build_zip(include_templates=True))
    olds = sorted(fn for fn in os.listdir(BACKUP_DIR) if fn.startswith("pre-upload-"))
    for fn in olds[:-DATA_KEEP_BACKUPS]:
        try:
            os.remove(os.path.join(BACKUP_DIR, fn))
        except OSError:
            pass
    return path


def _dt_apply(cfg_in, xp_in, tpls, only_guild=None):
    """تێکەڵکردن لە مەمۆری (بێ await، بۆیە race نابێت). دەگەڕێتەوە ئامار."""
    stats = {"guilds": set(), "boards": 0, "templates": 0}
    gid = str(only_guild) if only_guild else None

    # --- config ---
    for g, v in cfg_in.items():
        if gid and g != gid:
            continue
        if not isinstance(v, dict):
            continue
        cur = config.setdefault(g, {})
        _dt_merge(cur, v)
        stats["guilds"].add(g)

    # --- xp_data ---
    for key, val in xp_in.items():
        if key == "users" and isinstance(val, dict):
            for g, v in val.items():
                if gid and g != gid:
                    continue
                _dt_merge(xp_db["users"].setdefault(g, {}), v, num_max=True)
                stats["guilds"].add(g)
        elif key == "love" and isinstance(val, dict):
            for g, v in val.items():
                if gid and g != gid:
                    continue
                _dt_merge(xp_db.setdefault("love", {}).setdefault(g, {}), v, num_max=True)
                stats["guilds"].add(g)
        elif key == "boards" and isinstance(val, list):
            for b in val:
                if not isinstance(b, dict):
                    continue
                if gid and str(b.get("g")) != gid:
                    continue
                same = any(str(x.get("g")) == str(b.get("g")) and str(x.get("m")) == str(b.get("m"))
                           for x in xp_db["boards"])
                if not same:
                    xp_db["boards"].append(b)
                    stats["boards"] += 1
        elif not gid:
            # کلیلی تر (بێ ئایدی سێرڤەر) تەنها لە Upload ی تەواو
            if key in xp_db:
                xp_db[key] = _dt_merge(xp_db[key], val, num_max=True)
            else:
                xp_db[key] = val

    # --- templates (تەنها لە Upload ی تەواو) ---
    if not gid and tpls:
        os.makedirs(CC_DIR, exist_ok=True)
        for fn, data in tpls.items():
            path = os.path.join(CC_DIR, fn)
            if fn == "sources.json":
                try:
                    merged = cc_sources() | {int(x) for x in json.loads(data.decode("utf-8"))}
                    data = json.dumps(sorted(merged)).encode("utf-8")
                except Exception:
                    continue
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
            stats["templates"] += 1

    save_config()
    xp_save_now()
    return stats


@bot.tree.command(name="get-data", description="هەموو داتای بۆتەکە دابەزێنە وەک فایل (تەنها خاوەنی بۆت)")
@app_commands.describe(templates="تێمپلەیتەکانی کۆپی سێرڤەریش لەگەڵیدا بێت؟ (بنەڕەت: بەڵێ)")
async def get_data_cmd(interaction: discord.Interaction, templates: bool = True):
    if interaction.user.id != CC_OWNER_ID:
        await deny_interaction(interaction)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        limit = interaction.guild.filesize_limit if interaction.guild else 10 * 1024 * 1024
        limit = min(limit, 25 * 1024 * 1024) - 64 * 1024
        note = ""
        raw = await asyncio.to_thread(_dt_build_zip, templates)
        if len(raw) > limit and templates:
            raw = await asyncio.to_thread(_dt_build_zip, False)
            note = "\n⚠️ تێمپلەیتەکان زۆر گەورە بوون بۆیە لەگەڵیدا نین. فۆڵدەری `server_templates` جیا بگوازەرەوە."
        if len(raw) > limit:
            await interaction.followup.send(
                f"❌ فایلەکە {len(raw)/1048576:.1f}MB یە و لە سنووری Discord گەورەترە.", ephemeral=True)
            return
        stamp = _dt.datetime.utcnow().strftime("%Y%m%d-%H%M")
        await interaction.followup.send(
            f"✅ داتای بۆتەکە ئامادەیە ({len(raw)/1024:.0f}KB)\n"
            f"سێرڤەرەکان: **{len(config)}**  |  بۆردی XP: **{len(xp_db.get('boards', []))}**{note}\n"
            f"لە بۆتی نوێ بە `/upload-data` بینێرەوە.",
            file=discord.File(_io.BytesIO(raw), filename=f"bot-data-{stamp}.zip"),
            ephemeral=True,
        )
    except Exception as ex:
        print(f"get-data error: {ex}", flush=True)
        await interaction.followup.send(f"❌ هەڵە: {ex}", ephemeral=True)


@bot.tree.command(name="upload-data", description="داتای پێشوو بگەڕێنەوە و لەگەڵ داتای ئێستا تێکەڵی بکە (تەنها خاوەنی بۆت)")
@app_commands.describe(file="فایلی ZIP ی /get-data",
                       server="ئایدی سێرڤەر: تەنها داتای ئەو سێرڤەرە بگەڕێنەوە (ئارەزووومەندانە)")
async def upload_data_cmd(interaction: discord.Interaction, file: discord.Attachment, server: str = None):
    if interaction.user.id != CC_OWNER_ID:
        await deny_interaction(interaction)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        only = None
        if server:
            server = server.strip()
            if not server.isdigit():
                await interaction.followup.send("❌ ئایدی سێرڤەر دەبێت ژمارە بێت.", ephemeral=True)
                return
            only = server
        if not file.filename.lower().endswith(".zip"):
            await interaction.followup.send("❌ تەنها فایلی `.zip` ی /get-data.", ephemeral=True)
            return
        if file.size > DATA_MAX_ZIP:
            await interaction.followup.send("❌ فایلەکە زۆر گەورەیە.", ephemeral=True)
            return
        raw = await file.read()
        cfg_in, xp_in, tpls = _dt_read_zip(raw)
        backup = await asyncio.to_thread(_dt_backup_now)
        stats = _dt_apply(cfg_in, xp_in, tpls, only)
        if only and only not in stats["guilds"]:
            msg = f"⚠️ لەناو فایلەکە هیچ داتایەک بۆ سێرڤەری `{only}` نەدۆزرایەوە."
        else:
            msg = (f"✅ داتا تێکەڵ کرا\n"
                   f"سێرڤەر: **{len(stats['guilds'])}**  |  بۆردی نوێ: **{stats['boards']}**  |  "
                   f"تێمپلەیت: **{stats['templates']}**\n"
                   f"🗂 backup ی داتای پێشوو: `{os.path.basename(backup)}`")
        await interaction.followup.send(msg, ephemeral=True)
    except (_zipfile.BadZipFile, ValueError, json.JSONDecodeError) as ex:
        await interaction.followup.send(f"❌ فایلەکە دروست نییە: {ex}", ephemeral=True)
    except Exception as ex:
        print(f"upload-data error: {ex}", flush=True)
        await interaction.followup.send(f"❌ هەڵە: {ex}", ephemeral=True)


# =========================================================
# 34b. REKLAM LINK CUSTOMIZER + PARTNER AD COUNTING
# =========================================================

REKLAM_COUNT_FILE = os.path.join(os.path.dirname(CONFIG_FILE) or ".", "reklam_count_data.json")
try:
    with open(REKLAM_COUNT_FILE, "r", encoding="utf-8") as _f:
        reklam_count_db = json.load(_f)
except Exception:
    reklam_count_db = {}
reklam_count_db.setdefault("users", {})  # users[guild_id][user_id] = total invite links
reklam_count_db.setdefault("boards", [])  # manually sent boards: {g, c, m}
_reklam_board_state = {}


def reklam_count_save():
    try:
        tmp = REKLAM_COUNT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reklam_count_db, f, ensure_ascii=False, indent=2)
        os.replace(tmp, REKLAM_COUNT_FILE)
    except Exception as ex:
        print(f"reklam count save error: {ex}", flush=True)


def reklam_message_text(message):
    """Include forwarded-message snapshots where Discord.py exposes them."""
    chunks = [message.content or ""]
    for snap in (getattr(message, "message_snapshots", None) or []):
        snap_msg = getattr(snap, "message", snap)
        chunks.append(getattr(snap_msg, "content", "") or "")
    for emb in getattr(message, "embeds", []) or []:
        chunks.extend([getattr(emb, "url", "") or "", getattr(emb, "description", "") or ""])
    return "\n".join(chunks)


def reklam_invite_links(message):
    # Count only Discord server invites, not arbitrary URLs; duplicate invite strings
    # in one post are counted once. Forwarded message snapshots are included.
    text = reklam_message_text(message)
    return set(m.group(0).rstrip(".,)>]}") for m in SEC_INVITE_RX.finditer(text))


async def reklam_count_message(message):
    if message.guild is None or message.author.bot:
        return
    # Counting follows the Partner channels chosen in /reklam -> Partner (same as pt_check).
    # Owner, administrator, developer and normal members are ALL counted (no exemption).
    if not is_partner_channel(message):
        return
    # The same restrictions as Partner: no stickers/images/attachments, only invite links.
    if msg_has_attached_image(message):
        return
    links = reklam_invite_links(message)
    if not links:
        return
    users = reklam_count_db["users"].setdefault(str(message.guild.id), {})
    uid = str(message.author.id)
    users[uid] = int(users.get(uid, 0)) + len(links)
    reklam_count_save()


async def reklam_count_on_message(message):
    await reklam_count_message(message)


bot.add_listener(reklam_count_on_message, "on_message")


def reklam_count_embed(guild):
    """Partner leaderboard styled to match the existing XP board."""
    users = reklam_count_db["users"].get(str(guild.id), {})
    ranked = sorted(users.items(), key=lambda item: item[1], reverse=True)[:25]
    lines = ["✧･ﾟ:  Partner  :･ﾟ✧", ""]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for rank, (uid, count) in enumerate(ranked, 1):
        member = guild.get_member(int(uid))
        name = member.display_name if member else f"<@{uid}>"
        name = discord.utils.escape_markdown(name)[:20]
        if rank <= 3:
            lines.append(f"{medals[rank]} **{name}** ⋆ **{int(count):,}** ✦")
            if rank == 3 and len(ranked) > 3:
                lines.append("┈┈┈┈┈┈┈┈┈┈┈┈")
        else:
            lines.append(f"`{rank:02d}` {name} ⋅ {int(count):,} ✦")
    if not ranked:
        lines.append("هێشتا هیچ ڕیکلامێک نەژمێردراوە ♡")
    embed = discord.Embed(
        title="🤝  Partner Reklam  ♡  Top 25",
        description="\n".join(lines)[:4000],
        color=discord.Color.from_rgb(244, 208, 238),
    )
    embed.set_footer(
        text="⟡ نوێ دەبێتەوە هەر چرکەیەک ⟡  ·  تەنها لینکی بانگهێشتی سێرڤەر ژمێردرێت",
        icon_url=guild.icon.url if guild.icon else None,
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    return embed


def reklam_count_sig(embed):
    return json.dumps(embed.to_dict(), sort_keys=True, ensure_ascii=False)


@_tasks.loop(seconds=XP_REFRESH)
async def reklam_count_board_loop():
    # Only boards that the owner/developer manually sent are refreshed.
    for board_info in list(reklam_count_db.get("boards", [])):
        guild = bot.get_guild(int(board_info.get("g", 0)))
        if guild is None:
            continue
        try:
            message_id = int(board_info["m"])
            if board_info.get("c") is None:
                continue
            embed = reklam_count_embed(guild)
            sig = reklam_count_sig(embed)
            if _reklam_board_state.get(message_id) == sig:
                continue
            channel = guild.get_channel(int(board_info["c"]))
            if channel is None:
                continue
            msg = await channel.fetch_message(message_id)
            await msg.edit(embed=embed)
            _reklam_board_state[message_id] = sig
        except discord.NotFound:
            try:
                reklam_count_db["boards"].remove(board_info)
                reklam_count_save()
            except ValueError:
                pass
        except discord.Forbidden:
            pass
        except Exception as ex:
            print(f"reklam count board update error: {ex}", flush=True)


async def reklam_count_loop_ready():
    if not reklam_count_board_loop.is_running():
        reklam_count_board_loop.start()


bot.add_listener(reklam_count_loop_ready, "on_ready")


RK_MEDIA_DIR = os.path.join(DATA_DIR, "reklam_media_v2")
RK_MEDIA_MAX = 8 * 1024 * 1024


def rk_media_path(url):
    import hashlib
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    if ext not in (".gif", ".png", ".jpg", ".jpeg", ".webp", ".mp4"):
        ext = ".gif"
    return os.path.join(RK_MEDIA_DIR, hashlib.sha1(url.encode()).hexdigest() + ext)


async def rk_media_get(url):
    """Return a local file for this GIF/image link (downloaded once, then kept so it never expires)."""
    path = rk_media_path(url)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    try:
        os.makedirs(RK_MEDIA_DIR, exist_ok=True)
        timeout = _aiohttp.ClientTimeout(total=40)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; DiscordBot)"}
        async with _aiohttp.ClientSession(timeout=timeout, headers=headers) as sess:
            async with sess.get(url) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                if r.status != 200 or not (ctype.startswith("image/") or ctype.startswith("video/")):
                    print(f"reklam media: bad response {r.status} {ctype} for {url[:80]}", flush=True)
                    return None
                data = bytearray()
                async for chunk in r.content.iter_chunked(64 * 1024):   # read the WHOLE body
                    data.extend(chunk)
                    if len(data) > RK_MEDIA_MAX:
                        print("reklam media: file too big (>8MB)", flush=True)
                        return None
                expected = r.headers.get("Content-Length")
        if not data or (expected and expected.isdigit() and len(data) != int(expected)):
            print("reklam media: incomplete download", flush=True)
            return None
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return path
    except Exception as ex:
        print(f"reklam media download error: {ex}", flush=True)
        return None


class ReklamLinkModal(discord.ui.Modal, title="Reklam Link Message"):
    def __init__(self, guild):
        super().__init__()
        rk = get_rk(guild.id)
        self.server_link = discord.ui.TextInput(
            label="Server invite link", placeholder="https://discord.gg/...",
            default=rk.get("server_link") or None, max_length=200)
        self.before_text = discord.ui.TextInput(
            label="Text above link (GIF link allowed)", style=discord.TextStyle.paragraph,
            default=rk.get("link_before") or None, required=False, max_length=900)
        self.after_text = discord.ui.TextInput(
            label="Text below link (GIF link allowed)", style=discord.TextStyle.paragraph,
            default=rk.get("link_after") or None, required=False, max_length=900)
        for item in (self.server_link, self.before_text, self.after_text):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        link = self.server_link.value.strip()
        if not SEC_INVITE_RX.search(link):
            await interaction.response.send_message("❌ تکایە لینکی بانگهێشتی سێرڤەری Discord دابنێ.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        rk = get_rk(interaction.guild.id)
        rk["server_link"] = link
        rk["link_before"] = self.before_text.value.strip()
        rk["link_after"] = self.after_text.value.strip()
        rk["link_gif"] = ""
        save_config()
        msg = ("✅ Link auto-message ڕێکخرا. لە کەناڵە دیاریکراوەکانی Reklam هەر نامەیەک وشەی "
               "`link` یان `لینک` تیابێت، بۆتەکە ئەم نامەیە دەنێرێت.")
        bad = 0
        for text in (rk["link_before"], rk["link_after"]):
            for m in RK_MEDIA_URL_RX.finditer(text):
                if not await rk_media_get(m.group(0)):
                    bad += 1
        if bad:
            msg += (f"\n⚠ {bad} لینکی GIF/وێنە نەتوانرا دابەزێنرێت (لەوانەیە بەسەرچووبێت، یان فایلەکە "
                    "گەورەیە، یان لینکی ڕاستەوخۆی وێنە نییە). لینکەکە وەک خۆی دەنێردرێت.")
        await interaction.followup.send(msg, ephemeral=True)


# =========================================================
# 30. RUN
# =========================================================

TOKEN = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("❌ Token نەدۆزرایەوە! لە Railway > Variables بیخە ناو TOKEN", flush=True)
else:
    bot.run(TOKEN)
