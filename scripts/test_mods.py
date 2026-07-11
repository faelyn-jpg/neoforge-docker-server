#!/home/faebian/repos/mc-server/scripts/.venv/bin/python
import tomllib
import tomli_w
import re
import os
import requests
import json
from dotenv import load_dotenv
from pathlib import Path

MODPACK_DIR = Path(__file__).parent.parent / "modpack"
SCRIPTS_DIR = Path(__file__).parent
mods_dir = MODPACK_DIR / "mods"
load_dotenv("../.env")
project_id = int(os.getenv("MODPACK_PROJECT_ID", 0))
api_key: str = os.getenv("CURSEFORGE_API_KEY", "")


def snapshot_mods(mods_dir):
    mods = {}
    for f in sorted(mods_dir.glob("*.pw.toml")):
        with open(f, "rb") as fp:
            data = tomllib.load(fp)
        mods[data["name"]] = {
            "filename": data["filename"],
            "side": data.get("side", "both")
        }
    return mods

def diff_mods(before, after):
    added = {k: v for k, v in after.items() if k not in before}
    removed = {k: v for k, v in before.items() if k not in after}
    updated = {
        k: {"before": before[k]["filename"], "after": after[k]["filename"], "side": after[k]["side"]}
        for k in after
        if k in before and before[k]["filename"] != after[k]["filename"]
    }
    return added, removed, updated

def format_changelog(added, removed, updated, notes):
    lines = []
    
    if updated:
        lines.append("### Updated")
        for name, info in sorted(updated.items()):
            lines.append(f"- {name} ({info['side']}): {info['before']} → {info['after']}")
    
    if added:
        lines.append("\n### Added")
        for name, info in sorted(added.items()):
            lines.append(f"- {name} ({info['side']}): {info['filename']}")
    
    if removed:
        lines.append("\n### Removed")
        for name, info in sorted(removed.items()):
            lines.append(f"- {name} ({info['side']}): {info['filename']}")
    
    if notes:
        lines.append(f"\n### Notes\n{notes}")
    
    return "\n".join(lines)

def update_pack_toml(pack_path, new_version):
    with open(pack_path, "rb") as f:
        pack = tomllib.load(f)
    pack["version"] = new_version
    with open(pack_path, "wb") as f:
        tomli_w.dump(pack, f)

def update_bcc_config(bcc_path, new_version):
    with open(bcc_path, "r") as f:
        content = f.read()
    content = re.sub(
        r'modpackVersion = ".*?"',
        f'modpackVersion = "{new_version}"',
        content
    )
    with open(bcc_path, "w") as f:
        f.write(content)

def upload_to_curseforge(zip_path, version, changelog):  
    metadata = {
        "changelog": changelog,
        "changelogType": "markdown",
        "gameVersionNames": ["1.21.1", "NeoForge"],
        "releaseType": "release"
    }
    
    with open(zip_path, "rb") as f:
        response = requests.post(
            f"https://minecraft.curseforge.com/api/projects/{project_id}/upload-file",
            headers={"X-Api-Token": api_key},
            files={"file": (zip_path.name, f, "application/zip")},
            data={"metadata": json.dumps(metadata)}
        )
    
    if response.status_code == 200:
        file_id = response.json()["id"]
        print(f"Upload successful! File ID: {file_id}")
        return file_id
    else:
        print(f"Upload failed: {response.status_code} {response.text}")
        exit(1)

def get_zip_path():
    zip_files = list(MODPACK_DIR.glob("*.zip"))
    if not zip_files:
        print("No zip found")
        exit(1)
    zip_path = zip_files[0]
    print(f"Found zip: {zip_path.name}")
    return zip_path

def format_curseforge_changelog(added, removed, updated, notes):
    lines = []
    if notes:
        lines.append(notes)
        lines.append("")
    summary = []
    if updated:
        summary.append(f"{len(updated)} mods updated")
    if added:
        summary.append(f"{len(added)} mods added")
    if removed:
        summary.append(f"{len(removed)} mods removed")
    if summary:
        lines.append(", ".join(summary))
    return "\n".join(lines)

def save_baseline():
    baseline = snapshot_mods(MODPACK_DIR / "mods")
    with open(SCRIPTS_DIR / "baseline_mods.json", "w") as f:
        json.dump(baseline, f, indent=2)
    print(f"Baseline saved with {len(baseline)} mods")


