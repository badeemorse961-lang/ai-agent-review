# Repository / Local Boundary

## GitHub
GitHub is the source of truth for:
- source code
- tests
- documentation
- schemas
- non-secret configuration
- architectural rules

## Local-only
Keep local:
- API key files
- `.env`
- machine credentials
- machine-specific runtime state
- local model stores
- machine caches
- other protected secrets

## Secret rule
Never commit raw API keys, tokens, passwords, or secret-bearing environment files.

The repository may contain:
- connection IDs
- provider/model names
- secret fingerprints
- non-secret roles/configuration

## Runtime secrets
Secrets are loaded at runtime from local protected storage.

Conceptual layout:
```text
D:\AI-Agent\Secrets\
    groq_keys.txt
    openrouter_keys.txt

D:\AI-Agent\Sandbox\agent-test\
    repository-controlled files
```

## Synchronization
Synchronization means synchronizing repository-controlled state.

It does not mean deleting every local file absent from Git.

## Destructive commands
Normal synchronization must not blindly use:
- `git clean -fd`
- `git reset --hard`

when they can destroy protected local state.

## Ollama
Ollama/local model storage is outside the Git repository lifecycle and must not be deleted by repository synchronization.
