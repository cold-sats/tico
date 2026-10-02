#!/bin/sh
# Planning is the default; only --apply makes AWS calls or writes a signing key.
set -eu
exec python3 - "$@" <<'PY'
import argparse
import hashlib
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser(description='Private attachment bucket and signed CloudFront delivery')
parser.add_argument('--bucket', required=True)
parser.add_argument('--region', required=True)
parser.add_argument('--private-key-path', required=True, type=Path)
mode = parser.add_mutually_exclusive_group()
mode.add_argument('--apply', action='store_true')
mode.add_argument('--dry-run', action='store_true')
args = parser.parse_args()
name = 'tico-attachments-' + args.bucket
print(json.dumps({'bucket': args.bucket, 'region': args.region, 'public_access': 'blocked',
 'encryption': 'AES256', 'origin': 'S3 with Origin Access Control', 'signed_urls': 'trusted key group',
 'cache': {'MinTTL': 0, 'DefaultTTL': 30, 'MaxTTL': 31536000},
 'private_key_path': str(args.private_key_path), 'mode': 'apply' if args.apply else 'dry-run'}, indent=2))
if not args.apply:
    raise SystemExit(0)
import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

path = args.private_key_path
if path.is_symlink():
    raise SystemExit('The signing key path must not be a symbolic link')
if path.exists():
    os.chmod(path, 0o600)
    pem = path.read_bytes()
else:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(pem)
key = serialization.load_pem_private_key(pem, password=None)
public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
s3, cf = boto3.client('s3', region_name=args.region), boto3.client('cloudfront')
try:
    s3.head_bucket(Bucket=args.bucket)
except ClientError as exc:
    if exc.response['Error']['Code'] not in ('404', 'NoSuchBucket', 'NotFound'):
        raise
    options = {} if args.region == 'us-east-1' else {'CreateBucketConfiguration': {'LocationConstraint': args.region}}
    s3.create_bucket(Bucket=args.bucket, **options)
s3.put_public_access_block(Bucket=args.bucket, PublicAccessBlockConfiguration={
 'BlockPublicAcls': True, 'IgnorePublicAcls': True, 'BlockPublicPolicy': True, 'RestrictPublicBuckets': True})
s3.put_bucket_encryption(Bucket=args.bucket, ServerSideEncryptionConfiguration={'Rules': [
 {'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]})
s3.put_bucket_ownership_controls(Bucket=args.bucket, OwnershipControls={'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]})
# Abandoned multipart uploads cannot accumulate indefinitely.
try:
    lifecycle = s3.get_bucket_lifecycle_configuration(Bucket=args.bucket)['Rules']
except ClientError as exc:
    if exc.response['Error']['Code'] != 'NoSuchLifecycleConfiguration':
        raise
    lifecycle = []
lifecycle = [r for r in lifecycle if r.get('ID') != 'tico-abort-incomplete'] + [
 {'ID': 'tico-abort-incomplete', 'Status': 'Enabled', 'Filter': {'Prefix': 'blobs/'},
  'AbortIncompleteMultipartUpload': {'DaysAfterInitiation': 1}}]
s3.put_bucket_lifecycle_configuration(Bucket=args.bucket, LifecycleConfiguration={'Rules': lifecycle})



def listing(operation, root, **kwargs):
    marker = None
    while True:
        response = getattr(cf, operation)(**kwargs, **({'Marker': marker} if marker else {}))[root]
        yield from response.get('Items', [])
        if not response.get('IsTruncated'):
            return
        marker = response['NextMarker']


def ensure(operation, root, config_name, config, list_kwargs=None):
    # List summaries sometimes wrap the named configuration.
    for item in listing('list_' + (operation[:-1] + 'ies' if operation.endswith('y') else operation + 's'), root, **(list_kwargs or {})):
        row = item.get(operation.title().replace('_', ''), item)
        spec = row.get(config_name, row)
        if spec.get('Name') == config['Name']:
            return row['Id']
    result = getattr(cf, 'create_' + operation)(**{config_name: config})
    return result[operation.title().replace('_', '')]['Id']

fingerprint = hashlib.sha256(public.encode()).hexdigest()[:16]
key_id = ensure('public_key', 'PublicKeyList', 'PublicKeyConfig', {
 'CallerReference': name + '-' + fingerprint, 'Name': name[:90] + '-' + fingerprint,
 'EncodedKey': public, 'Comment': name})
group_id = ensure('key_group', 'KeyGroupList', 'KeyGroupConfig', {
 'Name': name[:100] + '-' + fingerprint, 'Items': [key_id], 'Comment': name})
oac_id = ensure('origin_access_control', 'OriginAccessControlList', 'OriginAccessControlConfig', {
 'Name': name[:64], 'Description': name, 'SigningProtocol': 'sigv4', 'SigningBehavior': 'always',
 'OriginAccessControlOriginType': 's3'})
cache_id = ensure('cache_policy', 'CachePolicyList', 'CachePolicyConfig', {
 'Name': name + '-origin-cache', 'Comment': name, 'MinTTL': 0, 'DefaultTTL': 30, 'MaxTTL': 31536000,
 'ParametersInCacheKeyAndForwardedToOrigin': {
  'EnableAcceptEncodingGzip': False, 'EnableAcceptEncodingBrotli': False,
  'HeadersConfig': {'HeaderBehavior': 'none'}, 'CookiesConfig': {'CookieBehavior': 'none'},
  'QueryStringsConfig': {'QueryStringBehavior': 'none'}}}, {'Type': 'custom'})
headers_id = ensure('response_headers_policy', 'ResponseHeadersPolicyList', 'ResponseHeadersPolicyConfig', {
 'Name': name + '-safe-media', 'Comment': name, 'SecurityHeadersConfig': {
  'ContentTypeOptions': {'Override': True},
  'ContentSecurityPolicy': {'ContentSecurityPolicy': "default-src 'none'; sandbox", 'Override': True}}}, {'Type': 'custom'})
config = {'CallerReference': name, 'Comment': name, 'Enabled': True, 'PriceClass': 'PriceClass_100',
 'Origins': {'Quantity': 1, 'Items': [{'Id': 'attachments',
  'DomainName': args.bucket + '.s3.' + args.region + '.amazonaws.com', 'OriginPath': '',
  'S3OriginConfig': {'OriginAccessIdentity': ''}, 'OriginAccessControlId': oac_id}]},
 'DefaultCacheBehavior': {'TargetOriginId': 'attachments', 'ViewerProtocolPolicy': 'https-only',
  'TrustedKeyGroups': {'Enabled': True, 'Quantity': 1, 'Items': [group_id]},
  'CachePolicyId': cache_id, 'ResponseHeadersPolicyId': headers_id, 'Compress': False,
  'AllowedMethods': {'Quantity': 2, 'Items': ['GET', 'HEAD'],
   'CachedMethods': {'Quantity': 2, 'Items': ['GET', 'HEAD']}}},
 'ViewerCertificate': {'CloudFrontDefaultCertificate': True}, 'HttpVersion': 'http2', 'IsIPV6Enabled': True}
existing = next((r for r in listing('list_distributions', 'DistributionList') if r['Comment'] == name), None)
if existing:
    found = cf.get_distribution_config(Id=existing['Id'])
    current = found['DistributionConfig']
    # Preserve CloudFront defaults and caller reference; update only managed fields.
    for field, value in config.items():
        if field != 'CallerReference':
            current[field] = value
    result = cf.update_distribution(Id=existing['Id'], IfMatch=found['ETag'], DistributionConfig=current)['Distribution']
else:
    result = cf.create_distribution(DistributionConfig=config)['Distribution']
statement = {'Sid': 'TicoAttachmentsOAC', 'Effect': 'Allow', 'Principal': {'Service': 'cloudfront.amazonaws.com'},
 'Action': 's3:GetObject', 'Resource': 'arn:aws:s3:::' + args.bucket + '/blobs/*',
 'Condition': {'StringEquals': {'AWS:SourceArn': result['ARN']}}}
try:
    policy = json.loads(s3.get_bucket_policy(Bucket=args.bucket)['Policy'])
except ClientError as exc:
    if exc.response['Error']['Code'] != 'NoSuchBucketPolicy':
        raise
    policy = {'Version': '2012-10-17', 'Statement': []}
policy['Statement'] = [r for r in policy['Statement'] if r.get('Sid') != statement['Sid']] + [statement]
s3.put_bucket_policy(Bucket=args.bucket, Policy=json.dumps(policy))
print(json.dumps({'TICO_BLOB_BUCKET': args.bucket, 'TICO_CDN_URL': 'https://' + result['DomainName'],
 'TICO_CDN_KEY_ID': key_id, 'distribution_id': result['Id'],
 'next': 'Put the private key in Tico server secrets or vault; configure TICO_CDN_SECRET_ARN or TICO_CDN_CREDENTIAL_ID.'}, indent=2))
PY
