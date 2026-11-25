# Security and Privacy

## Before Making the Repository Public

- Do not commit app_data/. This directory stores the cineduo.sqlite3 database, cached posters, backups, and potentially API keys.
- Never publish .env files, screenshots containing API keys or tokens, backup files, or exports of your personal movie rankings.
- The .gitignore file helps prevent accidental commits, but does not replace reviewing git status before every commit.
- If an API key or token has been visible in a shared screenshot, revoke or regenerate the credential through its provider and update the application with the replacement.
- Do not use the --network mode on untrusted or public networks, and do not expose port 8765 to the internet through your router.

## Current Security Limitations

CineDuo currently runs on a local HTTP server without user authentication. The optional --network mode can allow other devices on the same local network to connect. This server must not be exposed directly to the public internet.

Before deploying CineDuo publicly or providing private remote access, the application will need authentication, authorization, route protection, secure credential and data storage, and a security review.

## If a Credential Is Committed to a Public Repository

**Revoke or rotate the exposed credential immediately.** Removing a file from the latest commit does not remove sensitive data from the Git history.
See GitHub's guidance: Removing sensitive data from a repository.