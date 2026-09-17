# deepjudge-legal-search

Small, secure HTTPS-ready JSON backend for DeepJudge legal search, designed for iPhone apps, Apple Shortcuts, and other mobile clients.

## What is included

- Your DeepJudge/API key stays on the server.
- The phone only talks to `POST /api/search`.
- Responses are normalized into clean iPhone-friendly fields like `title`, `text`, `url`, and `score`.
- Optional bearer-token auth protects the endpoint.
- Docker deployment files are included.
- The server can run behind any HTTPS host, or directly with a TLS cert/key.

## Deploy it

This repository includes `Dockerfile`, `.dockerignore`, `requirements.txt`, and `.env.example` so it can be deployed to a container-capable host.

Set these server-side environment variables in your hosting provider:

- `DEEPJUDGE_API_KEY` **required for search**
- `MOBILE_API_TOKEN` **strongly recommended**; use a long random value
- `DEEPJUDGE_SEARCH_URL` optional, defaults to `https://api.deepjudge.ai/v1/search`
- `DEEPJUDGE_API_KEY_HEADER` optional, defaults to `Authorization`
- `MOBILE_API_ALLOW_ORIGIN` optional, defaults to `*`
- `DEEPJUDGE_TIMEOUT_SECONDS` optional, defaults to `30`
- `PORT` optional, defaults to `8000`

Do not commit `.env` files or real API keys. The Docker ignore rules exclude them.

After deployment, verify:

```text
GET https://YOUR-DOMAIN/health
```

Then search with:

```bash
curl https://YOUR-DOMAIN/api/search \
  -H "X-API-Token: YOUR-MOBILE-TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"What cases discuss Miranda warnings?","top_k":3}'
```

## API endpoints

### `GET /health`

Returns:

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

Response fields include `ok`, `query`, `result_count`, `request_id`, and `results`. Individual results can include `id`, `title`, `text`, `url`, `score`, `source`, and `metadata`.

## Running locally

HTTP for local development:

```bash
export DEEPJUDGE_API_KEY=your-server-side-key
export MOBILE_API_TOKEN=choose-a-long-random-token
python mobile_api.py --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
docker build -t deepjudge-mobile-api .
docker run --rm -p 8000:8000 \
  -e DEEPJUDGE_API_KEY="$DEEPJUDGE_API_KEY" \
  -e MOBILE_API_TOKEN="$MOBILE_API_TOKEN" \
  deepjudge-mobile-api
```

Direct HTTPS with your own certificate:

```bash
export DEEPJUDGE_API_KEY=your-server-side-key
export MOBILE_API_TOKEN=choose-a-long-random-token
python mobile_api.py --host 0.0.0.0 --port 8443 --certfile /path/to/fullchain.pem --keyfile /path/to/privkey.pem
```

## iPhone / Apple Shortcuts

Use your deployed HTTPS URL as the API base. The iPhone app or Shortcut sends `X-API-Token` and never receives the upstream `DEEPJUDGE_API_KEY`.

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

let url = URL(string: "https://YOUR-DOMAIN/api/search")!
var request = URLRequest(url: url)
request.httpMethod = "POST"
request.setValue("YOUR-MOBILE-TOKEN", forHTTPHeaderField: "X-API-Token")
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
2. Set the URL to `https://YOUR-DOMAIN/api/search`.
3. Method: `POST`.
4. Headers: `X-API-Token` and `Content-Type: application/json`.
5. JSON body with `query` and `top_k`.
6. Read `results[0].title` or `results[0].text`.

## Authentication guidance

- Set a long random `MOBILE_API_TOKEN`.
- Send it in `X-API-Token` from the iPhone app.
- Rotate it if a device is lost.
- Keep the real `DEEPJUDGE_API_KEY` on the server only.
- For production, use your hosting provider's HTTPS endpoint rather than exposing plain HTTP to the internet.

## Tests

Run:

```bash
python -m unittest discover -s tests -v
```
