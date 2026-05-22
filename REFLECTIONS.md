# Reflections — costctl AWS Management CLI

This document outlines key technical considerations, safety trade-offs, and design enhancements discovered while building the `costctl` CLI.

---

### 1. Scaling to 100+ AWS Accounts (Multi-Account Strategy)

To scale `costctl` to run against 100+ AWS accounts, several changes are required:
*   **Cross-Account IAM Roles**: Instead of relying on a single local AWS profile, the CLI should accept an `--account-id` or `--profile` parameter. For each target account, the CLI will use the AWS Security Token Service (STS) `AssumeRole` API to assume a predefined cross-account IAM role (e.g., `OrganizationAccountAccessRole` or `costctl-executor-role`) and obtain temporary security credentials.
*   **Concurrently Scanning**: Running sequential API requests over 100+ accounts would be extremely slow. We would introduce Python's `concurrent.futures.ThreadPoolExecutor` to query accounts in parallel.
*   **Centralized Aggregation**: Instead of print-to-stdout only, all commands would support `--format json` or `--format csv` to easily aggregate all findings into a centralized S3 bucket or database for reporting and visualization.

---

### 2. `idle` Command vs AWS Trusted Advisor

The `idle` command uses a configurable `N`-hour window (default 24 hours) for average CPU metrics, whereas AWS Trusted Advisor (TA) analyzes a standard 14-day window.

*   **When to trust `idle` more**: 
    *   **Short-Lived & Experimental Environments**: For developer sandboxes, training labs, or trial environments, a 24-hour average is much more effective. If a resource was launched, had a burst of activity, and sat idle for the last 20 hours, we want to flag and terminate it immediately rather than waiting 14 days.
    *   **Aggressive Dev/Test Optimization**: During cost-saving sprints or weekend cleanups, a 24-hour or 48-hour idle scan can quickly reclaim hundreds of dollars of forgotten infrastructure.
*   **When to trust Trusted Advisor more**:
    *   **Production & Enterprise Workloads**: Steady-state workloads often run batch jobs, periodic cron tasks, or backups once a week. An instance that sits idle for 5 days but spikes to 100% on the 6th day for critical business data would be mistakenly killed by a 24h idle scan but correctly ignored by TA's 14-day analysis.

---

### 3. Limiting the Blast Radius of `clean --apply`

Running a bulk clean command like `clean --tag Environment=dev --apply` in a shared AWS account carries an immense risk of terminating resources owned by other teams. To mitigate this risk, we would implement:
1.  **Multiple Tag Filters (Logical AND)**: Restrict cleanup to require multiple matching tags, such as both `Environment=dev` AND `Owner=Nhom9`.
2.  **Explicit Multi-Step Confirmations**: Require the user to type a randomized prompt or the exact count of matched resources to execute (e.g. `Type "confirm-12-instances" to delete`).
3.  **Strict Resource Termination Protection**: Ensure the CLI respects and checks the `DisableApiTermination` attribute for EC2 instances.
4.  **IAM Condition Policies**: Deploy IAM user/role permissions with strict conditions using `aws:ResourceTag/Owner` so that the credentials used by `costctl` are physically incapable of terminating resources that do not belong to group 9.

---

### 4. AI-Assistance & Custom Modifications

*   **AI-Generated Fraction**: Approximately 80% of the core boto3 pagination, boilerplate API calls, and argparse layout were generated successfully by Gemini.
*   **Actively Modified Parts**:
    *   **S3 Empty Checks**: I custom-implemented a dual check using `KeyCount` and `Contents` on S3 bucket contents to prevent false empty detections across different boto3 versions and mock environments.
    *   **Tag Merging logic for S3**: The standard `put_bucket_tagging` API overwrites the entire tag set. I actively refined the `_tag_s3` method to fetch, merge, and put tags to prevent data loss.
    *   **Output Alignment**: Customized the string padding and alignment logic across list and scan tables to ensure readable, uniform alignment for terminal outputs.
