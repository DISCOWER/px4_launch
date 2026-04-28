#!/usr/bin/env python3
"""Scenario: single atmos free-flyer in the default world."""

from px4_sitl_launcher import launch, Vehicle

WORLD = "default"

VEHICLES = [
    Vehicle(name="snap", model="gz_atmos", pose=(1, 0, 0.2)),
]

SESSION = "atmos1"   # tmux session name

if __name__ == "__main__":
    launch(vehicles=VEHICLES, world=WORLD, session=SESSION)
