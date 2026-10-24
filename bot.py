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

bot = commands.Bot(command_prefix="", intents=intents, case_insensitive=True)

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
    for k in ("mute", "ban", "safika", "staff", "regri"):
        bl.setdefault(k, [])
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
        if member.id == member.guild.owner_id:
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
        if member.id == member.guild.owner_id:
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
    if author.id == guild.owner_id or author.guild_permissions.administrator:
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
        if not message.author.guild_permissions.manage_channels:
            return
        try:
            await message.channel.set_permissions(message.guild.default_role, send_messages=False)
            await message.channel.send("🔒 کەناڵەکە Lock کرا.")
        except Exception:
            pass
        return

    # ---------------- UNLOCK ----------------
    if command == "unlock":
        if not message.author.guild_permissions.manage_channels:
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
@app_commands.default_permissions(administrator=True)
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
@app_commands.default_permissions(administrator=True)
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
@app_commands.default_permissions(administrator=True)
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
@app_commands.default_permissions(administrator=True)
async def autorole_cmd(interaction: discord.Interaction):
    await open_perm_panel(interaction, "auto")


@bot.tree.command(name="config", description="پیشاندانی ڕێکخستنەکانی ئەم سێرڤەرە")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
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
@app_commands.default_permissions(administrator=True)
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
        getter(g.id)[field] = [c.id for c in self.values]
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
    e.set_footer(text="کەناڵ هەڵبژێریت، لیستەکەی پێشوو دەگۆڕێت")
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


async def ar_on_message(message):
    if message.author.bot or message.guild is None:
        return
    a = get_ar(message.guild.id)
    if not a["enabled"] or not a["emojis"] or not a["channels"]:
        return
    ch = message.channel
    if ch.id not in a["channels"] and getattr(ch, "parent_id", None) not in a["channels"]:
        return

    has_vid = msg_has_video(message)
    has_img = msg_has_image(message) and not has_vid
    has_text = bool((message.content or "").strip())
    mode = a["mode"]
    if mode == "image":
        ok = has_img
    elif mode == "video":
        ok = has_vid
    elif mode == "text":
        ok = has_text and not has_img and not has_vid
    else:
        ok = has_img or has_vid or has_text
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
@app_commands.default_permissions(administrator=True)
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
    if (message.content or "").strip().lower() not in {t.lower() for t in rk["triggers"]}:
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
@app_commands.default_permissions(administrator=True)
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
        return (member.id == member.guild.owner_id
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
    for a in m.attachments:
        ct = (a.content_type or "").lower()
        if ct.startswith("image/") or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
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
    if not is_partner_channel(message) or chat_exempt(message.author):
        return
    if msg_has_attached_image(message):
        await _delete_and_warn(message, "نابێت وێنە لێرە بنێریت.")
    elif not SEC_INVITE_RX.search(message.content or ""):
        await _delete_and_warn(
            message, "ناتوانیت تێکست لێرە دابنێیت، دەبێت لەگەڵ تێکستەکە لینکی سێرڤەر هەبێت.")


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
    e.set_footer(text="تەنها نامەی لەگەڵ لینکی سێرڤەر ڕێگەپێدراوە | وێنە قەدەغەیە")
    return e


class RkPartnerView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        rk = get_rk(guild.id)
        self.add_item(PanelChannelSelect("rkp", row=0))
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
@app_commands.default_permissions(administrator=True)
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
@app_commands.default_permissions(administrator=True)
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
        return member.id == member.guild.owner_id
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
@app_commands.default_permissions(administrator=True)
async def rolemute(interaction: discord.Interaction):
    await open_perm_panel(interaction, "mute")


@bot.tree.command(name="roleban", description="ئەو ڕۆڵانەی دەتوانن Bfra / Unban بکەن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def roleban(interaction: discord.Interaction):
    await open_perm_panel(interaction, "ban")


@bot.tree.command(name="rolesafika", description="ئەو ڕۆڵانەی دەتوانن Safika (کلێر) بکەن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def rolesafika(interaction: discord.Interaction):
    await open_perm_panel(interaction, "safika")


@bot.tree.command(name="rolestaff", description="ئەو ڕۆڵانەی دەتوانن /staff بەکاربهێنن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def rolestaff(interaction: discord.Interaction):
    await open_perm_panel(interaction, "staff")


@bot.tree.command(name="regri-roles", description="ئەو ڕۆڵانەی دەتوانن /regri بەکاربهێنن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def regri_roles(interaction: discord.Interaction):
    await open_perm_panel(interaction, "regri")


@bot.tree.command(name="regadan-ranggorin", description="ڕۆڵ و کەسانی ڕێگەپێدراو بۆ گۆڕینی ڕەنگی ڕۆڵ")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
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
@app_commands.default_permissions(administrator=True)
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
@app_commands.default_permissions(administrator=True)
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
# 30. RUN
# =========================================================

TOKEN = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("❌ Token نەدۆزرایەوە! لە Railway > Variables بیخە ناو TOKEN", flush=True)
else:
    bot.run(TOKEN)
