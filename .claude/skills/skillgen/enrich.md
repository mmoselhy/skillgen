# Community Enrichment — Supporting Reference

## Index URL

`https://raw.githubusercontent.com/mmoselhy/skill-index/main/index.json`

## Index JSON Schema (v2)

```json
{
  "version": 2,
  "updated": "2026-03-28T04:30:00Z",
  "sources_crawled": ["anthropics/skills", "PatrickJS/awesome-cursorrules"],
  "skills": [
    {
      "id": "anthropic-frontend-design",
      "name": "Frontend Design",
      "language": "any",
      "framework": null,
      "categories": ["architecture", "code-style"],
      "description": "Create distinctive, production-grade frontend interfaces.",
      "source_repo": "anthropics/skills",
      "source_path": "skills/frontend-design/SKILL.md",
      "content_url": "https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend-design/SKILL.md",
      "trust": "official",
      "format": "skill-md",
      "tags": ["frontend", "design"],
      "updated_at": "2026-03-15"
    }
  ]
}
```

## Fields

- `id` — unique slug
- `name` — display name
- `language` — python/typescript/javascript/go/rust/java/any
- `framework` — string or null
- `categories` — array matching local skill filenames without .md
- `description` — one-line summary
- `source_repo` — GitHub owner/repo where the skill originates
- `source_path` — path within the source repo
- `content_url` — direct raw URL to fetch content
- `trust` — `official`, `community`, or `contributed`
- `format` — `skill-md`, `cursorrules`, `copilot-instructions`, `claude-md`, `markdown`
- `tags` — freeform search tags
- `updated_at` — ISO date of last source modification

## Trust Tiers

| Tier | Label | Sources |
|---|---|---|
| 1 | `official` | anthropics/skills, anthropics/claude-code/plugins, github/awesome-copilot |
| 2 | `community` | PatrickJS/awesome-cursorrules, josix/awesome-claude-md |
| 3 | `contributed` | User-submitted via PR to skill-index repo |

## Skill Content URL

Each skill has a `content_url` field pointing directly to the raw file in the source repo. Use this URL to fetch content. If `content_url` is empty (v1 entries), fall back to: `https://raw.githubusercontent.com/mmoselhy/skill-index/main/{path}`
