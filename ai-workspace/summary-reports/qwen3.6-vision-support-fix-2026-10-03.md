# Qwen3.6 Vision Support Fix — Summary Report

**Date:** 2026-10-03
**Branch:** `fix/qwen3.6-litellm-vision-support` (branched off `origin/main`, `4aaa2b6`)

---

## Symptom

When asked to review an image file, `qwen3.6-35b-a3b` replied that it doesn't support vision. That contradicts
the Hugging Face model card and the vLLM recipe, which both list the model as vision-capable.

---

## Root cause

`litellm-config.yaml` declared the model as not vision-capable:

```yaml
  - model_name: qwen3.6-35b-a3b
    model_info:
      supports_vision: false
```

Clients that read LiteLLM's `/model/info` (Cline, OpenCode, Claude Code) check this flag. When it's `false`,
they leave the image out of the request, so the model only ever sees text and says it can't view images.

The vLLM engine side was correct the whole time:

| Check | Result |
|-------|--------|
| Checkpoint `config.json` (`nvidia/Qwen3.6-35B-A3B-NVFP4`, local HF cache) | `architectures: Qwen3_5MoeForConditionalGeneration`, has `vision_config`, `image_token_id: 248056` |
| `docker-compose.qwen3.6.yml` vLLM command | `--mm-encoder-tp-mode data` set; no `--language-model-only`, no `--limit-mm-per-prompt` of 0 |

### How it got that way

v1.2.0 served `Qwen3.6-27B-FP8` with vision turned on in LiteLLM. In v1.3.0 that model was replaced by
`Qwen3.6-35B-A3B-NVFP4`, and the CHANGELOG recorded the new checkpoint as "text-only; `supports_vision: false`"
without checking its config. That claim was then repeated across the docs, which is why it looked settled.

---

## Changes

| File | Change |
|------|--------|
| `litellm-config.yaml` | `qwen3.6-35b-a3b`: `supports_vision: false` → `true`, with a comment giving the reason |
| `docs/models.md` | Replaced "Text-Only" with "Vision-capable"; comparison table Vision ❌ → ✅; removed "the only stack of the two with a vision encoder" claims for qwen3.8 |
| `docs/architecture.md` | qwen3.6 Vision Support: No → Yes; architecture line now mentions the vision encoder |
| `docs/troubleshooting.md` | Corrected an explanation that relied on qwen3.6 being text-only |
| `docker-compose.qwen3.8.yml` | Same correction in a header comment. No functional change |
| `scripts/restart.sh`, `scripts/model-switch.sh` | Help text "text-only" → "vision-capable" |
| `CLAUDE.md` | Alias table notes qwen3.6 is vision-capable |
| `CHANGELOG.md` | New `[Unreleased] → Fixed` entry. Older entries are left as written |

`docker-compose.qwen3.6.yml` was not modified.

---

## Verification

1. **LiteLLM restarted** (`docker restart litellm-proxy`). The vLLM engine was not touched.
   `/model/info` now reports `supports_vision: true` for both `qwen3.6-35b-a3b` and `qwen3.8-27b`.
2. **Image round trip through LiteLLM.** The test image was a generated 512×320 PNG with a red circle on the
   left, a blue square on the right and a green bar along the bottom. It was sent to the running engine
   (`qwen3.8-27b`, since that is the stack currently up) through both APIs:

   | Endpoint | Prompt tokens | Answer |
   |----------|---------------|--------|
   | `POST /v1/chat/completions` (OpenAI `image_url`) | 234 | Red circle – left; Blue square – right; Green rectangle – bottom |
   | `POST /v1/messages` (Anthropic `image` block) | 234 | Red circle: left; Blue square: right; Green rectangle: bottom |

   Both answers are correct. This shows LiteLLM passes images to the vLLM engine on both APIs.

### Not yet verified

- **qwen3.6 itself, end to end.** Its engine (`qwen3-6-35b-nvfp4-engine`) wasn't running during this fix. A
  request to `qwen3.6-35b-a3b` would currently fail over to `qwen3.8-27b` through `default_fallbacks`, so it
  wouldn't test qwen3.6. To check, bring up the rollback stack (`./scripts/model-switch.sh qwen3.6`) and repeat
  the request with `"model": "qwen3.6-35b-a3b"`, or send it directly to `localhost:8301`.
- **Client behavior after the flag change.** Cline, OpenCode and Claude Code may cache model info. Restart the
  client before retesting with an image.
