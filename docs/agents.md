# AI Agent Configuration Guide

This guide provides setup instructions for popular AI agents and clients that use the LiteLLM proxy API.

## Overview

The LiteLLM proxy provides an OpenAI-compatible API, which means it works with any tool that supports OpenAI's API format. This document covers configuration for various AI agents and development tools.

| Agent/Tool | API Model | Port | Purpose |
|------------|-----------|------|---------|
| Cline Code | `qwen3.6-35b-a3b`, `qwen3-coder-next`, `nemotron-super` | 4000 | VS Code AI assistant |
| Cursor IDE | `qwen3.6-35b-a3b`, `qwen3-coder-next`, `nemotron-super` | 4000 | AI-powered code editor |
| Continue | `qwen3.6-35b-a3b`, `qwen3-coder-next`, `nemotron-super` | 4000 | Open-source AI assistant |
| Codeium | `qwen3.6-35b-a3b`, `qwen3-coder-next`, `nemotron-super` | 4000 | AI coding assistant |
| OpenWebUI | Direct endpoint | 3000 | Web-based LLM interface |
| OpenAI SDK | `qwen3.6-35b-a3b`, `qwen3-coder-next`, `nemotron-super` | 4000 | Python/JavaScript clients |

> **Note:** The `anthropic/*` wildcard passthrough (added v1.4.0) now routes all Claude model requests directly to Anthropic's real API via the proxy, with a fallback to the local Qwen3.6 engine if the Anthropic API is unavailable. This replaces the older approach of using individual `claude-sonnet-4-6` / `claude-haiku-4-6` proxy aliases (removed in v1.3.0).

---

## Cline Code

Cline is a VS Code extension that acts as an AI programming assistant, allowing you to interact with AI models directly in your editor.

### Setup

1. **Install the Cline extension** in VS Code:
   - Open VS Code Extensions (`Ctrl+Shift+X`)
   - Search for "Cline" and install

2. **Configure Cline Settings**:
   - Open VS Code Settings (`Ctrl+,`)
   - Search for "cline"
   - Or edit `settings.json` directly:

```json
{
  "cline.modelConfig": {
    "model": "qwen3.6-35b-a3b",
    "apiBaseUrl": "http://localhost:4000/v1",
    "apiKey": "sk-your-litellm-master-key",
    "enableClineLogging": true
  }
}
```

3. **Restart VS Code** and test with `Ctrl+Shift+P` → "Cline: Ask Cline"

### Alternative Configuration (Environment Variables)

If you prefer environment variables, add to your shell profile:

```bash
# ~/.bashrc or ~/.zshrc
export CLINE_API_BASE_URL="http://localhost:4000/v1"
export CLINE_API_KEY="sk-your-litellm-master-key"
```

---

## Cursor IDE

Cursor is an AI-powered code editor built on VS Code with integrated LLM capabilities.

### Setup

1. **Open Cursor IDE**
2. **Go to Settings** (`Ctrl+,` on Windows/Linux, `Cmd+,` on macOS)
3. **Add the following configuration** to your `settings.json`:

```json
{
  "cursor.apiProvider": "openai",
  "cursor.openai.baseURL": "http://localhost:4000/v1",
  "cursor.openai.apiKey": "sk-your-litellm-master-key",
  "cursor.model": "qwen3.6-35b-a3b",
  "cursor.autoSuggestEnabled": true
}
```

4. **Restart Cursor** to apply changes

### Using Cursor with Different Models

Cursor allows switching models via the status bar or commands:

| Model | API Model Name | Use Case |
|-------|---------------|----------|
| Main | `qwen3.6-35b-a3b` | Complex coding tasks |
| Nemotron | `nemotron-super` | Reasoning tasks |

---

## Continue

Continue is an open-source AI coding assistant that integrates with VS Code.

### Setup

1. **Install Continue extension**:
   - Open VS Code Extensions
   - Search for "Continue" and install

2. **Configure Continue**:
   - Open `~/.continue/config.py` (create if it doesn't exist)

```python
from continue_chainlit import *

# Configure the proxy
configure(
    model="qwen3.6-35b-a3b",
    api_base="http://localhost:4000/v1",
    api_key="sk-your-litellm-master-key"
)
```

3. **Alternative: Use UI Configuration**
   - Open Continue sidebar in VS Code
   - Click "Settings" (gear icon)
   - Enter:
     - **API Base URL**: `http://localhost:4000/v1`
     - **API Key**: `sk-your-litellm-master-key`
     - **Model**: `qwen3.6-35b-a3b`

---

## Codeium

Codeium is an AI-powered coding assistant with support for multiple IDEs.

### Setup for VS Code

1. **Install Codeium extension**:
   - Open VS Code Extensions
   - Search for "Codeium" and install

2. **Configure Codeium**:
   - Open VS Code Settings (`Ctrl+,`)
   - Search for "codeium"
   - Or edit `settings.json`:

```json
{
  "codeium.enableGeneralChat": true,
  "codeium.enableExperiments": false,
  "codeium.disableTelemetry": true
}
```

3. **Optional: Link to Account**
   - Sign in to your Codeium account for syncing settings
   - Or use the proxy mode with custom API endpoint

### Using Codeium with LiteLLM Proxy

Codeium supports custom API endpoints. In your settings:

```json
{
  "codeium.apiKey": "sk-your-litellm-master-key",
  "codeium.apiEndpoint": "http://localhost:4000/v1/chat/completions"
}
```

---

## OpenAI SDK (Python)

For programmatic access using OpenAI's official Python SDK.

### Installation

```bash
pip install openai
```

### Basic Usage

```python
from openai import OpenAI

# Initialize client
client = OpenAI(
    base_url="http://localhost:4000/v1",
    api_key="sk-your-litellm-master-key"
)

# Qwen3.6-35B-A3B-NVFP4 (default)
response = client.chat.completions.create(
    model="qwen3.6-35b-a3b",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Write a Python function to sort a list."}
    ],
    temperature=0.7
)

print(response.choices[0].message.content)

# Qwen3-Coder-Next-FP8
response = client.chat.completions.create(
    model="qwen3-coder-next",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Write a Python function to sort a list."}
    ],
    temperature=0.7
)

# Using Nemotron-3-Super-120B for reasoning tasks
response = client.chat.completions.create(
    model="nemotron-super",
    messages=[
        {"role": "user", "content": "Explain quantum entanglement."}
    ]
)
```

### Streaming Responses

```python
stream = client.chat.completions.create(
    model="nemotron-super",
    messages=[
        {"role": "user", "content": "Write a story about AI."}
    ],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

---

## OpenAI SDK (JavaScript/Node.js)

### Installation

```bash
npm install openai
```

### Basic Usage

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:4000/v1',
  apiKey: 'sk-your-litellm-master-key'
});

// Qwen3.6-35B-A3B-NVFP4 (default)
const response = await client.chat.completions.create({
  model: 'qwen3.6-35b-a3b',
  messages: [
    { role: 'system', content: 'You are a helpful assistant.' },
    { role: 'user', content: 'Write a JavaScript function to sort an array.' }
  ],
  temperature: 0.7
});

console.log(response.choices[0].message.content);

// Qwen3-Coder-Next-FP8
const response2 = await client.chat.completions.create({
  model: 'qwen3-coder-next',
  messages: [
    { role: 'system', content: 'You are a helpful assistant.' },
    { role: 'user', content: 'Write a JavaScript function to sort an array.' }
  ],
  temperature: 0.7
});

// Using Nemotron-3-Super-120B for reasoning tasks
const response3 = await client.chat.completions.create({
  model: 'nemotron-super',
  messages: [
    { role: 'user', content: 'Explain neural networks.' }
  ]
});
```

---

## OpenWebUI

OpenWebUI is a self-hosted web interface for interacting with LLMs.

### Setup

1. **Access OpenWebUI** at `http://localhost:3000`

2. **Configure API Settings**:
   - Click on the settings icon (gear)
   - Go to "General" tab
   - Set:
     - **OpenAI API Base URL**: `http://localhost:4000/v1`
     - **OpenAI API Key**: `sk-your-litellm-master-key`

3. **Select Model**:
   - Choose `qwen3.6-35b-a3b` for main tasks
   - Choose `qwen3-coder-next` for coding tasks
   - Choose `nemotron-super` for reasoning tasks

---

## Model Reference

### Available Model Names

| Model Name | Purpose | Backend Model |
|------------|---------|---------------|
| `qwen3.6-35b-a3b` | Direct access to Qwen3.6 model | Qwen3.6-35B-A3B-NVFP4 |
| `qwen3-coder-next` | Direct access to Qwen3-Coder model | Qwen3-Coder-Next-FP8 |
| `nemotron-super` | Direct access to Nemotron model | Nemotron-3-Super-120B |
| `nemotron-3-embed-1b-nvfp4` | Text embeddings (2048-dim, NVFP4) | Embedding engine |

### Using Different Models in Your Code

```python
# Python - Switch between models
models = {
    'main': 'qwen3.6-35b-a3b',
    'qwen': 'qwen3-coder-next',
    'nemotron': 'nemotron-super',
    'embed': 'nemotron-3-embed-1b-nvfp4'
}

response = client.chat.completions.create(
    model=models['main'],  # or models['qwen'], models['nemotron'], etc.
    messages=[...]
)
```

---

## Testing Your Setup

### Test API Connection

```bash
# Test with curl (Qwen3.6-35B-A3B-NVFP4)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-litellm-master-key" \
  -d '{
    "model": "qwen3.6-35b-a3b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Test with curl (Qwen3-Coder-Next-FP8)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-litellm-master-key" \
  -d '{
    "model": "qwen3-coder-next",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Test embedding
curl http://localhost:4000/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-litellm-master-key" \
  -d '{
    "model": "nemotron-3-embed-1b-nvfp4",
    "input": "query: Hello world"
  }'
```

### Test Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:4000/v1",
    api_key="sk-your-litellm-master-key"
)

# Simple health check (Qwen3.6-35B-A3B-NVFP4)
try:
    response = client.chat.completions.create(
        model="qwen3.6-35b-a3b",
        messages=[{"role": "user", "content": "Say 'hello'"}],
        max_tokens=10
    )
    print("✓ API connection successful!")
    print(f"Response: {response.choices[0].message.content}")
except Exception as e:
    print(f"✗ Connection failed: {e}")
```

---

## Troubleshooting

### Common Issues

**1. Connection Refused**
- Ensure LiteLLM proxy is running: `docker compose ps`
- Check port 4000 is accessible: `curl http://localhost:4000/v1/models`

**2. Invalid API Key**
- Verify `LITELLM_MASTER_KEY` in `.env` matches your configuration
- Restart containers after changing environment variables

**3. Model Not Found**
- Check available models: `curl http://localhost:4000/v1/models`
- Ensure the model name is in the list

**4. Slow Responses**
- Check vLLM engine logs: `docker compose logs qwen3-6-35b-nvfp4-engine`
- Verify GPU is not out of memory: `nvidia-smi`