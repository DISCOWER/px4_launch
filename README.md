# PX4 SITL Multi-Vehicle Launcher

Launch one or more PX4 SITL vehicles in Gazebo from a single scenario script.

## Setup

```bash
chmod +x launch_*.py
```

Add this to your `~/.bashrc` (then open a new shell):

```bash
export PX4_Autopilot_Dir=~/PX4-Autopilot
```

## Running

```bash
./launch_multi_atmos.py
```

The launcher runs in the foreground and prefixes each vehicle's output with its
name. Press `Ctrl-C` to stop every vehicle and its Gazebo process group.
Scenario state files are stored under `~/.cache/px4-sitl/`.

## Configuring

Each scenario script has a small CONFIG block at the top. Edit it to
change the world, the state session name, or the vehicle list (names,
models, poses):

```python
WORLD   = "kthspacelab"
SESSION = "atmos"

VEHICLES = [
    Vehicle(name="snap",    model="gz_atmos", pose=(1, 0, 0.2)),
    Vehicle(name="crackle", model="gz_atmos", pose=(2, 0, 0.2)),
]
```

`Vehicle.name` is used for the DDS namespace, live output prefix, and status output.
Gazebo assigns its own model names such as `atmos_0` and `atmos_1`; this is
intentional because setting `PX4_GZ_MODEL_NAME` makes PX4 attach to an existing
Gazebo model instead of spawning one.

To add a new model, edit `px4_sitl_launcher.py` and add it to both
`MODEL_AUTOSTART` and `MODEL_BUILD`.

## Managing a Scenario

```bash
./launch_multi_atmos.py --detach   # launch and return to the shell
./launch_multi_atmos.py --status   # show vehicle PIDs and states
./launch_multi_atmos.py --stop    # stop only this scenario
```

Detached scenarios are still owned by their individual process groups, so
stopping one scenario does not kill unrelated PX4 or Gazebo processes.

## Notes

**ROS 2 integration.** In a separate terminal, run the XRCE-DDS agent:

```bash
micro-xrce-dds-agent udp4 -p 8888
```

Each vehicle's topics then appear under its name, e.g. `/snap/fmu/out/...`.

## Troubleshooting

**`PX4 binary not found at .../build/<target>/bin/px4`** — build the target it asks for:

```bash
cd $PX4_Autopilot_Dir
make px4_sitl_spacecraft   # gz_atmos / gz_atmos_dual
make px4_sitl_uuv          # gz_uuv_bluerov2_heavy
```
