# LLM Integration Guide — Portal Context Generator

> This guide explains how to connect **any** LLM API to the Portal Context Generator,
> even if it's not OpenAI-compatible.

---

## Overview: What the Tool Expects from an LLM

The Portal Context Generator sends text prompts to an LLM and receives text responses. That's it. Internally, it uses the `LLMProvider` interface:

```python
class LLMProvider:
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Send a prompt, get a text response."""
        ...
```

The tool supports **three provider types** out of the box:

| Provider | Config Value | For |
|----------|-------------|-----|
| `gemini` | `LLM_PROVIDER=gemini` | Google Gemini API (free tier) |
| `openai` | `LLM_PROVIDER=openai` | Any OpenAI-compatible endpoint (vLLM, Ollama, LM Studio, etc.) |
| `custom` | `LLM_PROVIDER=custom` | **Your custom LLM API** — any simple POST endpoint |

---

## Option 1: Your LLM is Already OpenAI-Compatible

If your LLM server exposes an endpoint at `/v1/chat/completions` that accepts this format:

```http
POST http://your-llm-host:8080/v1/chat/completions
Content-Type: application/json

{
    "model": "your-model-name",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Describe this portal page..."}
    ]
}
```

And responds with:

```json
{
    "choices": [
        {
            "message": {
                "content": "This portal page allows users to..."
            }
        }
    ]
}
```

Then you're already compatible. Configure:

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://your-llm-host:8080/v1
LLM_API_KEY=your-api-key        # Use any string if your server doesn't require auth
LLM_MODEL=your-model-name
```

**No code changes needed.**

---

## Option 2: Your LLM Has a Simple Custom API

This is the most common case for internal LLMs. Your API is a simple POST endpoint with custom field names.

### Step 1: Identify Your API Shape

Your LLM API probably looks something like this:

```http
POST http://your-llm-host:5000/generate
Content-Type: application/json

{
    "input": "Describe this portal page..."
}
```

Response:

```json
{
    "output": "This portal page allows users to..."
}
```

Or maybe it looks like this:

```http
POST http://your-llm-host:5000/api/chat
Content-Type: application/json

{
    "prompt": "Describe this portal page...",
    "max_tokens": 2000
}
```

Response:

```json
{
    "response": "This portal page allows users to...",
    "tokens_used": 150
}
```

### Step 2: Map Your Fields

You need to identify **two things**:

1. **Request field name**: What key does your API expect the prompt text in? (e.g., `input`, `prompt`, `query`, `text`, `message`)
2. **Response field name**: What key does the response contain the output in? (e.g., `output`, `response`, `result`, `text`, `generated_text`)

### Step 3: Configure

```env
LLM_PROVIDER=custom
LLM_BASE_URL=http://your-llm-host:5000/generate
LLM_REQUEST_FIELD=input
LLM_RESPONSE_FIELD=output
LLM_API_KEY=your-key             # Leave empty or set to "none" if no auth needed
```

That's it. The tool's `CustomAPIProvider` will:
1. Build a JSON body: `{"{your_request_field}": "{prompt_text}"}`
2. POST it to your `LLM_BASE_URL`
3. Parse the response JSON and extract `response["{your_response_field}"]`

### How It Works Internally

```python
class CustomAPIProvider(LLMProvider):
    """Supports any simple POST-based LLM API."""
    
    def __init__(self, base_url: str, request_field: str = "input",
                 response_field: str = "output", api_key: str = "",
                 extra_params: dict = None):
        self.base_url = base_url
        self.request_field = request_field
        self.response_field = response_field
        self.api_key = api_key
        self.extra_params = extra_params or {}  # Additional fixed params to send

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        # Combine system prompt and user prompt
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        # Build request body
        body = {self.request_field: full_prompt}
        body.update(self.extra_params)  # Add any extra params like max_tokens
        
        # Set headers
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        # Make the call
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(self.base_url, json=body, headers=headers)
            response.raise_for_status()
            result = response.json()
        
        # Extract the output
        return result[self.response_field]
```

---

## Option 3: Your API is More Complex (Adapter Wrapper)

If your LLM API has a non-trivial request/response format — for example:
- Requires specific authentication (not just Bearer token)
- Has nested request body structure
- Needs session management
- Returns streaming responses
- Has a multi-step API (create → poll → get result)

Then you can create a **thin adapter wrapper** — a small Python script that sits between the Portal Context Generator and your LLM, translating requests.

### Step 1: Create the Adapter Script

Create a file `llm_adapter.py` in the project root:

```python
"""
LLM Adapter — Translates standard requests to your custom LLM API.

This script runs a small HTTP server that:
1. Receives requests in the simple format: {"input": "..."}
2. Translates them to your LLM's expected format
3. Calls your LLM
4. Returns the response in simple format: {"output": "..."}

Usage:
    python llm_adapter.py --port 8888 --llm-url http://your-actual-llm:5000
"""

import argparse
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request


class AdapterHandler(BaseHTTPRequestHandler):
    """Translates between the tool's format and your LLM's format."""
    
    def do_POST(self):
        # Read incoming request
        content_length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(content_length)
        incoming = json.loads(raw_body)
        
        prompt = incoming.get("input", "")
        
        # ==========================================
        # CUSTOMIZE THIS SECTION FOR YOUR LLM API
        # ==========================================
        
        # Example 1: Simple field name mapping
        # your_request = {"prompt": prompt, "temperature": 0.3}
        
        # Example 2: Nested structure
        # your_request = {
        #     "params": {
        #         "text": prompt,
        #         "config": {"max_tokens": 4000, "temperature": 0.2}
        #     },
        #     "session_id": "portal-context"
        # }
        
        # Example 3: With special auth
        # your_request = {
        #     "auth_token": "YOUR_INTERNAL_TOKEN",
        #     "payload": {"query": prompt}
        # }
        
        # Default: pass through as-is
        your_request = {"input": prompt}
        
        # ==========================================
        # MAKE THE CALL TO YOUR ACTUAL LLM
        # ==========================================
        
        llm_url = self.server.llm_url
        
        req = urllib.request.Request(
            llm_url,
            data=json.dumps(your_request).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                # Add your custom auth headers here:
                # 'X-API-Key': 'your-key',
                # 'Authorization': 'Custom your-token',
            },
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=120) as resp:
            llm_response = json.loads(resp.read())
        
        # ==========================================
        # CUSTOMIZE: EXTRACT THE OUTPUT TEXT
        # ==========================================
        
        # Example 1: Simple field
        # output_text = llm_response["response"]
        
        # Example 2: Nested
        # output_text = llm_response["result"]["generated_text"]
        
        # Example 3: Array
        # output_text = llm_response["outputs"][0]["text"]
        
        # Default
        output_text = llm_response.get("output", str(llm_response))
        
        # ==========================================
        # SEND BACK IN STANDARD FORMAT
        # ==========================================
        
        response_body = json.dumps({"output": output_text})
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(response_body.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def main():
    parser = argparse.ArgumentParser(description='LLM Adapter for Portal Context Generator')
    parser.add_argument('--port', type=int, default=8888, help='Port to listen on')
    parser.add_argument('--llm-url', required=True, help='Your actual LLM endpoint URL')
    args = parser.parse_args()
    
    server = HTTPServer(('0.0.0.0', args.port), AdapterHandler)
    server.llm_url = args.llm_url
    
    print(f"LLM Adapter running on http://localhost:{args.port}")
    print(f"Forwarding to: {args.llm_url}")
    print(f"Configure Portal Context Generator with:")
    print(f"  LLM_PROVIDER=custom")
    print(f"  LLM_BASE_URL=http://localhost:{args.port}")
    print(f"  LLM_REQUEST_FIELD=input")
    print(f"  LLM_RESPONSE_FIELD=output")
    
    server.serve_forever()


if __name__ == "__main__":
    main()
```

### Step 2: Run the Adapter

```bash
# Terminal 1: Start the adapter
python llm_adapter.py --port 8888 --llm-url http://your-actual-llm:5000/api/generate

# Terminal 2: Run the Portal Context Generator
python cli.py --url https://portal.internal.com \
  --provider custom \
  --llm-url http://localhost:8888 \
  --request-field input \
  --response-field output
```

### Step 3: Customize the Adapter

Edit the three `CUSTOMIZE` sections in `llm_adapter.py`:

1. **Request building**: Transform the prompt into your LLM's expected format
2. **Auth headers**: Add any custom authentication your LLM requires
3. **Response extraction**: Pull the generated text out of your LLM's response format

---

## Option 4: Make Your LLM OpenAI-Compatible (Server-Side)

If you control the LLM server, you can add an OpenAI-compatible endpoint alongside your existing API. This is a small wrapper route.

### Flask Example

```python
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

YOUR_LLM_URL = "http://localhost:5000/generate"  # Your existing endpoint

@app.route('/v1/chat/completions', methods=['POST'])
def openai_compatible():
    """OpenAI-compatible wrapper for your LLM."""
    data = request.json
    
    # Extract the prompt from OpenAI format
    messages = data.get("messages", [])
    prompt = "\n".join([
        f"{msg['role']}: {msg['content']}" 
        for msg in messages
    ])
    
    # Call your actual LLM
    response = requests.post(YOUR_LLM_URL, json={
        "input": prompt  # Your LLM's expected field
    })
    llm_result = response.json()
    
    # Return in OpenAI format
    return jsonify({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": llm_result["output"]  # Your LLM's response field
            },
            "finish_reason": "stop"
        }],
        "model": data.get("model", "local"),
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    })

if __name__ == "__main__":
    app.run(port=8080)
```

Then configure:

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:8080/v1
LLM_API_KEY=not-needed
LLM_MODEL=local
```

### FastAPI Example

```python
from fastapi import FastAPI
from pydantic import BaseModel
import httpx

app = FastAPI()

YOUR_LLM_URL = "http://localhost:5000/generate"

class ChatRequest(BaseModel):
    model: str = "local"
    messages: list[dict]

@app.post("/v1/chat/completions")
async def openai_compatible(req: ChatRequest):
    prompt = "\n".join([
        f"{msg['role']}: {msg['content']}" 
        for msg in req.messages
    ])
    
    async with httpx.AsyncClient() as client:
        response = await client.post(YOUR_LLM_URL, json={"input": prompt})
        llm_result = response.json()
    
    return {
        "choices": [{
            "message": {
                "role": "assistant", 
                "content": llm_result["output"]
            },
            "finish_reason": "stop"
        }],
        "model": req.model,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }
```

---

## Quick Reference: Which Option to Use?

```
Is your LLM OpenAI-compatible? (/v1/chat/completions)
├── YES → Use LLM_PROVIDER=openai (Option 1)
└── NO
    ├── Is it a simple POST with input/output fields?
    │   ├── YES → Use LLM_PROVIDER=custom (Option 2)
    │   └── NO (complex auth, nested body, streaming, etc.)
    │       ├── Can you modify the LLM server?
    │       │   ├── YES → Add OpenAI-compatible route (Option 4)
    │       │   └── NO → Use the Adapter Wrapper (Option 3)
    └──────────────────────────────────────────────────
```

---

## Common API Patterns and Their Config

### Pattern A: `{"prompt": "..."} → {"response": "..."}`
```env
LLM_PROVIDER=custom
LLM_BASE_URL=http://llm:5000/generate
LLM_REQUEST_FIELD=prompt
LLM_RESPONSE_FIELD=response
```

### Pattern B: `{"text": "..."} → {"generated_text": "..."}`
```env
LLM_PROVIDER=custom
LLM_BASE_URL=http://llm:5000/api/generate
LLM_REQUEST_FIELD=text
LLM_RESPONSE_FIELD=generated_text
```

### Pattern C: `{"input": "..."} → {"output": "..."}`
```env
LLM_PROVIDER=custom
LLM_BASE_URL=http://llm:5000/predict
LLM_REQUEST_FIELD=input
LLM_RESPONSE_FIELD=output
```

### Pattern D: `{"query": "..."} → {"result": "..."}`
```env
LLM_PROVIDER=custom
LLM_BASE_URL=http://llm:5000/inference
LLM_REQUEST_FIELD=query
LLM_RESPONSE_FIELD=result
```

---

## Testing Your LLM Connection

Before running the full Portal Context Generator, test that your LLM is reachable:

```bash
# Activate your venv first
.\\venv\\Scripts\\Activate.ps1

# Test with curl (or Invoke-WebRequest on PowerShell)
curl -X POST http://your-llm:5000/generate \
  -H "Content-Type: application/json" \
  -d '{"input": "Say hello in one word"}'

# Expected: {"output": "Hello"} (or similar)
```

Or use the built-in test command:

```bash
python cli.py test-llm --provider custom \
  --llm-url http://your-llm:5000/generate \
  --request-field input \
  --response-field output
```

This sends a simple test prompt and verifies the response is valid.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Connection refused` | Ensure your LLM server is running and reachable from the machine running the tool |
| `Timeout` | Increase timeout in config; LLMs can be slow for long prompts |
| `401 Unauthorized` | Check `LLM_API_KEY` or adapter auth headers |
| `JSON parse error` | Your LLM may be returning non-JSON; check with curl first |
| `Wrong field name` | Verify `LLM_REQUEST_FIELD` and `LLM_RESPONSE_FIELD` match your API |
| `Empty response` | Check that `LLM_RESPONSE_FIELD` points to the correct key in the response JSON |
