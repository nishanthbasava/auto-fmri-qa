# Reviewing registration figures

Source: fMRIPrep visual report guidance (https://fmriprep.org/en/stable/outputs.html)
and this project's review checklist (agents/prompts/figure_review.md).

## BOLD → T1w coregistration

The figure overlays the EPI reference on the subject's anatomical image. Check
that the brain outline, ventricle edges, and major sulci coincide between the
two layers as the flicker alternates. Expected imperfections: EPI signal dropout
near orbitofrontal cortex and temporal poles (susceptibility artifact), mild
geometric distortion along the phase-encode axis. Failures worth flagging:
whole-brain shifts or rotations, missing slices or truncated field of view
(coverage failure), and severely degraded EPI contrast that makes interior
alignment unjudgeable.

## T1w → MNI normalization

The figure compares the warped subject anatomy against the MNI152NLin2009cAsym
template. Check gray/white boundaries, ventricle shape and size, and the cortical
outline. Atrophy is normal in an aging and Alzheimer's cohort: enlarged
ventricles and widened sulci that are well-aligned to the template are not
registration failures. Flag gross mismatches: brain edges falling outside the
template outline, distorted subcortical structures, or a warp that collapsed or
smeared a lobe.

## Site-specific EPI appearance

Some sites and scanner models produce EPI with a characteristically saturated,
low-contrast appearance where tissue boundaries are hard to see. When every scan
from a site shares this signature, it is an acquisition characteristic rather
than a per-scan failure — record it, but judge alignment from the visible
landmarks (ventricles, brain outline) rather than excluding the site wholesale.

## Ghosting

Nyquist ghosting appears as a faint, shifted copy of the brain along the
phase-encode direction. Mild ghosting outside the brain is common; ghosting that
overlaps brain tissue contaminates the signal and warrants a flag.
