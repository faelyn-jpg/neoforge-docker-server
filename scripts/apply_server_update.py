#!/home/faebian/repos/mc-server/scripts/.venv/bin/python
import subprocess
import json
import re
import docker
import webbrowser
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
SCRIPTS_DIR = Path(__file__).parent
MODPACK_DIR = Path(__file__).parent.parent / "modpack"
BCC_CONFIG = Path(__file__).parent.parent / "worlds/shared/config/bcc-common.toml"
CHANGELOG_PATH = SCRIPTS_DIR / "last_changelog.json"
REPO_DIR = Path(__file__).parent.parent
MODS_DIR = REPO_DIR / "worlds/shared/mods"
LOG_PATH = SCRIPTS_DIR / "update_log.md"

if not CHANGELOG_PATH.exists():
    print("No pending update found (last_changelog.json missing!)")
    exit(1)

with open(CHANGELOG_PATH) as f:
    saved = json.load(f)

new_version = saved["version"]
changelog = saved["changelog"]

print(f"Applying server update to version {new_version}!")
print(f"\nChangelog:\n{changelog}\n")
confirm = input("Proceed? (y/n): ").strip().lower()
if confirm != "y":
    print("Aborted")
    exit(0)

docker_client = docker.from_env()
container = docker_client.containers.get("survival")
if container.status == "running":
    print("WARNING: Survival server is currently running!")
    confirm = input("Stop server and apply update? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted")
        exit(0)
    container.stop(timeout=60)
    print("Server stopped")

print("Starting packwiz serve...")
serve_process = subprocess.Popen(
    ["packwiz", "serve"],
    cwd=MODPACK_DIR,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

def run_with_packwiz():
    return subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.packwiz.yml", "up", "survival"],
        capture_output=True,
        text=True,
        cwd=REPO_DIR
    )

def handle_manual_downloads(log_output):
    pattern = r'Please go to (httpsL//\S+) and save this file to (/data/mods/\S+)'
    downloads = re.findall(pattern, log_output)
    if not downloads:
        return False
    seen = set()
    unique = [(url, path) for url, path in downloads if url not in seen and not seen and not seen.add(url)]
    print(f"\n{len(unique)} mods need manual downloading:")
    for url, container_path in unique: 
        filename = container_path.split("/")[-1]
        dest = MODS_DIR / filename
        print(f"\n {filename}")
        print(f" Save to: {dest}")
        webbrowser.open(url)
    input("\nDownload all files to the listed locations, then press Enter to retry...")
    return True

try:
    result = run_with_packwiz()
    logs = result.stdout + result.stderr
    
    if result.returncode != 0:
        had_manual = handle_manual_downloads(logs)
        if had_manual:
            print("Retrying...")
            result = run_with_packwiz()
            if result.returncode != 0:
                print("Still failing after manual downloads:")
                print(result.stdout + result.stderr)
                exit(1)
        else:
            print("Failed with no manual downloads needed:")
            print(logs)
            exit(1)

    print(f"Updating bcc-common.toml to {new_version}...")
    with open(BCC_CONFIG, "r") as f:
        content = f.read()
    content = re.sub(r'modpackVersion = ".*?"', f'modpackVersion = "{new_version}"', content)
    with open(BCC_CONFIG, "w") as f:
        f.write(content)
    print("bcc-common.toml updated")

    log_path = SCRIPTS_DIR / "update_log.md"
    with open(log_path, "a") as f:
        f.write(f"\n## {new_version} — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(changelog)
        f.write("\n")
    print("Log entry written")

    subprocess.run(["git", "add", "."], cwd=REPO_DIR)
    subprocess.run(["git", "commit", "-m", f"update modpack to {new_version}"], cwd=REPO_DIR)
    subprocess.run(["git", "push"], cwd=REPO_DIR)
    print("Changes committed and pushed")
    print("Done!")

finally:
    print("Stopping packwiz serve...")
    serve_process.terminate()
    serve_process.wait()
    print("Stopping packwiz container...")
    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.packwiz.yml", "down", "survival"],
        cwd=REPO_DIR
    )

    # Start normally without packwiz URL
    print("Starting survival server normally...")
    subprocess.run(
        ["docker", "compose", "up", "-d", "survival"],
        cwd=REPO_DIR
    )
