"""
Shared launcher for PX4 SITL multi-vehicle scenarios.

Scenario scripts (e.g. launch_multi_atmos.py) configure specifics
like number of vehicles, models, poses, names and the world to use.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import shlex
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
MODEL_AUTOSTART = {
    "gz_atmos":              70000,
    "gz_atmos_dual":         70001,
    "gz_uuv_bluerov2_heavy": 60002,
}

MODEL_BUILD = {
    "gz_atmos":              "px4_sitl_spacecraft",
    "gz_atmos_dual":         "px4_sitl_spacecraft",
    "gz_uuv_bluerov2_heavy": "px4_sitl_uuv",
}

# Always set on every vehicle
ALWAYS_ENV = {"PX4_GZ_NO_FOLLOW": "1"}

# Env vars that get rendered onto the PX4 command line
PROPAGATED_KEYS = [
    "PX4_SYS_AUTOSTART",
    "PX4_SIM_MODEL",
    "PX4_UXRCE_DDS_NS",
    "PX4_GZ_MODEL_NAME",
    "PX4_GZ_MODEL_POSE",
    "PX4_GZ_WORLD",
    "PX4_GZ_STANDALONE",
    "PX4_GZ_NO_FOLLOW",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class Vehicle:
    """Vehicle to launch in a scenario."""
    name: str
    model: str
    pose: tuple = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def launch(vehicles,
           world: str = "default",
           px4_dir: str | None = None,
           session: str = "px4sitl",
           startup_delay: float = 6.0):
    """Launch the given list of Vehicles."""
    p = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Launch the PX4 SITL scenario defined in this file.",
    )
    p.add_argument("--startup-delay", type=float, default=startup_delay)
    p.add_argument("--kill", action="store_true",
                   help="kill the tmux session and exit")
    args = p.parse_args()

    if args.kill:
        if shutil.which("tmux"):
            subprocess.run(["tmux", "kill-session", "-t", session])
            print(f"killed tmux session '{session}' (if it existed)")
        # Also kill any leftover gz sim processes, which tmux won't always get
        subprocess.run(["pkill", "-f", "gz sim"])
        time.sleep(1.0)
        subprocess.run(["pkill", "-9", "-f", "gz sim"])
        print("killed any leftover 'gz sim' processes")
        return

    if not vehicles:
        sys.exit("No vehicles defined in scenario.")

    # Resolve PX4 dir
    if px4_dir is None:
        px4_dir = os.environ.get("PX4_Autopilot_Dir")
    if not px4_dir:
        sys.exit("PX4 dir not set: export $PX4_Autopilot_Dir or pass px4_dir=")
    px4_dir = Path(px4_dir).expanduser().resolve()
    
    # Validate models and check each required build is present.
    for v in vehicles:
        if v.model not in MODEL_BUILD:
            sys.exit(f"No build target known for model {v.model!r}. "
                     f"Add it to MODEL_BUILD in px4_sitl_launcher.py.")
    needed_builds = {MODEL_BUILD[v.model] for v in vehicles}
    for build in needed_builds:
        px4_bin = px4_dir / "build" / build / "bin" / "px4"
        if not px4_bin.is_file():
            sys.exit(f"PX4 binary not found at {px4_bin}.\n"
                     f"-> run `make {build}` in {px4_dir} first.")

    # Build per-vehicle commands
    commands = []
    for i, v in enumerate(vehicles):
        env = _build_env(v, world=world, standalone=(i > 0))
        commands.append((v.name, i,
                         _build_command(px4_dir, MODEL_BUILD[v.model], i, env)))

    # Summary
    print(f"PX4 dir : {px4_dir}")
    print(f"world   : {world}")
    print(f"vehicles: {len(vehicles)}")
    for name, instance, cmd in commands:
        print(f"  - {name:<10} i={instance}  {cmd}")
    print()

    _launch_tmux(commands, session, args.startup_delay)


def _build_env(vehicle: Vehicle, world: str, standalone: bool) -> dict:
    if vehicle.model not in MODEL_AUTOSTART:
        raise SystemExit(
            f"Unknown model {vehicle.model!r}. "
            f"Known: {list(MODEL_AUTOSTART)}. "
            f"Add it to MODEL_AUTOSTART in px4_sitl_launcher.py."
        )
    env = {
        "PX4_SYS_AUTOSTART": str(MODEL_AUTOSTART[vehicle.model]),
        "PX4_SIM_MODEL":     vehicle.model,
        "PX4_UXRCE_DDS_NS":  vehicle.name,
        "PX4_GZ_MODEL_POSE": ",".join(f"{v:g}" for v in vehicle.pose),
    }
    if world and world.lower() != "default":
        env["PX4_GZ_WORLD"] = world
    if standalone:
        env["PX4_GZ_STANDALONE"] = "1"
    env.update(ALWAYS_ENV)
    return env


def _env_prefix(env: dict) -> str:
    ordered = [(k, env[k]) for k in PROPAGATED_KEYS if k in env]
    return " ".join(f"{k}={v}" for k, v in ordered)


def _build_command(px4_dir: Path, build: str, instance: int, env: dict) -> str:
    px4_bin = px4_dir / "build" / build / "bin" / "px4"
    return f"cd {px4_dir} && {_env_prefix(env)} {px4_bin} -i {instance}"


def _launch_tmux(commands, session, delay):
    forward_keys = [
        "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
        "LD_LIBRARY_PATH", "GZ_SIM_RESOURCE_PATH",
        "GZ_VERSION", "HOME", "PATH",
    ]

    env_exports = "; ".join(
        f"export {k}={shlex.quote(os.environ[k])}"
        for k in forward_keys if k in os.environ
    )

    name, instance, cmd = commands[0]
    subprocess.run(["tmux", "new-session", "-d", "-s", session,
                    "-n", name, "bash", "-c", f"{env_exports}; {cmd}"], check=True)

    # Server now exists — sync env into it
    for key in forward_keys:
        if key in os.environ:
            subprocess.run(["tmux", "set-environment", "-g", key, os.environ[key]])
    print(f"  [{name}] PX4 instance {instance}  (gz-server host)")

    if len(commands) > 1:
        _wait_for_gz_server(delay)

    for name, instance, cmd in commands[1:]:
        subprocess.run(["tmux", "new-window", "-t", session, "-n", name,
                        "bash", "-c", f"{env_exports}; {cmd}"], check=True)
        print(f"  [{name}] PX4 instance {instance}  (standalone, attaching)")

    print()
    print(f"tmux session '{session}' is up.")
    print(f"  attach :  tmux attach -t {session}")
    print(f"  windows:  Ctrl-b 1/2/3   or   Ctrl-b n / Ctrl-b p")
    print(f"  kill   :  tmux kill-session -t {session}    "
          f"(or rerun the script with --kill)")


def _wait_for_gz_server(timeout: float):
    deadline = time.monotonic() + timeout
    print(f"  waiting for gz-server readiness (timeout {timeout:g}s) ...")

    while time.monotonic() < deadline:
        if _gz_server_is_running():
            print("  gz-server is up")
            return
        time.sleep(0.5)

    print("  warning: gz-server was not detected before timeout; continuing anyway")


def _gz_server_is_running() -> bool:
    probes = (
        ["pgrep", "-f", r"gz sim"],
        ["pgrep", "-f", r"gz server"],
    )
    for probe in probes:
        result = subprocess.run(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return True
    return False
