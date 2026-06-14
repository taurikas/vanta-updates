#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import keys_manager

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vanta-bot")

DEFAULT_OWNER_ID = 755423606732750988
OWNER_ID = int(os.getenv("OWNER_ID", str(DEFAULT_OWNER_ID)))
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
LAUNCHER_PATH = os.getenv("LAUNCHER_PATH", "").strip()
AUTO_GIT_PUSH = os.getenv("AUTO_GIT_PUSH", "true").lower() in ("1", "true", "yes")

MAX_FAILS = 5
FAIL_WINDOW_SEC = 900
COOLDOWN_SEC = 3

_failed_attempts = defaultdict(deque)
_last_attempt = {}


def is_owner(user):
    return user.id == OWNER_ID


def _rate_limit(user_id):
    now = time.monotonic()
    last = _last_attempt.get(user_id, 0.0)
    if now - last < COOLDOWN_SEC:
        return "Please wait a few seconds before trying again."
    _last_attempt[user_id] = now
    q = _failed_attempts[user_id]
    while q and now - q[0] > FAIL_WINDOW_SEC:
        q.popleft()
    if len(q) >= MAX_FAILS:
        return "Too many failed attempts. Try again later."
    return None


def _record_fail(user_id):
    _failed_attempts[user_id].append(time.monotonic())


def git_push_keys():
    if not AUTO_GIT_PUSH:
        return True, "AUTO_GIT_PUSH disabled"
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")

    def run(args):
        return subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=60)

    try:
        if run(["git", "add", "keys.enc"]).returncode != 0:
            return False, "git add failed"
        status = run(["git", "status", "--porcelain", "keys.enc"])
        if "keys.enc" not in (status.stdout or ""):
            return True, "keys.enc already up to date"
        commit = run(["git", "-c", "user.name=vanta-bot", "-c", "user.email=vanta-bot@local", "commit", "-m", "Update keys.enc"])
        if commit.returncode != 0:
            return False, "commit step failed"
        if run(["git", "push"]).returncode != 0:
            return False, "git push failed"
        return True, "Pushed keys.enc to GitHub"
    except Exception as exc:
        return False, str(exc)


class LicenseModal(discord.ui.Modal, title="Enter License Key"):
    license_key = discord.ui.TextInput(
        label="License Key",
        placeholder="VNTA-XXXX-XXXX-XXXX-XXXX",
        min_length=23,
        max_length=32,
    )

    async def on_submit(self, interaction):
        limit = _rate_limit(interaction.user.id)
        if limit:
            await interaction.response.send_message(limit, ephemeral=True)
            return
        ok, msg = keys_manager.validate_for_discord(self.license_key.value, interaction.user.id)
        if not ok:
            _record_fail(interaction.user.id)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        if not LAUNCHER_PATH:
            await interaction.response.send_message("Launcher not configured. Contact the owner.", ephemeral=True)
            return
        launcher = Path(LAUNCHER_PATH)
        if not launcher.is_file():
            await interaction.response.send_message("Launcher file missing. Contact the owner.", ephemeral=True)
            return
        if launcher.stat().st_size > 24 * 1024 * 1024:
            await interaction.response.send_message("Launcher too large for Discord.", ephemeral=True)
            return
        await interaction.response.send_message("Verified. Sending launcher...", ephemeral=True)
        try:
            await interaction.followup.send(
                content="Here is your launcher. Keep your key private.",
                file=discord.File(str(launcher), filename=launcher.name),
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send("Could not send the file. Contact the owner.", ephemeral=True)


class OwnerGenerateModal(discord.ui.Modal, title="Generate License Key"):
    user_id = discord.ui.TextInput(label="Discord User ID", placeholder="755423606732750988", min_length=17, max_length=20)
    expiry = discord.ui.TextInput(label="Expiry (+30d or YYYY-MM-DD)", placeholder="+30d", min_length=2, max_length=10)
    note = discord.ui.TextInput(label="Note (optional)", required=False, max_length=64)

    async def on_submit(self, interaction):
        if not is_owner(interaction.user):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        uid_text = self.user_id.value.strip()
        if not uid_text.isdigit():
            await interaction.response.send_message("Invalid Discord user ID.", ephemeral=True)
            return
        discord_id = int(uid_text)
        try:
            expiry = keys_manager.parse_expiry_arg(self.expiry.value.strip())
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        try:
            record = keys_manager.generate_for_user(discord_id, expiry, self.note.value.strip())
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        _, push_msg = git_push_keys()
        await interaction.response.send_message(
            "Generated `{}`\nExpires: **{}**\nUser ID: `{}`\nGit: {}".format(
                record.key, record.expires.isoformat(), discord_id, push_msg
            ),
            ephemeral=True,
        )


class OwnerPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Get Launcher", style=discord.ButtonStyle.primary, custom_id="vanta:get_launcher")
    async def get_launcher(self, interaction, button):
        await interaction.response.send_modal(LicenseModal())

    @discord.ui.button(label="Generate Key", style=discord.ButtonStyle.success, custom_id="vanta:owner_generate")
    async def generate_key(self, interaction, button):
        if not is_owner(interaction.user):
            await interaction.response.send_message("Only the owner can generate keys.", ephemeral=True)
            return
        await interaction.response.send_modal(OwnerGenerateModal())


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)


@bot.event
async def on_ready():
    bot.add_view(OwnerPanel())
    log.info("Logged in as %s", bot.user)


def _parse_user_id(arg):
    arg = arg.strip()
    if arg.startswith("<@") and arg.endswith(">"):
        arg = arg.replace("<@!", "").replace("<@", "").replace(">", "")
    if arg.isdigit():
        return int(arg)
    return None


@bot.command(name="panel")
async def panel_cmd(ctx):
    if not is_owner(ctx.author):
        return
    embed = discord.Embed(
        title="Vanta Launcher",
        description=(
            "Click **Get Launcher** and enter the license key generated for **your** Discord account.\n\n"
            "Keys are tied to your Discord ID and cannot be shared."
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="Vanta License System")
    await ctx.send(embed=embed, view=OwnerPanel())


@bot.command(name="keys")
async def keys_cmd(ctx, *, args=""):
    if not is_owner(ctx.author):
        return
    args = args.strip()
    if not args:
        await ctx.reply("Usage: `.keys @user +30d` | `.keys revoke KEY` | `.keys list`", delete_after=20)
        return
    if args.lower() == "list":
        records = keys_manager.load_records()
        if not records:
            await ctx.reply("No keys.", delete_after=15)
            return
        lines = []
        for r in records:
            status = "expired" if keys_manager.is_expired(r) else "active"
            uid = str(r.discord_id) if r.discord_id else "unlinked"
            lines.append("`{}` -> `{}` until {} ({})".format(r.key, uid, r.expires, status))
        await ctx.author.send("\n".join(lines[:40]))
        try:
            await ctx.message.add_reaction(chr(0x1F4EC))
        except discord.HTTPException:
            pass
        return
    if args.lower().startswith("revoke "):
        key = args[7:].strip()
        if keys_manager.revoke_key(key):
            _, push_msg = git_push_keys()
            await ctx.reply("Revoked `{}`. {}".format(keys_manager.normalize_key(key), push_msg), delete_after=15)
        else:
            await ctx.reply("Key not found.", delete_after=10)
        return
    parts = args.split()
    if len(parts) < 2:
        await ctx.reply("Example: `.keys @user +30d`", delete_after=12)
        return
    discord_id = _parse_user_id(parts[0])
    if discord_id is None:
        await ctx.reply("Could not parse Discord user.", delete_after=10)
        return
    try:
        expiry = keys_manager.parse_expiry_arg(parts[1])
    except ValueError as exc:
        await ctx.reply(str(exc), delete_after=12)
        return
    note = " ".join(parts[2:]).strip()
    try:
        record = keys_manager.generate_for_user(discord_id, expiry, note)
    except ValueError as exc:
        await ctx.reply(str(exc), delete_after=12)
        return
    _, push_msg = git_push_keys()
    try:
        member = ctx.guild.get_member(discord_id) if ctx.guild else None
        if member:
            await member.send(
                "Your Vanta license key:\n`{}`\nExpires: **{}**".format(record.key, record.expires.isoformat())
            )
    except discord.HTTPException:
        pass
    await ctx.reply(
        "Generated `{}` for <@{}> (expires {}). {}".format(record.key, discord_id, record.expires, push_msg),
        delete_after=30,
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    log.exception("Command error: %s", error)


def main():
    if not TOKEN:
        print("Set DISCORD_TOKEN in discord-bot/.env")
        sys.exit(1)
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
