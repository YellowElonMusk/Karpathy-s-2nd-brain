---
id: lidar_cleaning
type: procedure
title: "LiDAR Window Cleaning"
aliases: ["lidar wipe"]
tags: [maintenance, lidar]
status: active
applies_to: [scrubber50]
resolves: [error203]
requires: []
sources:
  - id: S1
    doc: sources/manuals/scrubber50-service-manual-2024.pdf
    locator: "p. 41"
created: 2026-07-07
updated: 2026-07-07
---

# LiDAR Window Cleaning

> **Worked example** — fabricated content demonstrating the conventions.

Removes dust and film from the LiDAR window; first-line fix for [[error203]] and weekly preventive maintenance in dusty sites [S1].

## Prerequisites

- Robot powered off and parked [S1].
- Lint-free microfiber cloth, isopropyl alcohol (≥90%). No solvents or paper towels — the window coating scratches [S1].

## Steps

1. Power off the robot and open the sensor mast cover [S1].
2. Wipe the LiDAR window with the dry microfiber cloth in one direction.
3. For film residue, dampen the cloth with isopropyl alcohol and repeat.
4. Let dry 2 minutes, close the cover, power on.

## Verification

Run a short mapped route; confirm no `E203` and `lidar_frame_gap` stays under 500 ms in telemetry [S1].

## Troubleshooting

Error persists after cleaning on firmware ≥ [[v2_8|v2.8]] → suspect the LiDAR unit itself; escalate per [[error203#Diagnosis]].
