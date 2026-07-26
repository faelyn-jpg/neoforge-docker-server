from pathlib import Path
file_path = Path(__file__).parent.parent / "worlds/shared/config/villagernames/customnames.txt"

def read_villagernames():
    with open(file_path, "r") as f:
        content = f.read()
        return content

def write_villagernames(all_names):
    with open(file_path, "w") as f:
        f.write(",\n".join(all_names) + ",")

def is_valid_name(name: str) -> bool:
    if not name or len(name) > 30:
        return False
    if "§" in name or "," in name:
        return False
    if any(ord(c) < 32 for c in name):
        return False
    return True

def update_villagernames(new):
    content = read_villagernames()
    old = [name.strip() for name in content.split(",") if name.strip()]
    new = [name.strip() for name in new.split(",") if name.strip()]
    invalid = [name for name in new if not is_valid_name(name)]
    new = [name for name in new if is_valid_name(name)]
    unique = [name for name in new if name not in old]
    duplicates = [name for name in new if name in old]
    all_names = old + unique
    write_villagernames(all_names)
    return unique, duplicates, invalid

