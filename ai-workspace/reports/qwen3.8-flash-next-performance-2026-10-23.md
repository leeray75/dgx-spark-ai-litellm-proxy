# Qwen3.8-Flash-Next performance and cost report — 2026-10-23

Engine `qwen3-8-flash-next-fp4-engine` (served name `qwen3.8-flash-next`), port 8301, `--gpu-memory-utilization 0.75`,
`--max-num-seqs 8`, MTP speculative decoding (4 tokens). Engine started 2026-10-22T23:06:34Z.

Sources: vLLM engine logs (`llm-throughput-check`), `~/power-logs` (`llm-power-cost`, $0.298/kWh, GPU-only draw),
agentgateway request logs, Langfuse (ClickHouse, read-only), vLLM `/metrics`.

## Summary

- **Price update: not needed.** Over the multi-subagent run Langfuse recorded $0.00623 against $0.00664 measured
  (−6%); over the whole engine lifetime $0.00917 against $0.00965 (−5%). The current prices (input 3.19e-11,
  output 8.69e-8) stay.
- **Single-stream decode ≈ 43 tok/s**; two concurrent requests ≈ 50 tok/s combined (25 each).
- **No errors, no preemption, no aborts.** 90 requests finished (89 `stop`, 1 `length` — an 8-token test).
- **Plenty of headroom at 0.75:** KV cache peaked at 42.8 %; queue never exceeded 2.
- **Prefix cache hit rate 91.5 %** (5.47M of 5.98M input tokens).

## Workloads

| Window (UTC) | Workload | Requests | Input tokens | Output tokens | Peak concurrency |
|---|---|---|---|---|---|
| 23:22:29 – 23:28:45 | Goose task (single agent) | 18 | 1.47M | 14.6k | 1 |
| 23:36:00 – 00:12:31 | Multiple subagents | 69 (66 agentgateway + 3 LiteLLM) | 4.51M | 70.1k | 3 |
| 23:06:34 – 00:13:22 | Engine lifetime | 90 | 5.98M | 84.7k | 3 |

## Throughput (subagent run, vLLM 10 s log samples while generating)

| Metric | Median | Mean |
|---|---|---|
| Generation (aggregate) | 42.0 tok/s | 42.5 tok/s |
| KV cache usage | 17.4 % (peak 42.8 %) | 17.6 % |
| Waiting requests | 0 (peak 2) | 0.03 |
| MTP draft acceptance | 45.5 % | 49.2 % |

By concurrency:

| Requests running | Samples | Aggregate tok/s | Per request tok/s |
|---|---|---|---|
| 1 | 130 | 43.3 | 43.3 |
| 2 | 15 | 50.2 | 25.1 |
| 3 | 6 | 22.4 | 7.5 |

The 3-concurrent row is not steady-state decode: those intervals coincided with large prefills (input counter rose
by ~2M tokens over 23:55–23:59), which share the `--max-num-batched-tokens 4096` budget with decode. Six samples
is too few to say what three concurrent decoders sustain.

Request latency (agentgateway, 66 requests):

| | Median | p90 | Max |
|---|---|---|---|
| Time to first token | 1.4 s | 12.5 s | 57.4 s |
| Request duration | 6.6 s | — | 460.5 s |
| Input tokens per request | 61k | — | 157k |

Long TTFTs are fresh (uncached) prefills of large contexts while other requests were running.

## Energy and cost (GPU only)

| | Goose task | Subagent run | Engine lifetime |
|---|---|---|---|
| Decode intervals | 57 | 266 | 323 |
| Decode speed / power | 41.6 tok/s @ 43.7 W | 45.9 tok/s @ 42.8 W | 45.2 tok/s @ 43.0 W |
| J per output token | 1.05 | 0.93 | 0.95 |
| Energy total (above idle) | 4.49 Wh (2.94) | 22.27 Wh (14.28) | 32.39 Wh (18.26) |
| Cost total (above idle) | $0.00134 ($0.00088) | $0.00664 ($0.00426) | $0.00965 ($0.00544) |
| Langfuse recorded | $0.00285* | $0.00623 | $0.00917 |
| Suggested output / input price | 8.69e-8 / 3.19e-11 | 7.71e-8 / 2.39e-11 | 7.87e-8 / 2.99e-11 |

\* recorded under the earlier provisional prices (1.26e-9 / 7.42e-8); see CHANGELOG.

Idle baseline 12.9–14.8 W ≈ $0.09–0.11/day.

### Price decision

The lifetime sample (323 decode intervals, 84.7k output tokens) is the first to clear the provisional bar
(30 intervals / 20k tokens). It suggests 7.87e-8 output, 9 % below the current 8.69e-8. Not changed, because:

- Langfuse already lands within 5–6 % of the measured total energy cost.
- J/token varies with workload (0.93 with light batching, 1.05 single-agent); the current price sits inside that
  range, and batching benefits are not guaranteed for future use.

Revisit if a day of mixed use moves the lifetime figure outside 0.90–1.05 J/token.

## Caveats

- GPU power only (nvidia-smi); CPU, memory, SSD and fans are not included.
- Input token counts are inflated by agent context resent each turn (91.5 % prefix-cache hits); they are not a
  measure of fresh prefill work.
- One evening of use, peak concurrency 3. Behaviour at 4–8 concurrent agents is untested.
