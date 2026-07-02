import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from mcrcon import MCRcon
from datetime import datetime, timedelta, timezone
import os
import docker
import asyncio
import time
import json
import subprocess
import requests


with open("../config/config.json") as f:
    config = json.load(f)

client = docker.from_env()
load_dotenv("../.env")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)
queue_channel_id = int(os.getenv("QUEUE_CHANNEL_ID", 0))
command_channel_id = int(os.getenv("COMMAND_CHANNEL_ID", 0))
bot_channel_id = int(os.getenv("BOT_CHANNEL_ID", 0))
furbletbot_user_id = int(os.getenv("FURBLETBOT_USER_ID", 0))
plex_token = os.getenv("PLEX_TOKEN")
idle_counts = {
        "survival": 0,
        "creative": 0,
        }
boot_time = datetime.now(timezone.utc)
remote_wake = False
AUTO_SHUTDOWN_DISABLED = "/tmp/no_shutdown"

def is_plex_active():
    try:
        response = requests.get(
                f"http://localhost:32400/status/sessions",
                headers={"Accept": "application/json"},
                params={"X-Plex-Token": plex_token}
                )
        data = response.json()
        return data["MediaContainer"]["size"] > 0
    except Exception as e:
        print(f'Error determining if plex is active: {e}')
        return False

def is_samba_active():
    try:
        result = subprocess.run(['sudo', 'smbstatus', '-p'], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        return len(lines) > 3
    except Exception as e:
        return f'Samba Active : Error {e}'

def are_users_logged_in():
    try: 
        result = subprocess.run(['who'], capture_output=True, text=True)
        users = result.stdout.strip().split('\n')
        return len([user.split()[0] for user in users if user]) > 0
    except Exception as e:
        return f'Users Logged in : Error {e}'

async def safe_to_shutdown():
    if os.path.exists(AUTO_SHUTDOWN_DISABLED):
        return False
    grace_period = not remote_wake and (datetime.now(timezone.utc) - boot_time).total_seconds() < 1800
    samba_active = is_samba_active()
    print(f'samba active? {samba_active}')
    plex_active = is_plex_active()
    print(f'plex active?{plex_active}')
    users_logged_in = are_users_logged_in()
    survival_safe = await is_server_empty("survival")
    creative_safe = await is_server_empty("creative")
    return not (samba_active or plex_active or users_logged_in or grace_period) and survival_safe and creative_safe


async def wait_for_server(container, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        logs = container.logs(tail=20).decode("utf-8")
        if "Dedicated server took" in logs:
            return True
        await asyncio.sleep(3)
    return False

async def is_server_empty(target_server):
    try:
        port = config["servers"][target_server]["rcon_port"]
        with MCRcon("127.0.0.1", os.getenv("RCON_PASSWORD"), port=port) as rcon:
            response= rcon.command("list")
            player_count = int(response.split()[2])
            return player_count == 0
    except Exception as e:
        print (f' Offline or Unreahable {target_server} server: {e}')
        return "offline"

async def handle_idle_server(target_server):
    server_empty = await is_server_empty(target_server)
    if server_empty == "offline": 
        return
    elif server_empty:
       idle_counts[target_server] += 1 
    else: 
        idle_counts[target_server] = 0
    if idle_counts[target_server] >= 5:
        idle_counts[target_server] = 0
        client.containers.get(target_server).stop(timeout=30)
        return "stop server"

async def shutdown():
    channel = bot.get_channel(command_channel_id)
    if isinstance(channel, discord.TextChannel):
        await channel.send("PC shutting down due to inactivity.")
    await asyncio.to_thread(subprocess.run, ['sudo', 'shutdown', 'now'])

async def poll_survival():
    try:
        await handle_idle_server("survival")
    except Exception as e:
        print(f' Error polling survival: {e}')

async def poll_creative():
    try:
        await handle_idle_server("creative")
    except Exception as e:
        print(f' Error polling creative: {e}')

@tasks.loop(seconds=300)
async def poll():
    try:
        await poll_creative()
        await poll_survival()
        if await safe_to_shutdown():
            await shutdown()
    except Exception as e:
        print(f'Error polling: {e}')

async def check_channel_for_wake(channel_id):
    channel = bot.get_channel(channel_id)
    if isinstance(channel, discord.TextChannel):
        async for message in channel.history(limit=1):
            if message.author.id == furbletbot_user_id:
                start_window = boot_time - timedelta(minutes=5)
                return message.created_at > start_window
    return False

async def was_remote_wake():
    try:
        return await check_channel_for_wake(command_channel_id) or await check_channel_for_wake(bot_channel_id)
    except Exception as e:
        print(f'Error checking if remote wake: {e}')
        return False

async def read_queue():
    try:
        channel = bot.get_channel(queue_channel_id)
        if isinstance(channel, discord.TextChannel):
            pending = set()
            async for message in channel.history(limit=10):
                if message.content.startswith("pending:"):
                    target_server = message.content.split(":")[1]
                    pending.add(target_server)
                    await message.delete()
            return pending
    except Exception as e:
        print(f'Error reading queue: {e}')


async def start_server(target_server, on_running=None, on_started=None, on_failed=None):
    try: 
        container = client.containers.get(target_server)
        if container.status == "running":
            if on_running:
                await on_running()
            return
        container.start()
        success = await wait_for_server(container)
        if success:
            if on_started:
                await on_started()
        else:
            container.stop(timeout=30)
            if on_failed:
                await on_failed()
    except Exception as e:
        print(f'Error starting {target_server}: {e}')

async def stop_server(target_server, on_exited=None, on_stop=None, on_failed=None):
    try:
        container = client.containers.get(target_server)
        if container.status == "exited":
            if on_exited:
                await on_exited()
            return
        await asyncio.to_thread(container.stop, timeout=30)
        container.reload()
        if container.attrs["State"]["ExitCode"] == 137:
            if on_failed:
                await on_failed()
        else: 
            if on_stop:
                await on_stop()
    except Exception as e:
        print(f'Error stopping {target_server} server: {e}')

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    global remote_wake
    remote_wake = await was_remote_wake()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
        await safe_to_shutdown()
        queue = await read_queue()
        if queue and len(queue) > 0:
            for server in queue:
                await start_server(server)
        poll.start()
    except Exception as e:
        print(f'Error initilzing bot: {e}')

@bot.tree.command(name="status", description="Check the survival server status")
async def status(interaction: discord.Interaction):
    try:
        with MCRcon("127.0.0.1", os.getenv("RCON_PASSWORD"), port=25575) as rcon:
            response = rcon.command("list")
            await interaction.response.send_message(f"Server is online!\n{response}")
    except Exception as e:
        print(e)
        await interaction.response.send_message(f"Server is offline or unreachable. You can use /start (server name) to turn it on :D")

@bot.tree.command(name="start", description="Start a server")
@app_commands.describe(target_server="Which server to start (default: survival)")
@app_commands.choices(target_server=[
    app_commands.Choice(name="survival", value="survival"),
    app_commands.Choice(name="creative", value="creative"),
])
async def start(interaction: discord.Interaction, target_server: str = "survival"):
    try:
        await interaction.response.send_message(f"Starting {target_server}! :3")
        await start_server(
            target_server, 
            on_running=lambda: interaction.followup.send(f"The {target_server} server is already running, go join! :D"),
            on_started=lambda: interaction.followup.send(f"Server is online! Have fun :'Y"),
            on_failed=lambda: interaction.followup.send(f"Server failed to start in time....")
            )
    except Exception as e:
        print(e)
        await interaction.followup.send(f"Oops! Something went wrong....")

@bot.tree.command(name="stop", description="Stop a server")
@app_commands.default_permissions(discord.Permissions(administrator=True))
@app_commands.describe(target_server="Which server to stop (default: survival)")
@app_commands.choices(target_server=[
    app_commands.Choice(name="survival", value="survival"),
    app_commands.Choice(name="creative", value="creative"),
])
async def stop(interaction: discord.Interaction, target_server: str = "survival"):
    try:
        container = client.containers.get(target_server)
        if container.status == "exited":
            await interaction.response.send_message(f"The {target_server} server isn't running.")
        else: 
            await interaction.response.send_message(f"Stopping {target_server} server.")
            container.stop(timeout=60)
    except Exception as e:
        print(e)
        await interaction.response.send_message(f"Oops! Something went wrong.")

@bot.tree.command(name="disable-shutdown", description="Disable automatic shutdown")
@app_commands.default_permissions(discord.Permissions(administrator=True))
async def disable_shutdown(interaction: discord.Interaction):
    if os.path.exists("/tmp/no_shutdown"):
        await interaction.response.send_message("Already disabled, nothing to do.")
    else: 
        open("/tmp/no_shutdown", "w").close()
        await interaction.response.send_message("Automatic shutdown disabled until next reboot")

@bot.tree.command(name="enable-shutdown", description="Enable automatic shutdown")
@app_commands.default_permissions(discord.Permissions(administrator=True))
async def enable_shutdown(interaction: discord.Interaction):
    if not os.path.exists("/tmp/no_shutdown"):
        await interaction.response.send_message("Already enabled, nothing to do.")
    else:
        os.remove("/tmp/no_shutdown")
        await interaction.response.send_message("Automatic shutdown re-enabled.")
#@bot.tree.command(name="say", description="Say a thing")
#@app_commands.default_permissions(discord.Permissions(administrator=True))
#async def say(interaction: discord.Interaction):
#    try:
#        active_users = check_active_users()
#        await interaction.response.send_message(f"There are {len(active_users)} logged into your PC.")
#    except Exception:
#        await interaction.response.send_message(f"I'm not sure....")

token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("DISCORD_TOKEN not set in .env")
bot.run(token)
