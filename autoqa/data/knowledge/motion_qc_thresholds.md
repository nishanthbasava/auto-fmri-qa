# Motion QC thresholds and their rationale

Source: Power et al. 2012 (doi:10.1016/j.neuroimage.2011.10.018), Power et al.
2019 (doi:10.1073/pnas.1720985115), Fair et al. 2020
(doi:10.1016/j.neuroimage.2019.116400), and this project's criteria.yaml.

## Session-level exclusion: mean FD

Mean FD summarizes sustained motion across the whole run and accumulates real
motion at any TR, making it protocol-fair across single-band and multiband
acquisitions. A session mean FD above 0.5 mm indicates pervasive motion that
denoising cannot fully repair; such scans are excluded. Typical cohort medians
for mean FD in older adults are 0.15–0.25 mm.

## Volume-level outliers: FD spikes and DVARS

A volume is an outlier when its FD exceeds the spike threshold (0.5 mm at
TR = 3 s) or its standardized DVARS exceeds the DVARS criterion. In relative
mode, the DVARS criterion is a multiple (1.5×) of the scan's own median
std_dvars, which removes scanner-vendor offsets in absolute DVARS units. Scans
whose outlier fraction exceeds ~20% earn CAUTION: enough volumes are corrupted
that scrubbing meaningfully shortens the usable data.

## Retained minutes

Percent-based criteria treat a 7-minute and a 10-minute run as equivalent, but
connectivity estimates stabilize with absolute clean time. A minimum
retained-minutes floor (clean volumes × TR) complements the percent criterion,
especially across mixed-duration protocols.

## Respiratory pseudomotion in fast-TR data

At sub-second TRs, chest motion during breathing modulates the magnetic field
and appears as a continuous ~0.05–0.15 mm oscillation in the realignment
parameters (~0.2–0.5 Hz) — pseudomotion, not head movement (Power 2019; Fair
2020). Band-stop (notch) filtering the six motion parameters at the respiratory
band before computing FD restores the meaning of small FD thresholds in
multiband data. Without that filter, a TR-scaled FD threshold mostly detects
breathing.

## Borderline values

Values within ±10% of a threshold (e.g. mean FD 0.45–0.55 mm, outlier fraction
18–22%) should be verified by a human: measurement noise and threshold choice
dominate the decision in that band.
