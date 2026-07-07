---
id: error203
type: error_code
title: "Error 203 — Navigation LiDAR Timeout"
aliases: ["E203", "nav lidar timeout"]
tags: [navigation, lidar]
status: active
affects_robots: [scrubber50]
caused_by: []
introduced_in: []
fixed_in: [v2_8]
resolved_by: [lidar_cleaning]
sources:
  - id: S1
    doc: sources/manuals/scrubber50-service-manual-2024.pdf
    locator: "pp. 34-36"
  - id: S2
    doc: ticket:1042
    locator: ""
created: 2026-07-07
updated: 2026-07-07
---

# Error 203 — Navigation LiDAR Timeout

> **Worked example** — fabricated content demonstrating the conventions.

The navigation stack stopped receiving LiDAR frames for more than the timeout threshold; the robot halts in place and requires operator attention. Not hardware-fatal, but a top-3 field complaint on [[scrubber50]] [S1].

## Symptoms

- Robot stops mid-route, beacon flashing amber, display shows `E203` [S1].
- Telemetry: `lidar_frame_gap > 2500 ms` immediately before the halt [S1].

## Root causes

1. **Dust/film on the LiDAR window** — most common; scan returns degrade until frames drop [S1] [S2].
2. **Timeout threshold too aggressive in firmware v2.6–v2.7** — transient gaps that v2.8 tolerates would halt the robot [S1].

## Diagnosis

1. Check firmware version: below [[v2_8|v2.8]] → cause 2 is likely a contributor.
2. Inspect the LiDAR window: visible film or dust → cause 1; run [[lidar_cleaning]].
3. Clean window + error recurs within a shift on v2.8 → escalate (possible LiDAR unit fault).

## Resolution

- Cause 1: perform [[lidar_cleaning]]; verified fix in ticket:1042 [S2].
- Cause 2: upgrade to [[v2_8|v2.8]], which widens the timeout and adds frame-gap smoothing [S1].

## History

- First documented in the 2024 service manual [S1]. Cleaning resolution confirmed in the field via ticket:1042 (see [[ticket_0001]]) [S2].
