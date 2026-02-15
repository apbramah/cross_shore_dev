import subprocess
from pathlib import Path

Import("env")

project_dir = Path(env["PROJECT_DIR"])

def run_git(args):
    return subprocess.check_output(
        ["git", "-C", str(project_dir)] + args,
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()

version = "unknown"
try:
    version = run_git(["rev-parse", "--short", "HEAD"])
    status = run_git(["status", "--porcelain"])
    if status:
        version = f"{version}-dirty"
except Exception:
    pass

env.Append(CPPDEFINES=[("FW_VERSION", f"\\\"{version}\\\"")])
