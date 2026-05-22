"""list — list AWS resources by type, filter by tag / missing-tag.

WHAT YOU MUST BUILD
-------------------
Support 4 resource types: ec2, rds, s3, volume.
Each takes:
- `want` — list of (key, value) tag pairs the resource MUST have
- `missing` — list of tag keys the resource MUST NOT have

Print a formatted table to stdout. Test cases are in tests/test_list.py.

HELPERS YOU CAN USE
-------------------
From commands._common:
  parse_kv(s) -> (k, v)            # "Owner=alice" -> ("Owner", "alice")
  tags_to_dict(items) -> dict       # boto3 [{"Key","Value"}] -> {k: v}
  tags_match(tags, want, missing) -> bool

AWS APIS YOU'LL NEED
--------------------
- EC2: ec2.describe_instances() with get_paginator
- RDS: rds.describe_db_instances(), then list_tags_for_resource(ResourceName=arn)
- S3:  s3.list_buckets(), then get_bucket_tagging(Bucket=name)
       (catch ClientError when bucket has no tagging config — treat as {})
- EBS: ec2.describe_volumes() with get_paginator

EXPECTED OUTPUT FORMAT (when run from CLI)
------------------------------------------
    EC2 Environment=dev — 1 found:
    ------------------------------------------------------------------------------
      i-0abc123def456789a       t3.micro       running       Environment=dev

VERIFY
------
    pytest tests/test_list.py -v
"""
import boto3
from botocore.exceptions import ClientError

from commands._common import parse_kv, tags_to_dict, tags_match


def _list_ec2(want, missing):
    """List EC2 instances matching tag filters.

    Args:
        want: list of (key, value) tag pairs that must all match
        missing: list of tag keys that must NOT be present

    Returns:
        list of (instance_id, instance_type, state, tags_dict) tuples
    """
    ec2 = boto3.client("ec2")
    paginator = ec2.get_paginator("describe_instances")
    rows = []
    for page in paginator.paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                state = inst["State"]["Name"]
                tags = tags_to_dict(inst.get("Tags", []))
                if tags_match(tags, want, missing):
                    rows.append((inst["InstanceId"], inst["InstanceType"], state, tags))
    return rows


def _list_rds(want, missing):
    """Same shape as _list_ec2 but for RDS DB instances.

    Note: RDS tags require a separate API call per DB:
        rds.list_tags_for_resource(ResourceName=db['DBInstanceArn'])

    Returns:
        list of (db_id, db_class, db_status, tags_dict) tuples
    """
    rds = boto3.client("rds")
    paginator = rds.get_paginator("describe_db_instances")
    rows = []
    for page in paginator.paginate():
        for db in page.get("DBInstances", []):
            db_id = db["DBInstanceIdentifier"]
            db_class = db["DBInstanceClass"]
            db_status = db["DBInstanceStatus"]
            arn = db["DBInstanceArn"]
            try:
                resp = rds.list_tags_for_resource(ResourceName=arn)
                tags = tags_to_dict(resp.get("TagList", []))
            except ClientError:
                tags = {}
            if tags_match(tags, want, missing):
                rows.append((db_id, db_class, db_status, tags))
    return rows


def _list_s3(want, missing):
    """List S3 buckets matching tag filters.

    Note: get_bucket_tagging raises ClientError if no tagging config exists
    for that bucket. Treat that as an empty tags dict, not an error.

    Returns:
        list of (bucket_name, "bucket", "active", tags_dict) tuples
    """
    s3 = boto3.client("s3")
    rows = []
    try:
        resp = s3.list_buckets()
        for bucket in resp.get("Buckets", []):
            name = bucket["Name"]
            tags = {}
            try:
                tag_resp = s3.get_bucket_tagging(Bucket=name)
                tags = tags_to_dict(tag_resp.get("TagSet", []))
            except ClientError as e:
                # NoSuchTagSet or AccessDenied etc.
                pass
            if tags_match(tags, want, missing):
                rows.append((name, "bucket", "active", tags))
    except ClientError:
        pass
    return rows


def _list_volume(want, missing):
    """List EBS volumes matching tag filters.

    Returns:
        list of (volume_id, "<type>-<size>GB", state, tags_dict) tuples
        e.g. ("vol-0abc", "gp2-100GB", "in-use", {"purpose": "practice"})
    """
    ec2 = boto3.client("ec2")
    paginator = ec2.get_paginator("describe_volumes")
    rows = []
    for page in paginator.paginate():
        for vol in page.get("Volumes", []):
            vol_id = vol["VolumeId"]
            vol_type = vol["VolumeType"]
            size = vol["Size"]
            state = vol["State"]
            tags = tags_to_dict(vol.get("Tags", []))
            if tags_match(tags, want, missing):
                type_size = f"{vol_type}-{size}GB"
                rows.append((vol_id, type_size, state, tags))
    return rows


DISPATCH = {
    "ec2": _list_ec2,
    "rds": _list_rds,
    "s3": _list_s3,
    "volume": _list_volume,
}


def run(args):
    """Entry point called by costctl.py."""
    want = [parse_kv(t) for t in args.tag]
    missing = args.missing_tag
    rows = DISPATCH[args.type](want, missing)

    filters_parts = []
    for k, v in want:
        filters_parts.append(f"{k}={v}")
    for k in missing:
        filters_parts.append(f"missing={k}")

    filters_str = " ".join(filters_parts)
    if filters_str:
        header_text = f"{args.type.upper()} {filters_str} — {len(rows)} found:"
    else:
        header_text = f"{args.type.upper()} — {len(rows)} found:"

    print(header_text)
    print("-" * 78)

    for row in rows:
        tags_str = ", ".join(f"{k}={v}" for k, v in row[3].items())
        print(f"  {row[0]:<25} {row[1]:<14} {row[2]:<14} {tags_str}")
