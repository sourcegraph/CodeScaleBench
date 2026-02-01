<!--
  FlockDesk – Social Workspace Orchestrator
  Pull-Request Template
  ---------------------------------------------------------------------------
  A well-structured PR description is critical for maintainability, review
  efficiency, and release accuracy.  This template is designed to capture the
  essential technical and UX context required by core maintainers, security
  reviewers, QA engineers, and community contributors.
  ---------------------------------------------------------------------------
  NOTE:
    ☐   Keep all checklist items unless *absolutely* irrelevant.
    ☐   “N/A” is preferred over deleting sections.
    ☐   Use reference links for issues/epics (e.g. `FDK-123`).
    ☐   Remove these comments before submitting.
-->

# 📌  Summary

> _High-level, one-sentence overview of what the PR does._

---

# 🚦  Type of Change
<!-- Choose one or more by uncommenting. -->
- [ ] ✨ Feature         — New capability
- [ ] 🐛 Fix             — Bug fix
- [ ] 📚 Docs            — Documentation (no code change)
- [ ] ♻️ Refactor        — Code quality / maintainability
- [ ] ⚡️ Performance    — Speed or memory improvement
- [ ] 🛡 Security        — Vulnerability mitigation
- [ ] 🔄 Chore           — Build, tooling, or housekeeping
- [ ] 🧪 Test            — Adding / updating tests
- [ ] 💥 Breaking Change — Requires major version bump

---

# 🗂  Scope

| Area                    | Affected | Notes                          |
|-------------------------|----------|--------------------------------|
| Core Event Bus          | ☐        |                                |
| Plugin SDK              | ☐        |                                |
| Desktop Micro-UIs       | ☐        | Chat, Board, Presence, etc.    |
| Auto-Update Pipeline    | ☐        |                                |
| Crash Reporting         | ☐        |                                |
| Build / CI              | ☐        | GitHub Actions, packaging      |
| Docs / Examples         | ☐        |                                |
| Other                   | ☐        |                                |

---

# 📝  Related Issues / Tickets

Closes:  
Relates to:  

---

# 🎨  UI / UX (Screenshots or GIF)

> _Attach visual evidence for any user-facing changes._

---

# 🧪  How to Test

```bash
# 1️⃣  Environment setup (if new dependencies or migrations)
pip install -r requirements-dev.txt
flockdesk bootstrap --profile dev

# 2️⃣  Run unit / integration tests
pytest -m "not e2e"

# 3️⃣  Manual verification steps
# ☐  Step-by-step instructions ...
```

---

# 🔍  Reviewer Checklist (for PR author)
<!-- Mark each as completed (☑) or N/A (🚫) -->
- [ ] Code compiles and lints (`pre-commit run --all-files`)
- [ ] Unit tests pass locally
- [ ] New / updated tests added
- [ ] Docs updated (README, CHANGELOG, API docs, etc.)
- [ ] Sentry logging added / updated
- [ ] No secrets, credentials, or PII committed
- [ ] Follows the coding style-guide and naming conventions
- [ ] UI strings are i18n-ready
- [ ] End-to-end smoke test completed
- [ ] Version / build numbers bumped as needed
- [ ] No breaking changes without migration guide
- [ ] Conforms to accessibility (WCAG) guidelines

---

# 🔒  Security Implications

> _Describe any new attack surface, permission changes, data flows, or cryptographic primitives introduced._

---

# ⚠️  Deployment / Migration

- **Feature flag:**            ☐  Introduced  ☐  Existing  ☐  N/A  
- **DB migrations required:**  ☐  Yes         ☐  No  
- **Rollback strategy:**       _Describe how to revert-deploy safely._  

---

# 📓  Notes for Release Team

> _Concise, bullet-point summary for CHANGELOG or release blog._

---

# 👥  Additional Reviewers

| Area      | Reviewer  | Completed |
|-----------|-----------|-----------|
| Security  | @...      | ☐         |
| QA        | @...      | ☐         |
| Docs      | @...      | ☐         |
| UX / UI   | @...      | ☐         |

---

_Thank you for contributing to FlockDesk!_