"""Apply criteria.yaml to per-scan metrics -> status + VERIFY flags.

LLM review NEVER changes a status; it can only add VERIFY flags and notes.
"""


def classify(scan: dict, m: dict, criteria: dict) -> dict:
    excl, caut, vf = criteria["exclusion"], criteria["caution"], criteria["verify_flags"]
    flags, reasons = [], []

    if scan["missing"] and excl.get("missing_outputs", True):
        status = "EXCLUDE"
        reasons.append(f"missing required outputs: {', '.join(scan['missing'])}")
    elif m["mean_fd"] is not None and m["mean_fd"] > excl["mean_fd_mm"]:
        status = "EXCLUDE"
        reasons.append(f"session mean FD {m['mean_fd']:.3f} mm > {excl['mean_fd_mm']}")
    elif m["outlier_percent"] is not None and m["outlier_percent"] > caut["motion_outlier_percent"]:
        status = "CAUTION"
        reasons.append(f"outliers {m['outlier_percent']:.1f}% > {caut['motion_outlier_percent']}%")
    elif (caut.get("min_retained_minutes")
          and m["retained_minutes"] < caut["min_retained_minutes"]):
        status = "CAUTION"
        reasons.append(f"retained {m['retained_minutes']:.1f} min "
                       f"< {caut['min_retained_minutes']} min floor")
    else:
        status = "INCLUDE"

    lo, hi = vf["borderline_mean_fd_band"]
    if m["mean_fd"] is not None and lo < m["mean_fd"] <= hi:
        flags.append(f"borderline mean FD {m['mean_fd']:.3f} vs {criteria['exclusion']['mean_fd_mm']} mm")
    lo, hi = vf["borderline_outlier_band"]
    if m["outlier_percent"] is not None and lo < m["outlier_percent"] <= hi:
        flags.append(f"borderline outlier% {m['outlier_percent']:.1f} vs threshold")
    if m["is_fast_tr"]:
        flags.append("fast-TR (multiband): FD spike arm weak; DVARS is the active guard")

    return {"status": status, "reasons": reasons, "verify_flags": flags}
