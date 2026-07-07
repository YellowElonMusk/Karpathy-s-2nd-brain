---
id: ticket_0001
type: ticket
title: "Ticket 0001 — Recurring E203 halts at dusty warehouse site"
aliases: []
tags: [lidar, reference-case]
status: active
postgres_id: 1042
customer: []
robot: [scrubber50]
error_codes: [error203]
resolved_by: [lidar_cleaning]
sources:
  - id: S1
    doc: ticket:1042
    locator: ""
created: 2026-07-07
updated: 2026-07-07
---

# Ticket 0001 — Recurring E203 halts at dusty warehouse site

> **Worked example** — fabricated content demonstrating when a ticket earns a page:
> this one is the reference case that confirmed the cleaning resolution for [[error203]].

A [[scrubber50]] halted with `E203` two to three times per shift at a cement-adjacent warehouse. Distributor suspected a faulty LiDAR unit; root cause was dust film, resolved without parts [S1].

## Situation

Unit on firmware v2.7, six weeks after deployment, escalating halt frequency [S1].

## Diagnosis

Replacement LiDAR was quoted first (dead end — telemetry showed gradual `lidar_frame_gap` growth over days, pointing to progressive occlusion, not unit failure). Window inspection found a uniform dust film [S1].

## Resolution

[[lidar_cleaning]] eliminated the halts; site moved to twice-weekly cleaning cadence and scheduled a [[v2_8|v2.8]] upgrade for margin [S1].

## Lessons

- Added the dust-film root cause and telemetry signature to [[error203#Root causes]].
- Gradual frame-gap growth in telemetry distinguishes occlusion from LiDAR hardware failure — cheaper diagnosis than part swaps.
