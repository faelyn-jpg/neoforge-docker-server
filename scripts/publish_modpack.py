#!/home/faebian/repos/mc-server/scripts/.venv/bin/python
import subprocess
import tomllib
import argparse
import json
from test_mods import (
    format_changelog,
    snapshot_mods,
    diff_mods,
    update_pack_toml,
    update_bcc_config,
    upload_to_curseforge,
    get_zip_path,
    format_curseforge_changelog,
    save_baseline,
)
from dotenv import load_dotenv
from pathlib import Path

parser = argparse.ArgumentParser(description="Publish Furber modpack")
parser.add_argument("--upload-only", action="store_true", help="Skip menu, go straight to upload-only")
parser.add_argument("--save-baseline", action="store_true", help="Skip menu, go straight to save-baseline")
args = parser.parse_args()
load_dotenv(Path(__file__).parent.parent / ".env")
MODPACK_DIR = Path(__file__).parent.parent / "modpack"
BCC_CONFIG = Path(__file__).parent.parent / "modpack/config/bcc-common.toml"
CHANGELOG_PATH = Path(__file__).parent / "last_changelog.json"
BASELINE_PATH = Path(__file__).parent / "baseline_mods.json"


def load_baseline():
    """Load the last saved baseline snapshot (state at last publish)."""
    if not BASELINE_PATH.exists():
        return {}
    with open(BASELINE_PATH) as f:
        return json.load(f)


def confirm(prompt: str) -> bool:
    """Blocking y/n confirmation. Anything other than y/yes is a no."""
    resp = input(f"{prompt} [y/N]: ").strip().lower()
    return resp in ("y", "yes")

MENU = {
    "1": ("full", "Full publish — update mods, bump version, export, and upload to CurseForge"),
    "2": ("upload_only", "Upload only — skip update/export, just upload the existing zip for the current version"),
    "3": ("save_baseline", "Save baseline — snapshot current mod state as the baseline, without publishing anything"),
}

def choose_action() -> str:
    print("What would you like to do?")
    for key, (_, desc) in MENU.items():
        print(f"  {key}) {desc}")
    while True:
        choice = input(f"Enter {'/'.join(MENU.keys())}: ").strip()
        if choice in MENU:
            return MENU[choice][0]
        print(f"Please enter one of: {', '.join(MENU.keys())}")

if args.save_baseline:
    action = "save_baseline"
elif args.upload_only:
    action = "upload_only"
else:
    action = choose_action()

with open(MODPACK_DIR / "pack.toml", "rb") as f:
    pack = tomllib.load(f)
if action == "save_baseline":
    save_baseline()
    print("Baseline updated.")
    exit(0)
current_version = pack["version"]
print(f"Current version: {current_version}")

if action == "upload_only":
    new_version = current_version
    if CHANGELOG_PATH.exists():
        with open(CHANGELOG_PATH) as f:
            saved = json.load(f)
        if saved.get("version") != current_version:
            print(f"Saved changelog is for v{saved.get('version')}, but pack.toml is "
                  f"at v{current_version} — refusing to reuse it.")
            added, removed, updated = {}, {}, {}
            notes = input("Enter notes for CurseForge: ").strip()
        else:
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
    do_mass_update = bump in ("major", "minor")
    before = load_baseline()

    if do_mass_update:
        if not confirm(f"About to run 'packwiz update --all' for a {bump} bump. Continue?"):
            print("Aborted.")
            exit(0)
        print("Updating mods...")
        subprocess.run(["packwiz", "update", "--all"], cwd=MODPACK_DIR)
    else:
        print(f"Skipping mass mod update for a '{bump}' bump — only picking up manual changes.")

    print("Snapshotting current mod list...")
    after = snapshot_mods(MODPACK_DIR / "mods")

    added, removed, updated = diff_mods(before, after)
    print(f"\nChanges:")
    print(f" Added: {len(added)}")
    print(f" Removed: {len(removed)}")
    print(f" Updated: {len(updated)}")

    if (added or removed or updated) and not confirm("Review the counts above — proceed with this changelog?"):
        print("Aborted. No files were changed on CurseForge.")
        exit(0)

    notes = input("\nAny additional changelog notes? (press Enter to skip): ").strip()
    changelog = format_changelog(added, removed, updated, notes)

    with open(CHANGELOG_PATH, "w") as f:
        json.dump({
            "version": new_version,
            "added": added,
            "removed": removed,
            "updated": updated,
            "notes": notes,
            "changelog": changelog,
        }, f, indent=2)
    print(f"\nChangelog:\n{changelog}")

    if bump != "none":
        print(f"Bumping version to {new_version}...")
        update_pack_toml(MODPACK_DIR / "pack.toml", new_version)
        print("Version updated in pack.toml")

    print(f"Updating bcc-common.toml to {new_version}...")
    update_bcc_config(BCC_CONFIG, new_version)
    print("bcc-common.toml updated")

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

zip_path = get_zip_path(new_version)

cf_changelog = format_curseforge_changelog(added, removed, updated, notes)

if not confirm(f"Ready to upload {zip_path.name} to CurseForge as {new_version}. Proceed?"):
    print("Aborted before upload. Nothing changed — baseline and changelog are untouched, "
          "so re-running will still show the full set of changes above.")
    exit(0)
try:
    file_id = upload_to_curseforge(zip_path, new_version, cf_changelog)
except Exception as e:
    print(f"Upload failed: {e}")
    print("Baseline and changelog were NOT updated — re-run when ready and the "
          "full diff above will still be included.")
    raise

save_baseline()
print("Baseline updated.")
