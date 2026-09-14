# deepjudge-legal-search

Small, secure HTTPS-ready JSON backend for DeepJudge legal search, designed for iPhone apps, Apple Shortcuts, and other mobile clients.

## Install

```bash
python -m pip install .
```

This installs the `deepjudge-legal-search` package and the `deepjudge-mobile-api` command.

After installing, run the server with:

```bash
deepjudge-mobile-api --host 0.0.0.0 --port 8000
```

## Why this repo now works well for iPhone apps

- Your DeepJudge/API key stays on the server.
- The phone only talks to a small JSON API: `POST /api/search`.
- Responses are normalized into clean iPhone-friendly fields like `title`, `text`, `url`, and `score`.
- Optional bearer-token auth gives you a lightweight way to protect the endpoint.
- The server can run behind any HTTPS host, or directly with a TLS cert/key.

## API endpoints

### `GET /health`

Returns a simple health check:

```json
{
  "status": "ok",
  "service": "deepjudge-mobile-api"
}
```

### `POST /api/search`

Request body:

```json
{
  "query": "what cases discuss Miranda warnings?",
  "top_k": 3,
  "filters": {
    "jurisdiction": "us"
  }
}
```

Supported `filters` keys: `jurisdiction`, `court`, `date_from`, `date_to`, `practice_area`, and `document_type`. Filter values should be strings, numbers, booleans, or flat lists of those values.

Response body:

```json
{
  "ok": true,
  "query": "what cases discuss Miranda warnings?",
  "result_count": 1,
  "request_id": "req_123",
  "results": [
    {
      "id": "doc-1",
      "title": "Miranda v. Arizona",
      "text": "Key holding summary...",
      "url": "https://example.com/cases/miranda",
      "score": 0.98,
      "source": "Supreme Court"
    }
  ]
}
```

## Configuration

Set these environment variables before starting the server:

- `DEEPJUDGE_API_KEY` **required for search**
- `DEEPJUDGE_SEARCH_URL` optional, defaults to `https://api.deepjudge.ai/v1/search`
- `DEEPJUDGE_API_KEY_HEADER` optional, defaults to `Authorization`
- `MOBILE_API_TOKEN` optional but recommended; if set, clients should send it in the `X-API-Token` request header
- `MOBILE_API_ALLOW_ORIGIN` optional CORS header, defaults to `*`
- `DEEPJUDGE_TIMEOUT_SECONDS` optional, defaults to `30`
- `TLS_CERTFILE` and `TLS_KEYFILE` optional for direct HTTPS

## Running locally

HTTP for local development:

```bash
python -m pip install .
export DEEPJUDGE_API_KEY=your-server-side-key
export MOBILE_API_TOKEN=choose-a-long-random-token
deepjudge-mobile-api --host 0.0.0.0 --port 8000
```

Direct HTTPS with your own certificate:

```bash
python -m pip install .
export DEEPJUDGE_API_KEY=your-server-side-key
export MOBILE_API_TOKEN=choose-a-long-random-token
deepjudge-mobile-api --host 0.0.0.0 --port 8443 --certfile /path/to/fullchain.pem --keyfile /path/to/privkey.pem
```

For production, the simplest option is to deploy this behind HTTPS on a small VPS, Fly.io, Render, Railway, Cloud Run, or behind Nginx/Caddy.

## Example request from iPhone-compatible clients

`curl`:

```bash
curl https://your-domain.example/api/search \
  -H "X-API-Token: your-mobile-token" \
  -H "Content-Type: application/json" \
  -d '{"query":"What cases discuss Miranda warnings?","top_k":3}'
```

### Swift example

```swift
import Foundation

struct SearchResponse: Decodable {
    struct SearchResult: Decodable {
        let id: String?
        let title: String?
        let text: String?
        let url: String?
        let score: Double?
        let source: String?
    }

    let ok: Bool
    let query: String
    let resultCount: Int
    let requestId: String
    let results: [SearchResult]

    private enum CodingKeys: String, CodingKey {
        case ok, query, results
        case resultCount = "result_count"
        case requestId = "request_id"
    }
}

let url = URL(string: "https://your-domain.example/api/search")!
var request = URLRequest(url: url)
request.httpMethod = "POST"
request.setValue("your-mobile-token", forHTTPHeaderField: "X-API-Token")
request.setValue("application/json", forHTTPHeaderField: "Content-Type")
request.httpBody = try JSONSerialization.data(withJSONObject: [
    "query": "What cases discuss Miranda warnings?",
    "top_k": 3
])

URLSession.shared.dataTask(with: request) { data, response, error in
    guard let data else { return }
    let decoded = try? JSONDecoder().decode(SearchResponse.self, from: data)
    print(decoded?.results.first?.title ?? "No result")
}.resume()
```

### Apple Shortcuts flow

1. Add **Get Contents of URL**.
2. Set URL to `https://your-domain.example/api/search`.
3. Method: `POST`.
4. Headers:
   - `X-API-Token` → `your-mobile-token`
   - `Content-Type` → `application/json`
5. JSON body:

```json
{
  "query": "What cases discuss Miranda warnings?",
  "top_k": 3
}
```

6. Read `results[0].title` or `results[0].text` in the next Shortcut step.

## Authentication guidance

If you already have stronger auth infrastructure, place this endpoint behind it. Otherwise:

- set a long random `MOBILE_API_TOKEN`
- send it in the `X-API-Token` header from the iPhone app
- rotate it if a device is lost
- keep the real `DEEPJUDGE_API_KEY` on the server only

This gives you a lightweight, mobile-friendly setup without exposing upstream credentials to the app. The server also accepts bearer tokens if you prefer that style.

## Tests

Run:

```bash
python -m unittest discover -s tests -v
```
