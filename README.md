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
tmux kill-server
```
