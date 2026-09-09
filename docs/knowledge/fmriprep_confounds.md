# fMRIPrep confound metrics

Source: https://fmriprep.org/en/stable/outputs.html

## Framewise displacement (FD)

`framewise_displacement` is a quantification of estimated bulk head motion between
consecutive volumes, calculated with the formula proposed by Power et al. (2012):
the sum of the absolute values of the six differentiated realignment parameters,
with rotations converted to millimeters on a 50 mm sphere. It is a per-frame
metric: each value describes displacement relative to the previous volume, so at
faster TRs each frame accumulates proportionally less displacement.

Reference: Power JD, Barnes KA, Snyder AZ, Schlaggar BL, Petersen SE (2012).
"Spurious but systematic correlations in functional connectivity MRI networks
arise from subject motion." NeuroImage. doi:10.1016/j.neuroimage.2011.10.018

## DVARS and standardized DVARS

`dvars` is the derivative of RMS variance over voxels — how much the whole-brain
image intensity changes from one volume to the next. `std_dvars` is the
standardized variant. fMRIPrep generates motion spike regressors when
standardized DVARS exceeds 1.5 (its default threshold). Real head motion corrupts
image intensity at the moment it occurs, so DVARS spikes at motion events
regardless of the sampling rate — unlike per-frame FD, it is not diluted by fast
TRs. Absolute std_dvars levels differ systematically between scanner vendors and
reconstruction pipelines, so a fixed absolute threshold can flag one vendor's
scans far more often than another's at matched motion; normalizing against each
scan's own median removes this shift.

## The confounds file

Confounds are stored per subject, session, and run in TSV files
(`*_desc-confounds_timeseries.tsv`), one column per confound variable, with JSON
sidecar metadata. The first row of FD and DVARS is `n/a` because both are
frame-to-frame derivatives. fMRIPrep's documentation warns against including all
columns in a design matrix; QC uses only `framewise_displacement` and
`std_dvars`.

## The carpet plot

The carpet plot (Power 2016) displays voxelwise BOLD time series as rows,
separated into regions: cortical gray matter, deep gray matter, white matter and
cerebrospinal fluid, cerebellum, and the brain-edge "crown". Vertical dark or
bright bands that span all tissue classes indicate global artifacts — typically
motion; bands confined to edge/crown rows indicate motion at the brain boundary.

Reference: Power JD (2016). "A simple but useful way to assess fMRI scan
qualities." NeuroImage. doi:10.1016/j.neuroimage.2016.08.009
