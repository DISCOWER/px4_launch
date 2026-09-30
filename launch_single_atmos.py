#!/usr/bin/env python3
"""Scenario: single atmos free-flyer in the default world."""

from px4_sitl_launcher import launch, Vehicle

WORLD = "kthspacelab" #"default"

VEHICLES = [
    Vehicle(name="pop", model="gz_atmos", pose=(1, 0, 0, 0, 0, 0)),
]

SESSION = "atmos"   # state and log session name

if __name__ == "__main__":
    launch(vehicles=VEHICLES, world=WORLD, session=SESSION)
