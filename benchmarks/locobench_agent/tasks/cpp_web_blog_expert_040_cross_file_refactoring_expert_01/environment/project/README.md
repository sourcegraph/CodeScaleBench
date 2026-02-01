# IntraLedger BlogSuite `(web_blog)`
Enterprise-grade blogging & knowledge-commerce platform powered by modern C++20  
[![Build & Test](https://github.com/intraledger/blogsuite/actions/workflows/ci.yml/badge.svg)](https://github.com/intraledger/blogsuite/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/intraledger/blogsuite)](LICENSE)
[![Discord](https://img.shields.io/discord/1098305554262241361?label=chat&logo=discord)](https://discord.gg/intraledger)

---

## ✨ Key Highlights
* **Single-binary deployment**—ship anywhere a modern libc++ is available.
* **Strict MVC + Repository & Service Layer** for clean business boundaries.
* **Internal ORM** supporting both MariaDB and PostgreSQL.
* **Full-text search** on articles with language stemming and typo-tolerance.
* **Multi-tenant auth** with classic logins, OAuth2 social SSO and SAML.
* **PCI-compliant payments** (Stripe) for subscriptions and one-off purchases.
* **Built-in job queue** for async e-mails, image transforms and cache warming.
* **Real-time back-office** (WebSocket driven) with analytics, audit log & workflows.
* **100 % modern C++20**, header-only third-party deps where possible.

---

## 🚀 Quick Start

1. **Clone**
   ```bash
   git clone --recursive https://github.com/intraledger/blogsuite.git
   cd blogsuite
   ```

2. **Configure**
   ```bash
   cmake -B build \
         -DCMAKE_BUILD_TYPE=Release \
         -DBLOG_ORM_BACKEND=POSTGRES \
         -DBLOG_ENABLE_STRIPE=ON
   ```

3. **Build & Run**
   ```bash
   cmake --build build -j$(nproc)
   ./build/bin/web_blog --config ./config/example.yml
   ```

Once started, the application listens on `http://localhost:8080` and exposes a Swagger-compatible OpenAPI spec at `/api/docs`.

---

## 🗄️ Project Structure
```
web_blog/
 ├─ src/
 │   ├─ core/               # MVC, routing, controllers
 │   ├─ auth/               # Authentication & authorization middleware
 │   ├─ db/                 # ORM, repositories, migrations
 │   ├─ service/            # Business services (payments, search, etc.)
 │   ├─ jobs/               # Asynchronous workers
 │   └─ ui/                 # Bundled SPAs & static assets
 ├─ config/                 # Sample YAML configs
 ├─ tests/                  # Catch2 & approval tests
 ├─ CMakeLists.txt
 └─ README.md
```

---

## 🏗️ Building From Source

### Prerequisites
* A C++20 compatible compiler (GCC 12+, Clang 15+, MSVC 19.37+)
* CMake 3.24+
* vcpkg or Conan (optional, for dependency management)
* PostgreSQL ≥ 12 or MariaDB ≥ 10.4
* OpenSSL, zlib (system packages)

### One-Liner (Linux/macOS)
```bash
scripts/build.sh --preset release --with-postgres
```

The helper script bootstraps vcpkg, resolves third-party libraries (Boost, c-tre, fmt, Sophia search) and produces a statically-linked executable.

---

## 🧩 Extending Functionality

Adding a new **Service Layer** component (e.g., `NewsletterService`):

```cpp
// service/newsletter/NewsletterService.hpp
#pragma once
#include <memory>
#include "db/RepositoryProvider.hpp"
#include "jobs/JobQueue.hpp"

namespace blog::service {

class NewsletterService {
public:
    explicit NewsletterService(std::shared_ptr<db::RepositoryProvider> repo,
                               std::shared_ptr<jobs::JobQueue> queue)
        : repo_(std::move(repo)), queue_(std::move(queue)) {}

    // Publishes a newsletter asynchronously to subscribers
    void publishNewsletter(std::string_view title,
                           std::string_view markdownContent,
                           std::chrono::system_clock::time_point scheduled = {}) const;

private:
    std::shared_ptr<db::RepositoryProvider> repo_;
    std::shared_ptr<jobs::JobQueue>         queue_;
};

} // namespace blog::service
```

```cpp
// service/newsletter/NewsletterService.cpp
#include "NewsletterService.hpp"
#include "db/repositories/UserRepository.hpp"
#include "jobs/tasks/SendEmailTask.hpp"
#include "util/Markdown.hpp"

namespace blog::service {

void NewsletterService::publishNewsletter(std::string_view title,
                                          std::string_view markdownContent,
                                          std::chrono::system_clock::time_point scheduled) const
{
    const auto html = util::Markdown::toHtml(markdownContent);
    const auto recipients = repo_->users()->subscribedTo("newsletter");

    for (const auto& user : recipients) {
        jobs::tasks::SendEmailTask task {
            .to      = user.email,
            .subject = std::string{title},
            .body    = html
        };
        queue_->enqueue(task, scheduled);
    }
}

} // namespace blog::service
```

No controller changes are necessary; simply register the service in `DependencyRegistry.cpp` and add a route in `routes/newsletter.yml`.

---

## 🔐 Security Best Practices

* All cookies flagged with `HttpOnly`, `Secure`, `SameSite=Strict`.
* Secrets and DB credentials are loaded exclusively via environment variables or HashiCorp Vault.
* Mutual TLS is supported by toggling `tls.require_client_cert: true` in the YAML config.
* **OWASP Zap** executed on every PR via GitHub Actions.

---

## 🛠️ Development Workflow

1. Fork → Feature Branch (`feature/<issue>-short-desc`)
2. `cmake --preset dev && ninja`  
   (pre-commit hooks run clang-format, clang-tidy, include-what-you-use)
3. `ctest` must pass 🟢  
4. Open PR & fill out the template; reviewers from `@intraledger/maintainers` will be auto-assigned.
5. Upon merge, the CD pipeline publishes a Docker image to GHCR and artifacts to the release page.

---

## 📝 Testing

We rely on **Catch2 v3** with an expressive BDD-style syntax:

```cpp
TEST_CASE("Article full-text search yields expected result set", "[search]") {
    using namespace blog::search;
    FullTextSearchEngine engine{createTestIndex()};

    SECTION("Search by phrase matches relevant article titles") {
        const auto results = engine.query("modern c++ coroutine");
        REQUIRE(results.size() == 3);
        REQUIRE(results[0].score > results[1].score);
    }
}
```

Integration tests spin up docker-compose services for DB + Redis + Minio; run `scripts/test.sh` to execute the full matrix.

---

## 🤝 Contributing
We welcome community involvement! Please read `CONTRIBUTING.md` for our code of conduct, branching model, and architectural decision record (ADR) process.

---

## 📄 License
IntraLedger BlogSuite is distributed under the Apache License 2.0—see [`LICENSE`](LICENSE) for details.

---

Happy blogging! 🎉