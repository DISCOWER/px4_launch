"""
Shared launcher for PX4 SITL multi-vehicle scenarios.

Scenario scripts (e.g. launch_single_atmos.py) define a list of `Vehicle`s
and a world, then call `launch(...)`.

To add a new vehicle model, just add it to MODEL_AUTOSTART below.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Model registry — add new models here and they're available everywhere.
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

# Always set on every vehicle.
ALWAYS_ENV = {"PX4_GZ_NO_FOLLOW": "1"}

# Env vars that get rendered onto the PX4 command line. Anything not in this
# whitelist is dropped (keeps the printed command readable).
PROPAGATED_KEYS = [
    "PX4_SYS_AUTOSTART",
    "PX4_SIM_MODEL",
    "PX4_UXRCE_DDS_NS",
    "PX4_GZ_MODEL_NAME",
    "PX4_GZ_MODEL_POSE",
    "PX4_GZ_WORLD",
    "PX4_GZ_STANDALONE",
    "PX4_GZ_NO_FOLLOW",
    "PX4_GZ_SIM_RENDER_ENGINE",
    "PX4_SIM_SPEED_FACTOR",
    "PX4_GZ_FOLLOW_OFFSET_X",
    "PX4_GZ_FOLLOW_OFFSET_Y",
    "PX4_GZ_FOLLOW_OFFSET_Z",
    "PX4_GZ_PLATFORM_VEL",
    "PX4_GZ_PLATFORM_HEADING_DEG",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class Vehicle:
    """One PX4 SITL instance.

    pose is (x, y, z[, roll, pitch, yaw]); missing fields => 0.
    extra_env applies only to this vehicle (overrides scenario-wide env).
    """
    name: str
    model: str
    pose: tuple = (0.0, 0.0, 0.0)
    extra_env: dict = field(default_factory=dict)


def launch(vehicles,
           world: str = "default",
           px4_dir: str | None = None,
           session: str = "px4sitl",
           startup_delay: float = 6.0,
           sim_speed: float | None = None,
           render_engine: str | None = None,
           extra_env: dict | None = None):
    """Launch the given list of Vehicles.

    Vehicle 0 hosts gz-server; the rest get PX4_GZ_STANDALONE=1.

    Each scenario script also gets these CLI flags for free:
      --terminal {tmux,gnome,xterm,none}    how to host each PX4 process
      --session NAME                        override tmux session name
      --startup-delay SEC                   override delay between vehicle 1 and rest
      --kill                                kill the tmux session and exit
      --dry-run                             print commands and exit
    """
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
        # Reap orphan gz-server. Try SIGTERM first for a graceful shutdown,
        # then SIGKILL since gz sim ignores SIGTERM when it's been juggling
        # several PX4 clients (common in multi-vehicle scenarios).
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

    # Build common env
    common_env = dict(extra_env or {})
    if sim_speed is not None:
        common_env["PX4_SIM_SPEED_FACTOR"] = str(sim_speed)
    if render_engine:
        common_env["PX4_GZ_SIM_RENDER_ENGINE"] = render_engine

    # Build per-vehicle commands
    commands = []
    for i, v in enumerate(vehicles):
        instance = i
        env = _build_env(v, world=world, standalone=(i > 0),
                         common_env=common_env)
        commands.append((v.name, instance,
                         _build_command(px4_dir, MODEL_BUILD[v.model], instance, env)))

    # Summary
    print(f"PX4 dir : {px4_dir}")
    print(f"world   : {world}")
    print(f"vehicles: {len(vehicles)}")
    for name, instance, cmd in commands:
        print(f"  - {name:<10} i={instance}  {cmd}")
    print()

    _launch_tmux(commands, session, args.startup_delay)


# ---------------------------------------------------------------------------
# Internals — you usually don't need to touch these
# ---------------------------------------------------------------------------

def _normalize_pose(pose):
    parts = list(pose) + [0.0] * (6 - len(pose))
    return tuple(parts[:6])


def _build_env(vehicle: Vehicle, world: str, standalone: bool,
               common_env: dict) -> dict:
    if vehicle.model not in MODEL_AUTOSTART:
        raise SystemExit(
            f"Unknown model {vehicle.model!r}. "
            f"Known: {list(MODEL_AUTOSTART)}. "
            f"Add it to MODEL_AUTOSTART in px4_sitl_launcher.py."
        )
    pose = _normalize_pose(vehicle.pose)
    env = {
        "PX4_SYS_AUTOSTART": str(MODEL_AUTOSTART[vehicle.model]),
        "PX4_SIM_MODEL":     vehicle.model,
        "PX4_UXRCE_DDS_NS":  vehicle.name,
        "PX4_GZ_MODEL_POSE": ",".join(f"{v:g}" for v in pose),
    }
    if world and world.lower() != "default":
        env["PX4_GZ_WORLD"] = world
    if standalone:
        env["PX4_GZ_STANDALONE"] = "1"
    env.update(ALWAYS_ENV)
    env.update(common_env)
    env.update(vehicle.extra_env)
    return env


def _env_prefix(env: dict) -> str:
    ordered = [(k, env[k]) for k in PROPAGATED_KEYS if k in env]
    return " ".join(f"{k}={v}" for k, v in ordered)


def _build_command(px4_dir: Path, build: str, instance: int, env: dict) -> str:
    px4_bin = px4_dir / "build" / build / "bin" / "px4"
    return f"cd {px4_dir} && {_env_prefix(env)} {px4_bin} -i {instance}"


def _launch_tmux(commands, session, delay):
    if not shutil.which("tmux"):
        sys.exit("tmux not found. Install it or pass --terminal gnome|xterm|none.")
    subprocess.run(["tmux", "kill-session", "-t", session],
                   stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    name, instance, cmd = commands[0]
    subprocess.run(["tmux", "new-session", "-d", "-s", session,
                    "-n", name, cmd], check=True)
    print(f"  [{name}] PX4 instance {instance}  (gz-server host)")

    if len(commands) > 1:
        print(f"  waiting {delay:g}s for gz-server to come up ...")
        time.sleep(delay)

    for name, instance, cmd in commands[1:]:
        subprocess.run(["tmux", "new-window", "-t", session, "-n", name, cmd],
                       check=True)
        print(f"  [{name}] PX4 instance {instance}  (standalone, attaching)")

    print()
    print(f"tmux session '{session}' is up.")
    print(f"  attach :  tmux attach -t {session}")
    print(f"  windows:  Ctrl-b 1/2/3   or   Ctrl-b n / Ctrl-b p")
    print(f"  kill   :  tmux kill-session -t {session}    "
          f"(or rerun the script with --kill)")
