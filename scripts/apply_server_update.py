#!/home/faebian/repos/mc-server/scripts/.venv/bin/python
import subprocess
import json
import re
import time
import docker
from datetime import datetime
from docker import errors as docker_errors
import webbrowser
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
SCRIPTS_DIR = Path(__file__).parent
MODPACK_DIR = Path(__file__).parent.parent / "modpack"
BCC_CONFIG = Path(__file__).parent.parent / "worlds/shared/config/bcc-common.toml"
CHANGELOG_PATH = SCRIPTS_DIR / "last_changelog.json"
REPO_DIR = Path(__file__).parent.parent
MODS_DIR = REPO_DIR / "worlds/shared"
LOG_PATH = SCRIPTS_DIR / "update_log.md"
PACKWIZ_BOOTSTRAP = SCRIPTS_DIR / "packwiz-installer-bootstrap.jar"


print("Stopping FurberBot...")
subprocess.run(["sudo", "systemctl", "stop", "furberbot"])

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
try:   
    container = docker_client.containers.get("survival")
    if container.status == "running":
        print("WARNING: Survival server is currently running!")
        confirm = input("Stop server and apply update? (y/n): ").strip().lower()
        if confirm != "y":
            print("Aborted")
            exit(0)
        container.stop(timeout=60)
        print("Server stopped")
except docker_errors.NotFound:
    print("Survival container not found, continuing...")

print("Starting packwiz serve...")
serve_process = subprocess.Popen(
    ["packwiz", "serve"],
    cwd=MODPACK_DIR,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
time.sleep(2)
if serve_process.poll() is not None:
    print("ERROR: packwiz serve failed to start!")
    exit(1)
print("packwiz serve is running")

def run_packwiz_installer():
    print("Running packwiz-installer...")
    return subprocess.run([
        "java", "-jar", str(PACKWIZ_BOOTSTRAP),
        "-g", "-s", "server",
        f"http://localhost:8080/pack.toml",
        "--pack-folder", str(MODS_DIR)
    ], capture_output=True, text=True)

def handle_manual_downloads(log_output):
    pattern = r'Please go to (https://\S+) and save this file to (\S+\.jar)'
    downloads = re.findall(pattern, log_output)
    if not downloads:
        return False
    seen = set()
    unique = [(url, path) for url, path in downloads if url not in seen and not seen.add(url)]
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
    install_result = run_packwiz_installer()
    print(install_result.stdout)
    print(install_result.stderr)
    logs = install_result.stdout + install_result.stderr

    if install_result.returncode != 0:
        had_manual = handle_manual_downloads(logs)
        if had_manual:
            install_result = run_packwiz_installer()
            print(install_result.stdout)
            print(install_result.stderr)
            if install_result.returncode != 0:
                print("Still failing after manual downloads")
                serve_process.terminate()
                exit(1)
        else:
            print("Failed with no manual downloads needed:")
            print(logs)
            serve_process.terminate()
            exit(1)

    print(f"Updating bcc-common.toml to {new_version}...")
    with open(BCC_CONFIG, "r") as f:
        content = f.read()
    content = re.sub(r'modpackVersion = ".*?"', f'modpackVersion = "{new_version}"', content)
    with open(BCC_CONFIG, "w") as f:
        f.write(content)
    print("bcc-common.toml updated")

    print("Starting FurberBot...")
    subprocess.run(["sudo", "systemctl", "start", "furberbot"])

    with open(LOG_PATH, "a") as f:
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
    serve_process.terminate()
    serve_process.wait()
    print("packwiz serve stopped")
  
