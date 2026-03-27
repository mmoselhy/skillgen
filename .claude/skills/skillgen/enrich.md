# Community Enrichment — Supporting Reference

## Index URL

`https://raw.githubusercontent.com/skillgen/skill-index/main/index.json`

## Index JSON Schema

```json
{
  "version": 1,
  "updated": "YYYY-MM-DD",
  "skills": [
    {
      "id": "python-logging-structlog",
      "name": "Structured Logging with structlog",
      "language": "python",
      "framework": null,
      "categories": ["logging-and-observability"],
      "path": "skills/python/logging-structlog.md",
      "description": "Conventions for structured logging using structlog in Python projects."
    }
  ]
}
```

Fields: `id` (unique slug, used as filename), `name` (display name), `language` (python/typescript/go/rust/java/any), `framework` (string or null), `categories` (array matching local skill filenames without .md), `path` (relative path in repo), `description` (one-line summary).

## Skill Content URL

Combine base with `path`: `https://raw.githubusercontent.com/skillgen/skill-index/main/{path}`
