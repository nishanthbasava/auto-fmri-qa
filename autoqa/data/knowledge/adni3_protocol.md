# ADNI-3 resting-state fMRI acquisition protocols

Source: ADNI-3 MRI protocol documentation, https://adni.loni.usc.edu/methods/mri-tool/mri-analysis/

## Basic protocol

The ADNI-3 Basic resting-state fMRI protocol acquires single-band EPI with
TR = 3.0 s. Runs in this cohort contain approximately 140, 197, or 200 volumes
(roughly 7–10 minutes). This protocol is designed for backward compatibility
with ADNI-2 acquisitions.

## Advanced protocol (multiband)

The ADNI-3 Advanced protocol uses simultaneous multi-slice (multiband) EPI with
TR ≈ 0.607 s and a multiband/SMS acceleration factor of 8, acquiring roughly
976 volumes in about 10 minutes. ADNI documentation notes the Advanced protocol
is not compatible with ADNI-2 data. Sites with capable scanners (primarily
Siemens Prisma-class) run Advanced; other sites run Basic, so a mixed cohort
contains both TR regimes.

## Consequence for motion QC

Because FD is a per-frame metric, a fixed per-volume FD spike threshold tuned for
TR = 3 s (e.g. 0.5 mm) is effectively unreachable at TR = 0.6 s: the same
continuous motion is divided across five times as many frames. Scaling the
threshold by TR (0.5 mm × TR/3 ≈ 0.10 mm) instead lands inside the respiratory
pseudomotion band and flags breathing rather than behavior. Multiband runs
therefore rely on mean-FD exclusion, DVARS-based spike detection, and visual
review; a TR-scaled FD threshold is only meaningful after respiratory filtering
of the motion parameters.

## Session naming

ADNI session labels in this cohort follow visit codes (e.g. ses-v28, ses-v101).
Some subjects have two resting-state sessions; motion metrics must always be
computed per scan, never pooled across a subject's sessions.
