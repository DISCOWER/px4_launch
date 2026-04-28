#!/usr/bin/env python3
"""Scenario: multiple bluerov2_heavy UUVs."""

from px4_sitl_launcher import launch, Vehicle

WORLD = "default"

VEHICLES = [
    Vehicle(name="rov0", model="gz_uuv_bluerov2_heavy", pose=(0, 0, 1)),
    Vehicle(name="rov1", model="gz_uuv_bluerov2_heavy", pose=(1, 0, 1)),
]

SESSION = "bluerov"   # tmux session name

if __name__ == "__main__":
    launch(vehicles=VEHICLES, world=WORLD, session=SESSION)
