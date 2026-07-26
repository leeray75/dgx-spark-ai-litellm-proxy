#!/usr/bin/env python3
"""
GPU Power Consumption Benchmark for LLM Inference
==================================================
Monitors NVIDIA GPU power draw while sending complex prompts through a LiteLLM proxy.
Generates a structured log file for later analysis and report generation.

Usage:
    python3 gpu-power-benchmark.py [--api-key KEY] [--base-url URL] [--model MODEL] [--output FILE]

Example:
    python3 gpu-power-benchmark.py \\
        --api-key sk-your-key \\
        --base-url http://localhost:4000/v1 \\
        --model qwen3.6-35b-a3b \\
        --output /home/leeray75/vscode-workspace/ai-litellm-proxy/ai-workspace/reports/power-bench-2026-07-15.log
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import logging
import datetime
import threading
import uuid
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_API_KEY = "sk-your-key-here"
DEFAULT_BASE_URL = "http://localhost:4000/v1"
DEFAULT_MODEL = "qwen3.6-35b-a3b"

POWER_SAMPLE_INTERVAL = 0.5  # seconds between nvidia-smi samples
PROMPT_TIMEOUT = 300  # seconds per LLM request (5 min max)
WARMUP_BEFORE = 3  # seconds of power sampling before each prompt
WARMUP_AFTER = 5  # seconds of power sampling after each prompt

# Global list to collect power samples (thread-safe via append)
_power_samples = []
_power_sampling = False


# =============================================================================
# Prompt Loading & Cache-Busting
# =============================================================================

def load_prompts_from_file(prompts_file):
    """Load prompts from JSON file and return dict keyed by 'key' field."""
    try:
        with open(prompts_file, "r") as f:
            data = json.load(f)
        prompts_dict = {}
        for p in data.get("prompts", []):
            prompts_dict[p["key"]] = {
                "title": p["title"],
                "description": p["description"],
                "messages": p["messages"],
            }
        return prompts_dict
    except Exception as e:
        logging.error("Failed to load prompts from %s: %s", prompts_file, e)
        return None


def apply_cache_busting(prompts_dict, run_id):
    """Add unique identifiers to each prompt to prevent cache hits."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")
    result = {}
    for key, prompt_data in prompts_dict.items():
        mutated = {}
        for k, v in prompt_data.items():
            if k == "messages":
                mutated_messages = []
                for msg in v:
                    new_msg = dict(msg)
                    if "content" in new_msg:
                        new_msg["content"] = (
                            new_msg["content"]
                            .replace("{{TIMESTAMP}}", timestamp)
                            .replace("{{RUN_ID}}", run_id)
                        )
                    mutated_messages.append(new_msg)
                mutated["messages"] = mutated_messages
            else:
                mutated[k] = v
        result[key] = mutated
    return result


# =============================================================================
# Complex Prompts (fallback if JSON file not found)
# =============================================================================

PROMPTS = {
    "complex_reasoning": {
        "title": "Complex Multi-Step Reasoning",
        "description": "Multi-step logical reasoning with constraints",
        "messages": [
            {
                "role": "user",
                "content": "You are a senior logistics optimization consultant. Analyze the following supply chain problem and provide a comprehensive solution:\n\nA manufacturing company operates 5 factories (A, B, C, D, E) producing 3 product lines (X, Y, Z). Each factory has different production capabilities and costs:\n\nFactory A: Can produce X and Y. Production cost: X=$120/unit, Y=$180/unit. Max capacity: 10,000 units/day.\nFactory B: Can produce Y and Z. Production cost: Y=$150/unit, Z=$200/unit. Max capacity: 8,000 units/day.\nFactory C: Can produce X, Y, and Z. Production cost: X=$110/unit, Y=$170/unit, Z=$190/unit. Max capacity: 12,000 units/day.\nFactory D: Can produce X and Z. Production cost: X=$125/unit, Z=$210/unit. Max capacity: 9,000 units/day.\nFactory E: Can produce Y and Z. Production cost: Y=$160/unit, Z=$195/unit. Max capacity: 7,000 units/day.\n\nDemand requirements (daily):\n- Product X: 8,000 units minimum\n- Product Y: 10,000 units minimum\n- Product Z: 6,000 units minimum\n\nShipping costs per unit to 3 distribution centers:\n- From Factory A: $15 to DC1, $20 to DC2, $25 to DC3\n- From Factory B: $18 to DC1, $16 to DC2, $22 to DC3\n- From Factory C: $12 to DC1, $19 to DC2, $21 to DC3\n- From Factory D: $20 to DC1, $17 to DC2, $18 to DC3\n- From Factory E: $22 to DC1, $21 to DC2, $15 to DC3\n\nDistribution center requirements (daily):\n- DC1: 7,000 units minimum\n- DC2: 8,000 units minimum\n- DC3: 5,000 units minimum\n\nConstraints:\n1. Each factory must maintain at least 20% of its capacity on its most expensive product line\n2. No single factory can supply more than 40% of any single distribution center\n3. Factory C must produce at least one unit of each product line\n4. The ratio of X:Y:Z production across all factories must be within 35%:45%:20% +/-5%\n5. Total daily shipping cost must not exceed $500,000\n\nProvide:\n1. An optimal production plan (units per product per factory)\n2. Distribution plan (units from each factory to each DC)\n3. Total daily production cost\n4. Total daily shipping cost\n5. Total daily cost (production + shipping)\n6. Identify any bottlenecks\n7. Suggest one improvement that would reduce costs by at least 5%\n\nShow your work step by step, including the mathematical formulation of the optimization problem."
            }
        ]
    },

    "long_context_analysis": {
        "title": "Long Context Document Analysis",
        "description": "Process and analyze a lengthy technical document",
        "messages": [
            {
                "role": "user",
                "content": "Analyze the following comprehensive technical specification document and provide a detailed summary with architectural recommendations:\n\n=== Technical Specification: Enterprise Microservices Platform v4.0 ===\n\n1. EXECUTIVE SUMMARY\n1.1 Purpose\nThis document outlines the technical specifications for the next-generation enterprise microservices platform, codenamed Aurora. The platform is designed to support 10,000+ concurrent API endpoints, process 1 million+ transactions per second, and maintain 99.999% availability across three geographic regions.\n\n1.2 Scope\nThe Aurora platform replaces the legacy monolithic application (codenamed Titan) which currently processes 500K transactions/second across 2,000 API endpoints. The migration must be completed within 18 months with zero downtime.\n\n2. ARCHITECTURE OVERVIEW\n2.1 Service Mesh\n- Primary: Istio 1.19+ with Envoy proxy\n- Secondary: Linkerd for low-latency services\n- mTLS: Automatic certificate rotation every 24 hours\n- Traffic splitting: Canary deployments with 5% baseline traffic\n\n2.2 API Gateway\n- Kong Gateway 3.4 with custom plugins\n- Rate limiting: Token bucket algorithm, 10K req/s per tenant\n- Authentication: OAuth 2.0 + OIDC with JWKS rotation\n- Request transformation: gRPC to REST, GraphQL federation\n\n2.3 Data Layer\n- Primary: PostgreSQL 16 (sharded, 12 nodes)\n- Cache: Redis 7.2 cluster (256 GB total, 16 nodes)\n- Search: Elasticsearch 8.11 (3 data nodes, 2 master nodes)\n- Time-series: TimescaleDB 2.14 (5 nodes, 100TB capacity)\n- Object storage: MinIO (4 nodes, 1PB raw storage)\n\n2.4 Message Queue\n- Primary: Apache Kafka 3.6 (9 brokers, 64 partitions per topic)\n- Dead letter: Separate Kafka cluster for error handling\n- Stream processing: Apache Flink 1.18 (32 task managers)\n\n3. SECURITY REQUIREMENTS\n3.1 Authentication\n- Multi-factor: TOTP + hardware keys (FIDO2)\n- Service accounts: SPIFFE/SPIRE with short-lived JWTs\n- User provisioning: SCIM 2.0 with Azure AD sync\n- Session management: JWT with 15-minute expiry, refresh tokens 7 days\n\n3.2 Authorization\n- RBAC: 50+ roles, hierarchical permissions\n- ABAC: Attribute-based policies for data-level access\n- PDP: OPA 0.64 with Rego policies\n- Audit: All access decisions logged to immutable storage\n\n3.3 Encryption\n- At rest: AES-256-GCM with per-tenant keys (AWS KMS)\n- In transit: TLS 1.3 everywhere, HSTS with preload\n- Database: TDE with column-level encryption for PII\n- Secrets: HashiCorp Vault with automatic rotation\n\n3.4 Compliance\n- SOC 2 Type II (annual audit)\n- PCI DSS Level 1 (payment processing)\n- GDPR: Right to erasure, data portability\n- HIPAA: PHI protection for health data\n\n4. MONITORING AND OBSERVABILITY\n4.1 Metrics\n- Prometheus 3.0 (3 replicas, 14-day retention)\n- Grafana 10.4 (50+ dashboards, 200+ alerts)\n- Custom metrics: OpenTelemetry SDK, 100K+ unique metric series\n\n4.2 Logging\n- ELK stack: 50TB/day ingestion\n- Structured logging: JSON with correlation IDs\n- Log retention: 90 days hot, 1 year warm, 7 years cold (compliance)\n- PII filtering: Automatic redaction at ingestion\n\n4.3 Tracing\n- Jaeger/Tempo hybrid: 10% sampling rate, 100M spans/day\n- Service dependency map: Auto-discovered via service mesh\n- P99 latency tracking: Per-service, per-endpoint, per-region\n\n4.4 Alerting\n- PagerDuty integration: 200+ alert rules\n- Escalation: 3 levels, 5-minute intervals\n- On-call: Rotation with Slack integration\n- Incident response: Automated runbooks for 50+ scenarios\n\n5. CI/CD PIPELINE\n5.1 Build\n- GitHub Actions: 100 concurrent runners\n- Container: Docker BuildKit, multi-stage builds\n- SBOM: CycloneDX, SPDX compliance\n- Signing: Cosign with keyless signing (OIDC)\n\n5.2 Testing\n- Unit: pytest (Python), JUnit5 (Java), Jest (TypeScript)\n- Integration: Testcontainers, 500+ test suites\n- E2E: Playwright, 200 test scenarios\n- Performance: k6, 50 load test scenarios\n- Security: Trivy, Semgrep, SonarQube\n\n5.3 Deployment\n- GitOps: ArgoCD with sync waves\n- Strategy: Blue-green for critical services, canary for others\n- Rollback: Automatic on error rate > 1%\n- Environment: Dev (3 nodes), Staging (6 nodes), Prod (18 nodes)\n\n6. DISASTER RECOVERY\n6.1 Backup\n- Frequency: Incremental every 5 minutes, full daily\n- Retention: 35 days (compliance requirement)\n- Encryption: AES-256 at rest, TLS in transit\n- Testing: Monthly restore drills, 15-minute RTO target\n\n6.2 Failover\n- Active-Active: Three regions (us-east-1, eu-west-1, ap-southeast-1)\n- RPO: less than 1 second (synchronous replication)\n- RTO: less than 5 minutes (automated failover)\n- DNS: Route53 latency-based routing with health checks\n\n7. PERFORMANCE TARGETS\n7.1 Latency\n- P50: less than 50ms (API Gateway)\n- P95: less than 200ms\n- P99: less than 500ms\n- Database: P99 less than 10ms (read), less than 50ms (write)\n\n7.2 Throughput\n- API Gateway: 1M req/s sustained\n- Database: 500K writes/s, 2M reads/s\n- Message queue: 100K events/s per topic\n\n7.3 Scalability\n- Horizontal: Auto-scale based on CPU (70% threshold)\n- Vertical: Up to 64 vCPU, 256GB RAM per pod\n- Karpenter: Node provisioning in less than 10 seconds\n\n8. COST ESTIMATES\n8.1 Infrastructure (Monthly)\n- Compute: $120,000 (EC2, EKS)\n- Database: $45,000 (RDS, ElastiCache, DocumentDB)\n- Network: $25,000 (data transfer, load balancers, NAT)\n- Storage: $15,000 (EBS, S3, ECR)\n- Monitoring: $10,000 (Datadog, PagerDuty)\n- Total: $215,000/month\n\n8.2 Cost Optimization Targets\n- Year 1: $215,000/month\n- Year 2: $180,000/month (-16%)\n- Year 3: $150,000/month (-30% from baseline)\n\nAfter analyzing this document, provide:\n\n1. A 2-paragraph executive summary (50-75 words)\n2. A detailed architecture assessment covering:\n   - Strengths of the proposed architecture\n   - Potential single points of failure\n   - Security gaps or concerns\n   - Performance bottleneck risks\n3. A migration plan from Titan to Aurora with:\n   - Phase breakdown (min 5 phases)\n   - Risk assessment per phase\n   - Rollback strategy\n   - Timeline estimation\n4. A cost-benefit analysis comparing the old vs new system\n5. A prioritized list of 10 technical risks with mitigation strategies\n6. Recommendations for 3 areas where the spec could be improved\n7. An assessment of whether the 18-month timeline is realistic\n\nFormat your response with clear headings, bullet points, and tables where appropriate. Include specific metrics and numbers from the document in your analysis."
            }
        ]
    },

    "multi_turn_conversation": {
        "title": "Multi-Turn Conversation with Tool Calls",
        "description": "Simulated multi-turn conversation requiring tool calls and context retention",
        "messages": [
            {
                "role": "user",
                "content": "I am building a financial analysis dashboard. First, can you help me design the database schema for tracking stock portfolio performance? I need to track: users, portfolios, holdings, transactions, and price history. Consider that each user can have multiple portfolios, each holding can have multiple transactions over time, and price history needs to support minute-level granularity for trading data."
            }
        ]
    },

    "code_generation": {
        "title": "Complex Code Generation",
        "description": "Generate production-ready code for a complex system",
        "messages": [
            {
                "role": "user",
                "content": "Write production-ready Python code for a real-time stock market data processing pipeline. The system must:\n\n1. Ingest stock tick data via WebSocket from a hypothetical MarketDataAPI\n2. Implement a ring buffer for high-frequency price updates (target: 100K messages/second)\n3. Calculate rolling statistics (mean, std, min, max) with configurable windows (1s, 5s, 1m, 5m, 1h)\n4. Detect anomalies using z-score (threshold: 3.0) and flag them\n5. Persist processed data to PostgreSQL with proper connection pooling\n6. Expose a REST API (FastAPI) for querying historical data\n7. Implement proper error handling, retries with exponential backoff\n8. Add comprehensive logging with structured JSON format\n9. Include unit tests for the core calculation engine\n10. Add Docker Compose for easy deployment\n\nRequirements:\n- Use asyncio for all I/O operations\n- Implement circuit breaker pattern for the WebSocket connection\n- Use SQLAlchemy 2.0 async for database operations\n- Include health check endpoints\n- Add Prometheus metrics for monitoring\n- Implement graceful shutdown\n\nPlease provide:\n1. The main application entry point\n2. The WebSocket client with reconnection logic\n3. The ring buffer implementation\n4. The statistics calculator\n5. The anomaly detector\n6. The database models and repository\n7. The FastAPI routes\n8. The Docker Compose configuration\n9. Requirements file\n10. Unit tests\n\nMake sure the code is well-documented with docstrings and type hints. Follow PEP 8 style guide."
            }
        ]
    },

    "creative_task": {
        "title": "Creative Technical Writing",
        "description": "Generate creative technical content with specific constraints",
        "messages": [
            {
                "role": "user",
                "content": "Write a comprehensive technical blog post (2000-2500 words) about The Evolution of Database Systems: From Relational to Multi-Model.\n\nRequirements:\n1. Start with a compelling hook - perhaps a historical anecdote about the Y2K problem and how it shaped database choices\n2. Cover these eras in detail:\n   - The Relational Era (1970s-2000s): SQL, ACID, normalization\n   - The NoSQL Revolution (2000s-2010s): CAP theorem, eventual consistency, scaling challenges\n   - The Polyglot Persistence Era (2010s-2020s): Document, graph, time-series, vector databases\n   - The Multi-Model Era (2020s-present): Combining strengths, HTAP databases\n3. Include specific real-world examples (companies, products, benchmarks)\n4. Address common misconceptions in each era\n5. Provide a decision framework for choosing the right database for a given use case\n6. Include a comparison table (markdown format) covering: SQL, MongoDB, Neo4j, InfluxDB, Pinecone, Cassandra\n7. End with predictions for the next 5 years\n8. Use a conversational yet authoritative tone\n9. Include code snippets showing how the same query looks in 3 different database systems\n10. Add a Lessons Learned section with 5 key takeaways\n\nThe audience is senior software engineers and architects who need to make database decisions."
            }
        ]
    }
}


# =============================================================================
# Power Monitoring Functions
# =============================================================================

def _read_nvidia_smi():
    """Read a single nvidia-smi sample. Returns dict or None."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=power.draw,power.limit,utilization.gpu,memory.used,temperature.gpu",
                "--format=csv,noheader,nounits",
                "-i", "0",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 5:
                def _num(v):
                    v = v.strip()
                    return 0.0 if v == "[N/A]" else float(v)

                return {
                    "power_draw": _num(parts[0]),
                    "power_limit": _num(parts[1]),
                    "gpu_util": _num(parts[2]),
                    "mem_used": _num(parts[3]),
                    "temp": _num(parts[4]),
                }
    except Exception:
        pass
    return None


def _power_sampler_thread(log_path, stop_event):
    """Background thread that samples nvidia-smi power data at regular intervals."""
    start_time = time.time()
    header = [
        "timestamp", "epoch_seconds", "power_draw_w", "power_limit_w",
        "gpu_utilization", "memory_used_mb", "temperature_gpu"
    ]

    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        # Initial sample
        sample = _read_nvidia_smi()
        if sample:
            writer.writerow([
                datetime.datetime.utcnow().isoformat(),
                round(time.time() - start_time, 3),
                sample["power_draw"],
                sample["power_limit"],
                sample["gpu_util"],
                sample["mem_used"],
                sample["temp"],
            ])
            f.flush()

        while not stop_event.is_set():
            time.sleep(POWER_SAMPLE_INTERVAL)
            sample = _read_nvidia_smi()
            if sample:
                row = [
                    datetime.datetime.utcnow().isoformat(),
                    round(time.time() - start_time, 3),
                    sample["power_draw"],
                    sample["power_limit"],
                    sample["gpu_util"],
                    sample["mem_used"],
                    sample["temp"],
                ]
                with open(log_path, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
                    f.flush()


def start_power_monitoring(log_path):
    """Start power sampling in background thread. Returns stop_event."""
    global _power_sampling
    _power_sampling = True
    stop_event = threading.Event()
    t = threading.Thread(target=_power_sampler_thread, args=(log_path, stop_event), daemon=True)
    t.start()
    time.sleep(1)  # Let it stabilize
    return stop_event


def stop_power_monitoring(stop_event, log_path):
    """Stop power sampling and compute summary stats. Returns dict."""
    stop_event.set()
    time.sleep(0.5)

    # Parse CSV and compute summary
    return _parse_power_log(log_path)


def _parse_power_log(log_path):
    """Parse the power log CSV and compute summary statistics."""
    try:
        # Read CSV manually (no pandas dependency)
        power_data = []
        with open(log_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    power_data.append({
                        "epoch": float(row["epoch_seconds"]),
                        "power": float(row["power_draw_w"]),
                        "limit": float(row["power_limit_w"]) if row.get("power_limit_w", "").strip() else 0,
                        "util": float(row["gpu_utilization"]) if row.get("gpu_utilization", "").strip() else 0,
                        "mem": float(row["memory_used_mb"]) if row.get("memory_used_mb", "").strip() else 0,
                        "temp": float(row["temperature_gpu"]) if row.get("temperature_gpu", "").strip() else 0,
                    })
                except (ValueError, KeyError):
                    continue

        if not power_data:
            return {"error": "No power data collected"}

        duration_s = max(d["epoch"] for d in power_data)
        n = len(power_data)
        powers = [d["power"] for d in power_data]

        # Compute stats
        mean_p = sum(powers) / n
        max_p = max(powers)
        min_p = min(powers)
        variance = sum((p - mean_p) ** 2 for p in powers) / n
        std_p = variance ** 0.5

        # Energy: sum(power * dt) where dt = POWER_SAMPLE_INTERVAL
        dt_hours = POWER_SAMPLE_INTERVAL / 3600.0
        total_energy_wh = sum(powers) * dt_hours

        # Average utilization and memory
        avg_util = sum(d["util"] for d in power_data) / n
        avg_mem = sum(d["mem"] for d in power_data) / n
        avg_temp = sum(d["temp"] for d in power_data) / n

        return {
            "duration_seconds": round(duration_s, 2),
            "sample_count": n,
            "power_draw_mean_w": round(mean_p, 2),
            "power_draw_max_w": round(max_p, 2),
            "power_draw_min_w": round(min_p, 2),
            "power_draw_std_w": round(std_p, 2),
            "total_energy_wh": round(total_energy_wh, 4),
            "avg_gpu_utilization": round(avg_util, 2),
            "avg_memory_mb": round(avg_mem, 2),
            "avg_temperature": round(avg_temp, 2),
        }
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# LLM API Functions
# =============================================================================

def send_llm_request(base_url, api_key, model, messages, label, description, log_path):
    """Send a single LLM request and measure performance."""
    import urllib.request
    import urllib.error

    result = {
        "label": label,
        "description": description,
        "status": "pending",
        "time_to_first_token": None,
        "total_time": None,
        "tokens_generated": None,
        "response_length": None,
    }

    # Power sampling: warmup before
    logging.info("[PWR] Warmup before '%s'...", label)
    time.sleep(WARMUP_BEFORE)

    request_start = time.time()

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": False,
    }

    url = base_url + "/chat/completions"
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=PROMPT_TIMEOUT) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))

            request_end = time.time()
            result["total_time"] = round(request_end - request_start, 3)

            # Extract response details
            if "choices" in response_data:
                choice = response_data["choices"][0]
                content = choice.get("message", {}).get("content") or ""
                result["response_length"] = len(content)

                # Estimate tokens (rough: ~1.3 chars per token for English)
                result["tokens_generated"] = max(1, len(content) // 1.3)

            result["status"] = "success"

    except Exception as e:
        request_end = time.time()
        result["total_time"] = round(request_end - request_start, 3)
        result["status"] = "error: " + str(e)

    # Power sampling: warmup after
    logging.info("[PWR] Warmup after '%s'...", label)
    time.sleep(WARMUP_AFTER)

    logging.info("DONE '%s': %s (%ss)", label, result["status"], result.get("total_time"))
    return result


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="GPU Power Consumption Benchmark for LLM Inference")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="LiteLLM master key")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="LiteLLM API base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name to benchmark")
    parser.add_argument("--output", default=None, help="Output log file path")
    parser.add_argument("--prompts", nargs="+", default=None,
                        help="Specific prompts to run (default: all)")
    parser.add_argument("--prompts-file", default=None,
                        help="Path to JSON file with prompts (default: use built-in prompts)")
    parser.add_argument("--run-id", default=None,
                        help="Unique run ID for cache-busting (default: auto-generated)")
    args = parser.parse_args()

    # Generate run ID for cache-busting
    if args.run_id is None:
        args.run_id = str(uuid.uuid4())[:8]

    # Determine output path
    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir.parent / "ai-workspace" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        log_path = Path(args.output)
    else:
        log_path = output_dir / ("power-bench-" + datetime.date.today().isoformat() + ".log")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    power_csv_path = log_path.with_name(log_path.stem + "-power.csv")

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(str(log_path), mode="w"),
            logging.StreamHandler(sys.stdout),
        ]
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 80)
    logger.info("GPU POWER CONSUMPTION BENCHMARK")
    logger.info("=" * 80)
    logger.info("Timestamp: %s", datetime.datetime.utcnow().isoformat())
    logger.info("API Key: %s...%s", args.api_key[:10], args.api_key[-4:])
    logger.info("Base URL: %s", args.base_url)
    logger.info("Model: %s", args.model)
    logger.info("Output: %s", log_path)
    logger.info("Power sample interval: %ss", POWER_SAMPLE_INTERVAL)
    logger.info("Prompt timeout: %ss", PROMPT_TIMEOUT)
    logger.info("Power warmup before: %ss, after: %ss", WARMUP_BEFORE, WARMUP_AFTER)
    logger.info("-" * 80)

    # Check nvidia-smi availability
    result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("nvidia-smi failed. Is the GPU accessible?")
        sys.exit(1)

    # Get initial GPU info
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,power.limit",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        logger.info("GPU Info: %s", result.stdout.strip())

    # Default prompts file path
    default_prompts_file = script_dir / "gpu-power-bench-prompts.json"

    # Determine which prompts file to use
    prompts_file_to_use = args.prompts_file if args.prompts_file else str(default_prompts_file)

    # Load prompts from file or use built-in
    if args.prompts_file or not default_prompts_file.exists():
        # Use explicitly provided file or fall back to built-in
        if args.prompts_file:
            prompts_file_path = Path(args.prompts_file)
            if not prompts_file_path.is_absolute():
                prompts_file_path = script_dir / prompts_file_path
            logger.info("Loading prompts from: %s", prompts_file_path)
            loaded_prompts = load_prompts_from_file(str(prompts_file_path))
            if loaded_prompts is not None:
                PROMPTS = loaded_prompts
            else:
                logger.error("Failed to load prompts, using built-in defaults")
        # else: use built-in PROMPTS
    elif default_prompts_file.exists():
        # Use the default prompts file
        logger.info("Loading prompts from: %s", default_prompts_file)
        loaded_prompts = load_prompts_from_file(str(default_prompts_file))
        if loaded_prompts is not None:
            PROMPTS = loaded_prompts
        else:
            logger.error("Failed to load prompts, using built-in defaults")

    # Apply cache-busting (unique timestamps per run)
    prompts_to_run = apply_cache_busting(PROMPTS, args.run_id)

    # Determine which prompts to run
    if args.prompts:
        selected_prompts = {}
        for key in args.prompts:
            if key in prompts_to_run:
                selected_prompts[key] = prompts_to_run[key]
            else:
                logger.warning("Unknown prompt key: %s", key)
        prompts_to_run = selected_prompts
    else:
        prompts_to_run = prompts_to_run

    logger.info("Running %d prompt(s): %s", len(prompts_to_run), list(prompts_to_run.keys()))
    logger.info("-" * 80)

    # Start power monitoring
    logger.info("[PWR] Starting power monitoring...")
    stop_event = start_power_monitoring(power_csv_path)

    # Run prompts
    results = []
    for key, prompt_data in prompts_to_run.items():
        logger.info("")
        logger.info(">>> PROMPT: %s - %s", key, prompt_data["title"])
        logger.info("Description: %s", prompt_data["description"])

        result = send_llm_request(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            messages=prompt_data["messages"],
            label=key,
            description=prompt_data["description"],
            log_path=log_path,
        )
        results.append(result)

        # Log result
        logger.info("  Status: %s", result["status"])
        logger.info("  Total time: %ss", result.get("total_time"))
        logger.info("  Response length: %d chars", result.get("response_length") or 0)
        logger.info("  Tokens generated: %s", result.get("tokens_generated"))

    # Stop power monitoring
    logger.info("")
    logger.info("-" * 80)
    logger.info("[PWR] Stopping power monitoring...")
    bench_end = time.time()
    power_summary = stop_power_monitoring(stop_event, power_csv_path)

    # Add power summary to results
    power_summary["status"] = "success"
    power_summary["model"] = args.model

    # Write results summary
    results_path = str(log_path).rsplit(".", 1)[0] + ".json"
    summary = {
        "bench_start": datetime.datetime.utcfromtimestamp(bench_end - sum(
            r.get("total_time", 0) + WARMUP_BEFORE + WARMUP_AFTER + POWER_SAMPLE_INTERVAL * 2
            for r in results
        )).isoformat() if results else datetime.datetime.utcnow().isoformat(),
        "bench_end": datetime.datetime.utcfromtimestamp(bench_end).isoformat(),
        "model": args.model,
        "api_key": args.api_key,
        "base_url": args.base_url,
        "power_summary": power_summary,
        "prompt_results": results,
    }

    with open(results_path, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("")
    logger.info("Results saved to:")
    logger.info("  Text Log: %s", log_path)
    logger.info("  Power CSV: %s", power_csv_path)
    logger.info("  JSON Summary: %s", results_path)
    logger.info("")
    logger.info("Power Summary:")
    for k, v in power_summary.items():
        logger.info("  %s: %s", k, v)
    logger.info("=" * 80)
    logger.info("BENCHMARK COMPLETE")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()