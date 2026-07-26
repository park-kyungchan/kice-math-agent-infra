# -*- coding: utf-8 -*-
"""
CLI entrypoint: run the full 8-axis scorecard against a throwaway DB copy
and print a human-readable summary.

MISSION CONSTRAINT: never point --db at the live storage/parsed_dataset.db.
    cp storage/parsed_dataset.db /tmp/eval.db
    python3 -m pipeline.axis_eval.run_eval --db /tmp/eval.db

Usage:
    python3 -m pipeline.axis_eval.run_eval --db /tmp/eval.db \
        --outcomes scratch/staging/I1/outcome_data.json
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.axis_eval.scorecard import build_scorecard  # noqa: E402


def _fmt_pct(x):
    return "n/a" if x is None else f"{x*100:.2f}%"


def print_summary(scorecard):
    print("=" * 100)
    print("AXIS EVAL SCORECARD")
    print("=" * 100)
    for axis_key in scorecard["axis_keys"]:
        row = scorecard["per_axis"][axis_key]
        m2 = row["m2_discriminative_power"]
        m4 = row["m4_informational_validity"]
        print(f"\n--- {axis_key} ---")
        print(f"  M1 reproducibility        : {row['m1_reproducibility']['status']}")
        print(f"  M2 discriminative power   : status={m2['status']} distinct={m2.get('distinct')} "
              f"largest_bucket_share={m2.get('largest_bucket_share')} "
              f"normalized_entropy={m2.get('normalized_entropy')}")
        if m4.get("status") == "INSUFFICIENT_DATA":
            print(f"  M4 informational validity : INSUFFICIENT_DATA -- {m4.get('reason')}")
        else:
            mc = m4["mc"]
            sa = m4["short_answer"]
            print(f"  M4 informational validity : MC recovery(all)={_fmt_pct(mc['recovery_rate_of_all_mc'])} "
                  f"(chance={_fmt_pct(mc['chance'])}, beats_chance={mc['beats_chance']}) "
                  f"| SA recovery(all)={_fmt_pct(sa['recovery_rate_of_all_sa'])} "
                  f"(chance={_fmt_pct(sa['chance_baseline']['chance'])}, beats_chance={sa['beats_chance']})")
        oc = row["outcome_correlation_weak_n17"]
        if oc["status"] == "OK_BUT_WEAK":
            print(f"  Outcome corr (n=17, WEAK) : pearson_r={oc['pearson_r']:.4f} n={oc['n']}")
        else:
            print(f"  Outcome corr (n=17, WEAK) : {oc['status']} -- {oc.get('reason')}")

    print("\n" + "=" * 100)
    print("M3 EXISTENCE-PROOF REDUNDANCY (sparse axes, n<5, NOT corpus-scale)")
    print("=" * 100)
    for axis_key, others in scorecard["m3_existence_proofs_for_sparse_axes"].items():
        for other_key, res in others.items():
            if res.get("status") == "OK":
                print(f"  MI({axis_key} ; {other_key}) n={res['n']} normalized_mi={res['normalized_mi']:.4f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, help='Path to a THROWAWAY copy of parsed_dataset.db')
    parser.add_argument('--outcomes', default=os.path.join(BASE_DIR, 'scratch', 'staging', 'I1', 'outcome_data.json'))
    parser.add_argument('--json-out', default=None, help='Optional path to dump the full scorecard as JSON')
    args = parser.parse_args()

    if os.path.abspath(args.db).endswith(os.path.join('storage', 'parsed_dataset.db')):
        raise SystemExit("Refusing to run against the live storage/parsed_dataset.db -- copy it first.")

    scorecard = build_scorecard(args.db, i1_outcome_json_path=args.outcomes)
    print_summary(scorecard)

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(scorecard, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nFull scorecard JSON written to {args.json_out}")


if __name__ == '__main__':
    main()
