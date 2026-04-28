# PX4 SITL Multi-Vehicle Launcher

Launch one or more PX4 SITL vehicles in Gazebo from a single script.

## Setup

```bash
sudo apt install tmux
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

Each vehicle runs in its own tmux window; the script prints the attach command when it's ready.

## Configuring

Each scenario script has a small CONFIG block at the top. Edit it to
change the world, the tmux session name, or the vehicle list (names,
models, poses):

```python
WORLD   = "kthspacelab"
SESSION = "atmos3_kth"

VEHICLES = [
    Vehicle(name="snap",    model="gz_atmos", pose=(1, 0, 0.2)),
    Vehicle(name="crackle", model="gz_atmos", pose=(2, 0, 0.2)),
]
```

To add a new model, edit `px4_sitl_launcher.py` and add it to both
`MODEL_AUTOSTART` and `MODEL_BUILD`.

## Killing

```bash
./launch_multi_atmos.py --kill
```

## Notes

**ROS 2 integration.** In a separate terminal, run the XRCE-DDS agent:

```bash
micro-xrce-dds-agent udp4 -p 8888
```

Each vehicle's topics then appear under its name, e.g. `/snap/fmu/out/...`.

**Offboard control of multiple vehicles.** QGroundControl's virtual joystick
binds to one vehicle at a time, which trips the "manual control lost"
prearm check on the others. If you only need offboard mode, disable the
RC requirement by adding

```
param set-default COM_RC_IN_MODE 4
```

to the relevant airframe init files (`gz_atmos`, `gz_atmos_dual`,
`gz_uuv_bluerov2_heavy`, ...), or set the same parameter from the QGC
parameter editor.

## Troubleshooting

**`PX4 binary not found at .../build/<target>/bin/px4`** — build the target it asks for:

```bash
cd $PX4_Autopilot_Dir
make px4_sitl_spacecraft   # gz_atmos / gz_atmos_dual
make px4_sitl_uuv          # gz_uuv_bluerov2_heavy
```

**`gz sim` won't die after `--kill`:**

```bash
pkill -9 -f 'gz sim'
pkill -9 -f 'bin/px4'
tmux kill-server          # nuclear option
```
