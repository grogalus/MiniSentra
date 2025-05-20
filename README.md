# 📦 Sentra Scanner

Sentra Scanner is an AWS Lambda function that scans S3 buckets in your AWS account for specific patterns (e.g., email addresses) and sends the results to an Amazon SQS queue for downstream processing.

## 🧩 Architecture

1. **S3**: both Manual Trigger (Perform Full Scan) and Event Trigger are being supported -
   - An event (e.g., "S3 Notification") cab trigger the Lambda function automaticlly (need to be configured manually as this time)
3. **Lambda (Sentra Scanner)**: Downloads the file, scans for matches (e.g., email addresses), and sends results.
4. **SQS Queue**: Collects results for downstream consumption or processing.


## 🚀 Features

- Scans files in S3 buckets
- Supports multiple file types (TXT, CSV) and can be extendable to other file types
- Extracts and identifies email addresses
- Sends results to a SQS queue

## Deployment Steps
### deploy it as cloudformation stack (please use us-east-2 region for ease of deployment)

### Only need to provide stack name
https://console.aws.amazon.com/cloudformation/home?region=us-east-2#/stacks/create/review?templateURL=https://gal-mini-sentra-public.s3.amazonaws.com/templates/mini_sentra.yaml


## SQS Intergration - Default is true (Send Results to Sentra queue)
EnableSQS=true
