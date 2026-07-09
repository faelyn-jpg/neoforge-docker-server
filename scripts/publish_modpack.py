#!/home/faebian/repos/mc-server/scripts/.venv/bin/python
import subprocess
import tomllib
import argparse
import json
from test_mods import format_changelog, snapshot_mods, diff_mods, format_changelog, update_pack_toml, upload_to_curseforge, get_zip_path, format_curseforge_changelog
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path 

parser = argparse.ArgumentParser(description="Publish Furber modpack")
parser.add_argument("--upload-only", action="store_true", help="Skip update and export, just upload existing zip")
args = parser.parse_args()
load_dotenv(Path(__file__).parent.parent / ".env")
MODPACK_DIR = Path(__file__).parent.parent / "modpack"
BCC_CONFIG = Path(__file__).parent.parent / "worlds/shared/config/bcc-common.toml"
CHANGELOG_PATH = Path(__file__).parent / "last_changelog.json"

with open(MODPACK_DIR / "pack.toml", "rb") as f:
    pack = tomllib.load(f)

current_version = pack["version"]
print(f"Current version: {current_version}")
if args.upload_only:
    new_version = current_version
    if CHANGELOG_PATH.exists():
        with open(CHANGELOG_PATH) as f:
            saved = json.load(f)
        added = saved["added"]
        removed = saved["removed"]
        updated = saved["updated"]
        notes = saved["notes"]
    else:
        added, removed, updated = {}, {}, {}
        notes = input("No saved changelog found. Enter notes for CurseForge: ").strip()
else:
    major, minor, patch = map(int, current_version.split("."))
    bump = input("Which part to bump? (major/minor/patch/none): ").strip().lower()

    if bump == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump == "minor":
        minor += 1
        patch = 0
    elif bump == "patch":
        patch += 1
    elif bump == "none":
        pass
    else:
        print("Invalid input, expected major, minor, patch, or none")
        exit(1)

    new_version = f"{major}.{minor}.{patch}"
    print(f"New version: {new_version}")

    print("Snapshotting mod list before update...")
    before = snapshot_mods(MODPACK_DIR / "mods")
    print("Updating mods...")
    subprocess.run(["packwiz", "update", "--all", "-y"], cwd=MODPACK_DIR)
    print("Snapshotting mod list after update...")
    after = snapshot_mods(MODPACK_DIR / "mods")

    added, removed, updated = diff_mods(before, after)
    print(f"\nChanges:")
    print(f" Added: {len(added)}")
    print(f" Removed: {len(removed)}")
    print(f" Updated: {len(updated)}")

    notes = input("\nAny additional changelog notes? (press Enter to skip): ").strip()
    changelog = format_changelog(added, removed, updated, notes)
    if bump != "none" or not CHANGELOG_PATH.exists():
        with open(CHANGELOG_PATH, "w") as f:
            json.dump({
                "version": new_version,
                "added": added,
                "removed": removed,
                "updated": updated,
                "notes": notes,
                "changelog": changelog
                }, f, indent=2)
        print(f"\nChangelog:\n{changelog}")
    else: 
        print("Keeping existing changelog")
    
    if bump != "none":
        print(f"Bumping version to {new_version}...")
        update_pack_toml(MODPACK_DIR / "pack.toml", new_version)
        print("Version updated in pack.toml")
    
    print("Exporting modpack...")
    export_result = subprocess.run(
        ["packwiz", "cf", "export"],
        capture_output=True,
        text=True,
        cwd=MODPACK_DIR
    )

    if export_result.returncode != 0:
        print(f"Export failed:\n{export_result.stderr}")
        exit(1)

    print("Export successful")

zip_path = get_zip_path()
cf_changelog = format_curseforge_changelog(added, removed, updated, notes)
file_id = upload_to_curseforge(zip_path, new_version, cf_changelog)
