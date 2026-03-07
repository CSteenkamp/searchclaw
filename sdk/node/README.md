# SearchClaw Node.js SDK

TypeScript/JavaScript client for the [SearchClaw](https://searchclaw.dev) search API — cheap, fast web search for AI agents.

## Installation

```bash
npm install searchclaw
```

## Quick Start

```typescript
import { SearchClaw } from 'searchclaw';

const client = new SearchClaw({ apiKey: 'sc_live_xxx' });

// Web search
const results = await client.search('kubernetes pod restart policy');
results.results.forEach(r => console.log(r.title, r.url));

// News search
const news = await client.news('openai', { freshness: 'week' });

// Image search
const images = await client.images('cute cats', { count: 5 });

// Autocomplete suggestions
const suggestions = await client.suggest('kube');

// AI-optimized search (2 credits, returns RAG-ready context)
const ai = await client.aiSearch('what is kubernetes');
console.log(ai.context);

// Check usage
const usage = await client.usage();
console.log(`Credits remaining: ${usage.credits_remaining}`);
```

## Error Handling

```typescript
import { SearchClaw, AuthError, RateLimitError, SearchClawError } from 'searchclaw';

const client = new SearchClaw({ apiKey: 'sc_live_xxx' });

try {
  const results = await client.search('test');
} catch (err) {
  if (err instanceof AuthError) {
    console.log('Invalid API key');
  } else if (err instanceof RateLimitError) {
    console.log(`Rate limited. Retry after ${err.retryAfter}s`);
  } else if (err instanceof SearchClawError) {
    console.log(`API error ${err.statusCode}: ${err.message}`);
  }
}
```

## Configuration

```typescript
const client = new SearchClaw({
  apiKey: 'sc_live_xxx',
  baseUrl: 'https://api.searchclaw.dev/v1', // default
  timeout: 30000,                            // default, in milliseconds
});
```

## Requirements

- Node.js 18+ (uses native `fetch`)

## License

MIT
