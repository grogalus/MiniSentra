
''' 
Mini Sentra Scanner
Gal Grossman 
'''

import boto3
import os
import re
import tempfile
import json
import hashlib

# Initialize clients
s3 = boto3.client('s3')
sqs = boto3.client('sqs') if os.environ.get("ENABLE_SQS", "false").lower() == "true" else None

RESULT_BUCKET = os.environ.get("RESULT_BUCKET")
HASH_PREFIX = "hashes/"  # Directory to store file hashes

# Feature flag for SQS integration
ENABLE_SQS = os.environ.get("ENABLE_SQS", "false").lower() == "true"
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL")

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

def extract_emails_with_positions(text,bucket, key):
    """Extract emails along with their positions in the text"""
    results = []
    for match in re.finditer(EMAIL_REGEX, text):
        results.append({
            "pii_type": "email",
            "email": match.group(),
            "bucket_name": bucket,
            "file": key,
            "position_in_file": match.start()
        })
    return results

def process_txt(file_path):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()
    

# Example of plugable file scanner #
# def process_pdf(file_path):
#     reader = PdfReader(file_path)
#     return "\n".join([page.extract_text() or "" for page in reader.pages]) 

def calculate_file_hash(file_path):
    """Calculate MD5 hash of a file"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_file_hash_key(bucket, key):
    """Create a consistent key for storing file hashes"""
    return f"{HASH_PREFIX}{bucket}/{key}.hash"

def get_stored_hash(bucket, key):
    hash_key = get_file_hash_key(bucket, key)
    try:
        response = s3.get_object(Bucket=RESULT_BUCKET, Key=hash_key)
        return response['Body'].read().decode('utf-8').strip()
    except s3.exceptions.ClientError:
        return None

def store_file_hash(bucket, key, file_hash):
    """Store hash for a processed file"""
    hash_key = get_file_hash_key(bucket, key)
    try:
        s3.put_object(
            Bucket=RESULT_BUCKET,
            Key=hash_key,
            Body=file_hash,
            ContentType='text/plain'
        )
    except Exception as e:
        print(f"Error storing hash for {bucket}/{key}: {e}")

def result_exists(key):
    """Check if results already exist for the given key"""
    result_key = f"results/{key}.emails.json"
    try:
        s3.head_object(Bucket=RESULT_BUCKET, Key=result_key)
        return True
    except:
        return False

def send_to_sqs(bucket, key, email_results):
    """Send results to SQS in a different account using cross-account role"""
    if not ENABLE_SQS:
        print("SQS for Sentra is Disabled")
        return
    
    if not SQS_QUEUE_URL:
        print("SQS feature enabled but missing configuration (SQS_QUEUE_URL)")
        return
    
    try:
        emails = [result["email"] for result in email_results]
        
        # Payload
        message = {
            'source': {
                'bucket': bucket,
                'key': key
            },
            'timestamp': str(boto3.Session().client('sts').get_caller_identity().get('Account')),
            'result': {
                'type': 'email',
                'count': len(email_results),
                'data': emails,
                'detailed_results': email_results  # Include the detailed results with positions
            }
        }
        
        # Send message to SQS
        response = sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message)
        )
        
        print(f"SQS message sent: {response['MessageId']}")
        
    except Exception as e:
        print(f"Error sending results to SQS: {e}")

def process_file(bucket, key):
    """Process a file if it hasn't been processed or has changed"""
    try:
        # Check for file type
        file_type = key.split('.')[-1].lower() if '.' in key else ''
        
        # Skip processing non-text files
        if file_type not in ['txt', 'pdf', 'csv', 'json', 'html', 'xml']:
            print(f"Skipping non-text file: {key}")
            return
            
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            s3.download_file(bucket, key, tmp.name)
            
            current_hash = calculate_file_hash(tmp.name)

            stored_hash = get_stored_hash(bucket, key)
            
            if stored_hash == current_hash and result_exists(key):
                print(f"File {key} unchanged (hash: {current_hash}), skipping")
                return
                
            # Process the file based on type
            if file_type == 'pdf':
                #content = process_pdf(tmp.name)
                print("This is a plugable extenstion, use any python library to read PDF :)")
            else:  # Default to text processing
                content = process_txt(tmp.name)
                
            email_results = extract_emails_with_positions(content, bucket, key)
            print(f"{key}: Found {len(email_results)} email(s)")

            # Store results
            result_key = f"results/{key}.emails.json"
            s3.put_object(
                Bucket=RESULT_BUCKET,
                Key=result_key,
                Body=json.dumps(email_results),
                ContentType='application/json'
            )
            
            # Store the hash
            store_file_hash(bucket, key, current_hash)
            
            # Send results to SQS ONLY if emails were found and SQS is enabled
            if ENABLE_SQS and email_results:
                print(f"Sending {len(email_results)} emails to SQS queue")
                send_to_sqs(bucket, key, email_results)
            elif ENABLE_SQS and not email_results:
                print(f"No emails found in {key}, skipping SQS notification")
            
    except Exception as e:
        print(f"Error processing {key}: {e}")
    finally:
        # Clean up the temp files
        if 'tmp' in locals() and os.path.exists(tmp.name):
            os.unlink(tmp.name)

def scan_all_buckets():
    buckets = s3.list_buckets()["Buckets"]
    for bucket in buckets:
        bucket_name = bucket["Name"]
        if bucket_name == RESULT_BUCKET:
            continue
        print(f"Scanning bucket: {bucket_name}")
        try:
            has_awslogs = s3.list_objects_v2(Bucket=bucket_name, Prefix="AWSLogs", MaxKeys=1)
            if 'Contents' in has_awslogs:
                print(f" - Skipping {bucket_name} (contains AwsLogs/)")
                continue
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    print(f" - Checking {key}")
                    process_file(bucket_name, key)
        except Exception as e:
            print(f"Failed to scan {bucket_name}: {e}")

def lambda_handler(event, context):
    # S3 notification mode
    print("Trigger: S3 Notification - Performing bucket scan for this event")
    if "Records" in event and event["Records"][0].get("eventSource") == "aws:s3":
        for record in event["Records"]:
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            process_file(bucket, key)
    # Manual mode        
    else:
        print("Trigger: Manual or Scheduled - Performing full buckets scan")
        scan_all_buckets()

    return {
        "statusCode": 200,
        "body": "Scan complete"
    }