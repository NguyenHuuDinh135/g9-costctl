"""clean — (stretch) bulk terminate resources matching a tag.

WARNING — DESIGN-FOR-SAFETY
---------------------------
This is the most dangerous command in the CLI. Get the contract right:

  1. DEFAULT IS DRY-RUN. Without --apply the command MUST NOT touch resources.
     It only lists what WOULD be deleted.
  2. Even with --apply, you should consider printing a summary count first
     ("about to terminate N EC2 + M volumes — proceed?"), though for this
     starter a hard `--apply` flag is enough.
  3. Never use this with a tag you don't fully own. Reflection prompt in
     README covers the blast-radius scenario.

WHAT YOU MUST BUILD
-------------------
1. `_find_targets(tag_key, tag_val)` — return a dict like:
     {"ec2": [<instance ids in non-terminal state>],
      "volume": [<volume ids in 'available' state only>]}
   Skip terminated/shutting-down instances (already gone).
   Skip in-use volumes (can't delete while attached — would error anyway).

2. `run(args)` — call _find_targets, print the plan, then either:
     - bail with "(dry-run — pass --apply to ...)"  (default)
     - or actually terminate (when --apply)

HELPERS YOU CAN USE
-------------------
From commands._common:
  parse_kv(s) -> (k, v)

AWS APIS YOU'LL NEED
--------------------
- ec2.describe_instances() + describe_volumes() — same as list_cmd
- ec2.terminate_instances(InstanceIds=[...])
- ec2.delete_volume(VolumeId=...)  (per volume, no bulk API)

VERIFY
------
    pytest tests/test_clean.py -v
"""
import boto3

from commands._common import parse_kv


def _find_targets(tag_key, tag_val):
    """Return {"ec2": [...], "volume": [...]} matching tag in non-terminal state."""
    ec2 = boto3.client("ec2")
    targets = {"ec2": [], "volume": []}

    # 1. EC2 instances
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                state = inst["State"]["Name"]
                if state in ("shutting-down", "terminated"):
                    continue
                tags_dict = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                if tags_dict.get(tag_key) == tag_val:
                    targets["ec2"].append(inst["InstanceId"])

    # 2. Volumes
    vol_paginator = ec2.get_paginator("describe_volumes")
    for page in vol_paginator.paginate():
        for vol in page.get("Volumes", []):
            state = vol["State"]
            if state != "available":
                continue
            tags_dict = {t["Key"]: t["Value"] for t in vol.get("Tags", [])}
            if tags_dict.get(tag_key) == tag_val:
                targets["volume"].append(vol["VolumeId"])

    return targets


def run(args):
    """Entry point."""
    tag_key, tag_val = parse_kv(args.tag)
    targets = _find_targets(tag_key, tag_val)

    num_ec2 = len(targets["ec2"])
    num_vol = len(targets["volume"])

    if num_ec2 == 0 and num_vol == 0:
        print("Nothing to clean.")
        return

    if not args.apply:
        print(f"(dry-run) Would clean {num_ec2} EC2 instances and {num_vol} volumes matching tag {tag_key}={tag_val}:")
        if num_ec2 > 0:
            print(f"  EC2 instances: {', '.join(targets['ec2'])}")
        if num_vol > 0:
            print(f"  EBS volumes: {', '.join(targets['volume'])}")
        print("  Use --apply to perform the cleanup.")
        return

    ec2 = boto3.client("ec2")
    if num_ec2 > 0:
        ec2.terminate_instances(InstanceIds=targets["ec2"])
        for iid in targets["ec2"]:
            print(f"Terminated EC2 {iid}")

    for vid in targets["volume"]:
        ec2.delete_volume(VolumeId=vid)
        print(f"Deleted EBS volume {vid}")
