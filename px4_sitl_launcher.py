"""Shared launcher for PX4 SITL multi-vehicle scenarios."""

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
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

SESSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class Vehicle:
    """Vehicle to launch in a scenario."""
    name: str
    model: str
    pose: tuple = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass
class LaunchSpec:
    """Fully resolved command and environment for one vehicle."""
    name: str
    instance: int
    command: list[str]
    cwd: Path
    env: dict[str, str]


def launch(vehicles,
           world: str = "default",
           px4_dir: str | None = None,
           session: str = "px4sitl",
           ):
    """Launch and supervise the given list of Vehicles."""
    p = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Launch the PX4 SITL scenario defined in this file.",
    )
    actions = p.add_mutually_exclusive_group()
    actions.add_argument("--status", action="store_true",
                         help="show the status of this scenario")
    actions.add_argument("--stop", action="store_true",
                         help="stop this scenario")
    p.add_argument("--detach", action="store_true",
                   help="launch in the background and return immediately")
    args = p.parse_args()

    _validate_session_name(session)
    state_path = _state_path(session)

    if args.status:
        _show_status(session, state_path)
        return
    if args.stop:
        _stop_saved_session(session, state_path)
        return

    if not vehicles:
        sys.exit("No vehicles defined in scenario.")
    _validate_vehicles(vehicles)

    existing_state = _read_state(state_path)
    if existing_state and _state_has_running_process(existing_state):
        sys.exit(
            f"Scenario {session!r} is already running. "
            f"Use `{Path(sys.argv[0]).name} --stop` first."
        )
    state_path.unlink(missing_ok=True)

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

    # Resolve per-vehicle commands and environments.
    specs = []
    for i, v in enumerate(vehicles):
        env = _build_env(v, world=world, standalone=(i > 0))
        specs.append(LaunchSpec(
            name=v.name,
            instance=i,
            command=_build_command(px4_dir, MODEL_BUILD[v.model], i),
            cwd=px4_dir,
            env=_build_process_env(env),
        ))

    # Summary
    print(f"PX4 dir : {px4_dir}")
    print(f"world   : {world}")
    print(f"vehicles: {len(vehicles)}")
    for spec in specs:
        print(f"  - {spec.name:<10} i={spec.instance}  "
              f"{shlex.join(spec.command)}")
    print()

    _launch_processes(specs, session, state_path, args.detach)


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


def _build_process_env(overrides: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PX4_GZ_STANDALONE", "PX4_GZ_WORLD"):
        env.pop(key, None)
    env.update(overrides)
    return env


def _build_command(px4_dir: Path, build: str, instance: int) -> list[str]:
    px4_bin = px4_dir / "build" / build / "bin" / "px4"
    return [str(px4_bin), "-i", str(instance)]


def _launch_processes(specs, session, state_path, detach):
    processes = []
    state = {
        "session": session,
        "started_at": time.time(),
        "processes": [],
    }

    try:
        for index, spec in enumerate(specs):
            stdin_read, stdin_write = os.pipe()
            try:
                if detach:
                    process = subprocess.Popen(
                        spec.command,
                        cwd=spec.cwd,
                        env=spec.env,
                        stdin=stdin_read,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        pass_fds=(stdin_write,),
                    )
                    output_thread = None
                else:
                    process = subprocess.Popen(
                        spec.command,
                        cwd=spec.cwd,
                        env=spec.env,
                        stdin=stdin_read,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        start_new_session=True,
                        pass_fds=(stdin_write,),
                    )
                    output_thread = threading.Thread(
                        target=_pump_output,
                        args=(process, spec.name),
                        daemon=True,
                    )
                    output_thread.start()
            finally:
                os.close(stdin_read)
                os.close(stdin_write)

            processes.append((spec, process, output_thread))
            state["processes"].append({
                "name": spec.name,
                "instance": spec.instance,
                "pid": process.pid,
                "pgid": process.pid,
                "executable": spec.command[0],
            })
            _write_state(state_path, state)

            role = "gz-server host" if index == 0 else "standalone, waiting for Gazebo"
            print(f"  [{spec.name}] PX4 instance {spec.instance} ({role})")

        print()
        print(f"scenario '{session}' is running")
        print(f"  status : {Path(sys.argv[0]).name} --status")
        print(f"  stop   : {Path(sys.argv[0]).name} --stop")

        if detach:
            print("  mode   : detached")
            return

        print("  mode   : foreground (Ctrl-C stops all vehicles)")
        _monitor_processes(processes)
    except BaseException:
        _stop_processes(processes)
        state_path.unlink(missing_ok=True)
        raise
    finally:
        if not detach:
            _stop_processes(processes)
            state_path.unlink(missing_ok=True)


def _pump_output(process, name):
    for line in process.stdout:
        print(f"[{name}] {line}", end="", flush=True)


def _monitor_processes(processes):
    try:
        while True:
            exited = [(spec, process.returncode)
                      for spec, process, _ in processes
                      if process.poll() is not None]
            if exited:
                for spec, returncode in exited:
                    print(f"\n[{spec.name}] exited with code {returncode}")
                return
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nstopping PX4 SITL scenario...")


def _stop_processes(processes, timeout: float = 5.0):
    running = [process for _, process, _ in processes if process.poll() is None]
    for process in running:
        _signal_process_group(process.pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout
    while running and time.monotonic() < deadline:
        running = [process for process in running if process.poll() is None]
        time.sleep(0.1)

    for process in running:
        _signal_process_group(process.pid, signal.SIGKILL)
    for process in running:
        process.wait()

    for _, _, output_thread in processes:
        if output_thread:
            output_thread.join(timeout=1.0)


def _signal_process_group(pgid: int, sig: signal.Signals):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _validate_session_name(session: str):
    if not SESSION_NAME_PATTERN.fullmatch(session):
        raise SystemExit(
            f"Invalid session name {session!r}; use only letters, numbers, '.', '_' or '-'."
        )


def _validate_vehicles(vehicles):
    names = set()
    for vehicle in vehicles:
        if not SESSION_NAME_PATTERN.fullmatch(vehicle.name):
            raise SystemExit(
                f"Invalid vehicle name {vehicle.name!r}; use only letters, "
                "numbers, '.', '_' or '-'."
            )
        if vehicle.name in names:
            raise SystemExit(f"Vehicle name {vehicle.name!r} is duplicated.")
        names.add(vehicle.name)


def _state_directory() -> Path:
    return Path.home() / ".cache" / "px4-sitl"


def _state_path(session: str) -> Path:
    return _state_directory() / f"{session}.json"


def _write_state(state_path: Path, state: dict):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(state_path)


def _read_state(state_path: Path):
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        print(f"warning: ignoring invalid state file {state_path}", file=sys.stderr)
        return None


def _state_has_running_process(state: dict) -> bool:
    return any(_state_process_is_running(item) for item in state.get("processes", []))


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def _state_process_is_running(item: dict) -> bool:
    return _pid_is_alive(item["pid"]) and _pid_matches_executable(item)


def _pid_matches_executable(item: dict) -> bool:
    try:
        actual = os.path.realpath(f"/proc/{int(item['pid'])}/exe")
        expected = os.path.realpath(item["executable"])
    except (KeyError, OSError, ValueError):
        return False
    return actual == expected


def _show_status(session: str, state_path: Path):
    state = _read_state(state_path)
    if not state:
        print(f"scenario '{session}' is not running")
        return

    print(f"scenario '{session}'")
    for item in state.get("processes", []):
        if _state_process_is_running(item):
            status = "running"
        elif _pid_is_alive(item["pid"]):
            status = "stale-pid"
        else:
            status = "stopped"
        print(f"  {item['name']:<10} {status:<8} pid={item['pid']}")

    if not _state_has_running_process(state):
        state_path.unlink(missing_ok=True)


def _stop_saved_session(session: str, state_path: Path):
    state = _read_state(state_path)
    if not state:
        print(f"scenario '{session}' is not running")
        return

    for item in state.get("processes", []):
        pid = int(item["pid"])
        if _state_process_is_running(item):
            print(f"stopping {item['name']} (pid {pid})")
            _signal_process_group(int(item["pgid"]), signal.SIGTERM)
        elif _pid_is_alive(pid):
            print(f"skipping {item['name']}: saved PID now belongs to another executable")

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and _state_has_running_process(state):
        time.sleep(0.1)

    for item in state.get("processes", []):
        pid = int(item["pid"])
        if _state_process_is_running(item):
            _signal_process_group(int(item["pgid"]), signal.SIGKILL)

    state_path.unlink(missing_ok=True)
    print(f"scenario '{session}' stopped")


