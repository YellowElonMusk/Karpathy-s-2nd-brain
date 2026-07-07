---
id: scrubber50
type: robot
title: "Scrubber 50 — Autonomous Floor Scrubber"
aliases: ["S50", "Scrubber50"]
tags: [scrubber, autonomous]
status: active
components: []
firmware_history: [v2_8]
known_errors: [error203]
procedures: [lidar_cleaning]
sources:
  - id: S1
    doc: sources/manuals/scrubber50-service-manual-2024.pdf
    locator: "ch. 1-2"
created: 2026-07-07
updated: 2026-07-07
---

# Scrubber 50 — Autonomous Floor Scrubber

> **Worked example** — fabricated content demonstrating the conventions in
> [docs/02-knowledge-spec.md](../../docs/02-knowledge-spec.md). Replace with real data during Phase 0.

Mid-size autonomous floor scrubber for warehouses and retail, navigating via roof-mounted LiDAR with wheel-odometry fusion [S1].

## Specifications

| Spec | Value | Source |
|---|---|---|
| Cleaning width | 50 cm | [S1] |
| Runtime | 4.5 h | [S1] |
| Navigation | 2D LiDAR + odometry | [S1] |

## Components

No component pages yet — battery pack and LiDAR unit pages arrive with the first real products ingest.

## Firmware

Recommended: [[v2_8|v2.8]] — fixes the most common field error. Units below v2.6 must step through v2.6 first [S1].

## Known issues

- Navigation LiDAR timeout under dust load → [[error203]], most frequent on firmware v2.6–v2.7.

## Maintenance

- Weekly: [[lidar_cleaning|LiDAR window cleaning]] in dusty sites [S1].
