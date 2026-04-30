#!/usr/bin/env python3
"""Scenario: multiple atmos free-flyers."""

from px4_sitl_launcher import launch, Vehicle

WORLD = "kthspacelab"

VEHICLES = [
    Vehicle(name="snap",    model="gz_atmos", pose=(1, 0, 0.2, 0, 0, 0)),
    Vehicle(name="crackle", model="gz_atmos", pose=(2, 0, 0.2, 0, 0, 0)),
    Vehicle(name="pop",     model="gz_atmos", pose=(3, 0, 0.2, 0, 0, 0)),
]

SESSION = "atmos"   # tmux session name

if __name__ == "__main__":
    launch(vehicles=VEHICLES, world=WORLD, session=SESSION)
