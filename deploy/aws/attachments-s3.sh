#!/usr/bin/env bash
# Provision a dedicated private file bucket and grant an existing IAM principal access.
set -euo pipefail
python3 - "$@" <<'PYTHON'
import argparse
import json

parser = argparse.ArgumentParser(description="Private Tico file storage; dry run by default")
parser.add_argument('--bucket', required=True)
parser.add_argument('--region', default='us-east-1')
principal = parser.add_mutually_exclusive_group(required=True)
principal.add_argument('--user', help='Existing IAM user name')
principal.add_argument('--role', help='Existing IAM role name')
mode = parser.add_mutually_exclusive_group()
mode.add_argument('--dry-run', action='store_true')
mode.add_argument('--apply', action='store_true')
args = parser.parse_args()
policy = {'Version': '2012-10-17', 'Statement': [
 {'Effect': 'Allow', 'Action': ['s3:ListBucket', 's3:GetBucketLocation'],
  'Resource': 'arn:aws:s3:::' + args.bucket},
 {'Effect': 'Allow', 'Action': ['s3:GetObject', 's3:PutObject', 's3:AbortMultipartUpload',
                              's3:ListMultipartUploadParts'],
  'Resource': 'arn:aws:s3:::' + args.bucket + '/*'}]}
if not args.apply:
    print(json.dumps({'bucket': args.bucket, 'region': args.region,
                      'principal': args.user or args.role, 'policy': policy,
                      'changes': ['private bucket', 'block public access', 'AES256 encryption',
                                  'BucketOwnerEnforced', 'abort incomplete uploads after 2 days',
                                  'inline IAM policy']}, indent=2))
    raise SystemExit(0)

import boto3
from botocore.exceptions import ClientError
s3 = boto3.client('s3', region_name=args.region)
iam = boto3.client('iam')
try:
    s3.head_bucket(Bucket=args.bucket)
except ClientError as exc:
    if exc.response['Error']['Code'] not in ('404', 'NoSuchBucket', 'NotFound'):
        raise
    options = {} if args.region == 'us-east-1' else {
        'CreateBucketConfiguration': {'LocationConstraint': args.region}}
    s3.create_bucket(Bucket=args.bucket, **options)
s3.put_public_access_block(Bucket=args.bucket, PublicAccessBlockConfiguration={
 'BlockPublicAcls': True, 'IgnorePublicAcls': True, 'BlockPublicPolicy': True, 'RestrictPublicBuckets': True})
s3.put_bucket_encryption(Bucket=args.bucket, ServerSideEncryptionConfiguration={
 'Rules': [{'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]})
s3.put_bucket_ownership_controls(Bucket=args.bucket, OwnershipControls={
 'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]})
try:
    rules = s3.get_bucket_lifecycle_configuration(Bucket=args.bucket)['Rules']
except ClientError as exc:
    if exc.response['Error']['Code'] != 'NoSuchLifecycleConfiguration':
        raise
    rules = []
rules = [r for r in rules if r.get('ID') != 'tico-abort-incomplete'] + [
 {'ID': 'tico-abort-incomplete', 'Status': 'Enabled', 'Filter': {'Prefix': ''},
  'AbortIncompleteMultipartUpload': {'DaysAfterInitiation': 2}}]
s3.put_bucket_lifecycle_configuration(Bucket=args.bucket, LifecycleConfiguration={'Rules': rules})
# A stable policy name makes repeat applications replace this grant only.
policy_name = 'tico-files-' + args.bucket
if args.user:
    iam.put_user_policy(UserName=args.user, PolicyName=policy_name, PolicyDocument=json.dumps(policy))
else:
    iam.put_role_policy(RoleName=args.role, PolicyName=policy_name, PolicyDocument=json.dumps(policy))
print(json.dumps({'TICO_BLOB_BUCKET': args.bucket, 'TICO_BLOB_REGION': args.region}))
PYTHON
