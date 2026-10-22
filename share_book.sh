#!/bin/bash
# Upload one Project Gutenberg book to a private S3 bucket and print a presigned URL.
# Usage: ./share_book.sh BOOK_URL BUCKET_NAME EXPIRES_IN_SECONDS
set -euo pipefail

# Validate positional arguments
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 BOOK_URL BUCKET_NAME EXPIRES_IN_SECONDS" >&2
    exit 1
fi

BOOK_URL="$1"
BUCKET="$2"
EXPIRES="$3"
FILE_NAME="$(basename "$BOOK_URL")"
LOCAL_PATH="books/$FILE_NAME"

# Download the book, keeping the file name from the URL
mkdir -p books
curl -sSfL "$BOOK_URL" -o "$LOCAL_PATH"
echo "Downloaded $BOOK_URL -> $LOCAL_PATH" >&2

# Create the bucket unless it already exists (it stays private by default)
if aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
    echo "Bucket already exists: $BUCKET" >&2
else
    aws s3 mb "s3://$BUCKET" --region us-east-1 >&2
fi

# Upload the book as plain text so it displays in the browser
aws s3 cp "$LOCAL_PATH" "s3://$BUCKET/$FILE_NAME" \
    --content-type "text/plain; charset=utf-8" >&2

# Presign a time-limited URL to the private book and print it
aws s3 presign "s3://$BUCKET/$FILE_NAME" --expires-in "$EXPIRES"
