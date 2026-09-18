# Rater guide — visual QC labeling

You have a CSV sheet (`sheet_<yourname>.csv`) with one row per scan. Your job:
look at up to three figures per scan and fill in four columns. Plan for 30–45
seconds per scan; partial sheets are fine (empty rows are skipped on import),
so label in as many sittings as you like.

**One rule above all: do not discuss scans or compare answers with the other
rater until both sheets are turned in.** Agreement between independent raters
(κ) is the quality measure for this whole dataset; talking beforehand
invalidates it.

## What to look at

Each row's `carpet`, `coreg`, `t1norm` columns are image paths (open them from
the repo root). The `status` / `mean_fd` / `outlier_percent` columns are
context only — **rate what you see in the figures, not the numbers.** A scan
with ugly motion numbers can be visually fine, and vice versa.

| figure | what it shows | look for |
|---|---|---|
| carpet | signal traces + voxel-by-time plot | sharp dark/bright bands, scrambled segments, sharp-edged intensity blocks, long disrupted stretches |
| coreg | BOLD EPI with anatomical contours | contours not tracking the EPI, global offset/rotation, truncated/partial FOV, saturated or contrast-less EPI, heavy ghosting |
| t1norm | subject T1w warped to MNI | anatomy not matching labelled coordinates, bent midline, missing cortical rim (skull-strip), gross warp distortion |

## The four columns

**rating** (required — this is the label):

| value | meaning |
|---|---|
| `clean` | nothing a reviewer would mention |
| `minor` | small isolated oddity, clearly usable |
| `concern` | visible corruption a reviewer should weigh (may still be usable) |
| `bad` | unusable: truncated FOV, failed registration/skull-strip, scrambled carpet |

**panel** — where you saw the worst problem: `carpet`, `coreg`, `t1norm`,
`multiple`, or `none` (leave blank if clean).

**failure_type** — what is wrong: `truncated_fov`, `saturated_epi`,
`misregistration`, `skull_strip`, `carpet_block`, `ghosting`, `motion`,
`other`, or `none` (blank if clean).

**note** — one short sentence, optional. Timestamps help ("dark band ~04:30").

Values must match the spellings above exactly (lowercase); the importer
rejects anything else and names the row.

## Normal for this cohort — do NOT flag

Elderly ADNI cohort, mixed single-band (TR 3 s) and multiband (TR 0.6 s):

- orbitofrontal / temporal dropout and local distortion (susceptibility)
- enlarged ventricles, widened sulci (atrophy)
- fine continuous FD oscillation on multiband scans (respiratory pseudomotion)
- grainy EPI, mild contour wiggle

## When done

Save the CSV (keep it as CSV, not xlsx) back into `training/data/labels/` and
say so. Never commit or email the sheet — it carries ADNI identifiers (DUA);
it stays on lab machines.
