#!/usr/bin/env python3
"""Stage a collection of Project Gutenberg books in a public S3 bucket.

Downloads the books listed in a URL file, creates an S3 bucket, makes it
publicly readable, and uploads the books plus an index page.

Usage:
    uv run python src/s3_lab/stage_books.py book_urls.txt index.html public-mst3k
"""
import json
import logging
import os
import sys
import time

import boto3
import requests
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# One S3 client shared by all functions
s3 = boto3.client("s3", region_name="us-east-1")


def parse_args():
    """Read the book list path, index page path, and bucket name from the command line.

    Returns:
        tuple: (list_file, index_path, bucket) as strings.
    """
    if len(sys.argv) < 4:
        log.error(f"Usage: {sys.argv[0]} BOOK_LIST_FILE INDEX_HTML BUCKET_NAME")
        sys.exit(1)
    return sys.argv[1], sys.argv[2], sys.argv[3]


def download_books(list_file, dest_dir):
    """Download each book listed in list_file into dest_dir.

    Books that already exist locally are skipped, so the script can be rerun.

    Args:
        list_file (str): Path of a text file with one book URL per line.
        dest_dir (str): Folder to save the books in.

    Returns:
        list: Local paths of the books that are available in dest_dir.
    """
    os.makedirs(dest_dir, exist_ok=True)
    try:
        with open(list_file) as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log.error(f"Book list not found: {list_file}")
        return []

    paths = []
    for url in urls:
        # Keep the file name from the URL, e.g. pg1342.txt
        path = os.path.join(dest_dir, url.rstrip("/").split("/")[-1])
        if os.path.exists(path):
            log.info(f"Already downloaded, skipping: {path}")
            paths.append(path)
            continue
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()  # raise an error for 404 etc.
            with open(path, "wb") as out:
                out.write(response.content)
            log.info(f"Downloaded {url} -> {path}")
            paths.append(path)
        except requests.RequestException as e:
            log.error(f"Error downloading {url}: {e}")
        # Be polite to Project Gutenberg's servers
        time.sleep(1)

    log.info(f"{len(paths)} of {len(urls)} books available in {dest_dir}/")
    return paths


def create_bucket(bucket):
    """Create the bucket in us-east-1 unless it already exists.

    Args:
        bucket (str): Bucket name.

    Returns:
        bool: True if the bucket exists afterwards, False otherwise.
    """
    try:
        s3.head_bucket(Bucket=bucket)
        log.info(f"Bucket already exists: {bucket}")
        return True
    except ClientError:
        log.info(f"Bucket {bucket} not found, creating it")

    try:
        # us-east-1: omit LocationConstraint or create_bucket fails
        s3.create_bucket(Bucket=bucket)
        log.info(f"Created bucket: {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error creating bucket {bucket}: {e}")
        return False


def make_public(bucket):
    """Turn off Block Public Access and attach a public-read bucket policy.

    Args:
        bucket (str): Bucket name.

    Returns:
        bool: True on success, False otherwise.
    """
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/*",
            }
        ],
    }
    try:
        # Block Public Access must be off before a public policy is accepted
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        log.info(f"Turned off Block Public Access for {bucket}")
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info(f"Attached public-read policy to {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error making bucket {bucket} public: {e}")
        return False


def upload_files(bucket, file_paths):
    """Upload each file to the top level of the bucket as plain text.

    Args:
        bucket (str): Bucket name.
        file_paths (list): Local paths of the files to upload.

    Returns:
        int: Number of files uploaded successfully.
    """
    uploaded = 0
    for path in file_paths:
        key = os.path.basename(path)  # pg1342.txt, not books/pg1342.txt
        try:
            with open(path, "rb") as f:
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=f,
                    ContentType="text/plain; charset=utf-8",  # display in browser
                )
            log.info(f"Uploaded {path} to s3://{bucket}/{key}")
            uploaded += 1
        except (OSError, ClientError) as e:
            log.error(f"Error uploading {path}: {e}")
    log.info(f"Uploaded {uploaded} of {len(file_paths)} files to {bucket}")
    return uploaded


def upload_index(bucket, index_path):
    """Upload the index page to the bucket as index.html.

    Args:
        bucket (str): Bucket name.
        index_path (str): Local path of the index page.

    Returns:
        bool: True on success, False otherwise.
    """
    try:
        with open(index_path, "rb") as f:
            s3.put_object(
                Bucket=bucket,
                Key="index.html",
                Body=f,
                ContentType="text/html",  # display as a web page
            )
        log.info(f"Uploaded {index_path} to s3://{bucket}/index.html")
        return True
    except FileNotFoundError:
        log.error(f"Local file not found: {index_path}")
        return False
    except ClientError as e:
        log.error(f"Error uploading index page: {e}")
        return False


def main():
    """Download the books, create and publish the bucket, and upload everything."""
    list_file, index_path, bucket = parse_args()

    file_paths = download_books(list_file, "books")
    if not file_paths:
        log.error("No books were downloaded, stopping")
        sys.exit(1)

    if not create_bucket(bucket):
        sys.exit(1)
    if not make_public(bucket):
        sys.exit(1)

    uploaded = upload_files(bucket, file_paths)
    index_ok = upload_index(bucket, index_path)

    if uploaded == len(file_paths) and index_ok:
        log.info("Success: all books and the index page were uploaded")
    else:
        log.error("Failure: some files could not be uploaded, see errors above")
    log.info(f"Public index page: https://{bucket}.s3.amazonaws.com/index.html")


if __name__ == "__main__":
    main()
