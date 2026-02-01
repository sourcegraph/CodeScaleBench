```markdown
# CardioInsight 360 – Configuration Guide
_Author: CardioInsight 360 Engineering Team_  
_Version: 1.2.0_  
_Last Updated: 2024-05-17_

---

## 1. Introduction
CardioInsight 360 ships as a single, self-contained binary (`cardio_insight_360`) accompanied by a declarative YAML configuration file that activates or deactivates platform capabilities at runtime.  
This guide covers:

* The canonical **YAML schema** consumed at boot-time
* **Environment-variable overrides** for container or CI/CD deployments
* A reference **C++17 loader/validator** using `yaml-cpp`
* **Security considerations** (PHI retention, encryption keys, audit logging)

---

## 2. Minimum Working Example

Save as `ci360.yaml` adjacent to the executable unless `CI360_CONFIG_PATH` is set.

```yaml
system:
  node_id: "icu-node-01"
  log_level: "INFO"         # Valid: TRACE|DEBUG|INFO|WARN|ERROR|CRITICAL
  temp_dir: "/var/tmp/ci360"

ingest:
  hl7:
    enabled: true
    port: 2575
    max_message_size_kb: 512
  fhir_rest:
    enabled: false
  kafka:
    bootstrap_servers: "kafka-broker:9092"
    group_id: "ci360_ingest"
    security:
      sasl_mechanism: "SCRAM-SHA-256"
      sasl_username: "${CI360_KAFKA_USER}"        # env-var substitution
      sasl_password: "${CI360_KAFKA_PASS}"
      tls_ca_path: "/etc/ssl/certs/ca-certificates.crt"

storage:
  base_path: "/data/ci360"
  parquet_compression: "ZSTD"   # Valid: NONE|SNAPPY|GZIP|ZSTD|LZ4|BROTLI
  retention_days:
    raw: 30
    curated: 365

etl:
  max_concurrency: 8            # Defaults to available hardware threads
  batch_window_minutes: 15
  validation_profile: "adult_cardiac"

monitoring:
  metrics_port: 9090
  enable_pprof: false

security:
  encryption_key_path: "/etc/ci360/keys/enc.key"
  audit_log_path: "/var/log/ci360/audit.log"
```

---

## 3. Detailed Field Reference

### 3.1 `system`
| Key             | Type   | Default | Description                                  |
|-----------------|--------|---------|----------------------------------------------|
| `node_id`       | string | —       | Unique identifier that appears in metrics, log headers, and Kafka consumer groups. |
| `log_level`     | enum   | `INFO`  | Controls global log verbosity.               |
| `temp_dir`      | path   | `/tmp`  | Scratch space for intermediate files.        |

*(remaining sections omitted for brevity)*

---

## 4. Environment-Variable Overrides

The loader performs a **recursive walk** and expands tokens of the form `${ENV_VAR}` _after_ the YAML is parsed but _before_ validation, allowing secrets to remain outside of the file.

Example:

```bash
export CI360_KAFKA_USER="service-account"
export CI360_KAFKA_PASS="$(gcloud secrets versions access latest --secret=ci360-kafka-pass)"
cardio_insight_360 --config=/opt/conf/ci360.yaml
```

---

## 5. Reference C++17 Loader/Validator

```cpp
// ----------------------------------------------------------------------------
// File: ConfigurationLoader.hpp
// ----------------------------------------------------------------------------
#pragma once
#include <yaml-cpp/yaml.h>
#include <filesystem>
#include <optional>
#include <regex>
#include <string>
#include <unordered_map>

namespace ci360::config {

struct SecurityCfg
{
    std::filesystem::path encryptionKeyPath;
    std::filesystem::path auditLogPath;
};

struct KafkaSecurityCfg
{
    std::string saslMechanism;
    std::string saslUsername;
    std::string saslPassword;
    std::filesystem::path tlsCaPath;
};

struct KafkaCfg
{
    std::string bootstrapServers;
    std::string groupId;
    KafkaSecurityCfg security;
};

struct IngestCfg
{
    bool hl7Enabled;
    uint16_t hl7Port;
    std::size_t maxMessageSizeKB;
    bool fhirEnabled;
    KafkaCfg kafka;
};

struct SystemCfg
{
    std::string nodeId;
    std::string logLevel;
    std::filesystem::path tempDir;
};

struct StorageCfg
{
    std::filesystem::path basePath;
    std::string parquetCompression;
    int rawRetentionDays;
    int curatedRetentionDays;
};

struct EtlCfg
{
    std::size_t maxConcurrency;
    int batchWindowMinutes;
    std::string validationProfile;
};

struct MonitoringCfg
{
    uint16_t metricsPort;
    bool enablePprof;
};

struct RootConfig
{
    SystemCfg system;
    IngestCfg ingest;
    StorageCfg storage;
    EtlCfg etl;
    MonitoringCfg monitoring;
    SecurityCfg security;
};

class ConfigurationError : public std::runtime_error
{
public:
    using std::runtime_error::runtime_error;
};

class ConfigurationLoader
{
public:
    explicit ConfigurationLoader(std::filesystem::path path);
    [[nodiscard]] const RootConfig& get() const noexcept { return config_; }

private:
    static YAML::Node preprocess(const YAML::Node& root);
    static std::string expandEnv(const std::string& value);
    static void validate(const RootConfig& cfg);
    RootConfig config_;
};

} // namespace ci360::config
```

```cpp
// ----------------------------------------------------------------------------
// File: ConfigurationLoader.cpp
// ----------------------------------------------------------------------------
#include "ConfigurationLoader.hpp"
#include <cstdlib>
#include <iostream>

namespace ci360::config {

namespace fs = std::filesystem;

// -------- Helper Utilities --------------------------------------------------

static std::string readRequiredString(const YAML::Node& n, const char* field)
{
    if (!n[field] || !n[field].IsScalar())
        throw ConfigurationError{"Field '" + std::string(field) + "' is missing or not a scalar"};
    return n[field].as<std::string>();
}

// -------- Constructor -------------------------------------------------------

ConfigurationLoader::ConfigurationLoader(fs::path path)
{
    if (!fs::exists(path))
        throw ConfigurationError{"Config file not found: " + path.string()};

    YAML::Node root = YAML::LoadFile(path.string());
    root            = preprocess(root); // env-var expansion

    // ---- system -----------------------------------------------------------
    config_.system.nodeId  = readRequiredString(root["system"], "node_id");
    config_.system.logLevel= readRequiredString(root["system"], "log_level");
    config_.system.tempDir = root["system"]["temp_dir"].as<fs::path>("/tmp");

    // ---- ingest -----------------------------------------------------------
    const auto& ingestN          = root["ingest"];
    config_.ingest.hl7Enabled    = ingestN["hl7"]["enabled"].as<bool>(false);
    config_.ingest.hl7Port       = ingestN["hl7"]["port"].as<uint16_t>(2575);
    config_.ingest.maxMessageSizeKB = ingestN["hl7"]["max_message_size_kb"].as<std::size_t>(256);

    config_.ingest.fhirEnabled   = ingestN["fhir_rest"]["enabled"].as<bool>(false);

    const auto& kafkaN           = ingestN["kafka"];
    config_.ingest.kafka.bootstrapServers = readRequiredString(kafkaN, "bootstrap_servers");
    config_.ingest.kafka.groupId = readRequiredString(kafkaN, "group_id");

    const auto& kSecN            = kafkaN["security"];
    config_.ingest.kafka.security.saslMechanism = readRequiredString(kSecN, "sasl_mechanism");
    config_.ingest.kafka.security.saslUsername  = readRequiredString(kSecN, "sasl_username");
    config_.ingest.kafka.security.saslPassword  = readRequiredString(kSecN, "sasl_password");
    config_.ingest.kafka.security.tlsCaPath     = kSecN["tls_ca_path"].as<fs::path>("");

    // ---- storage ----------------------------------------------------------
    const auto& storageN         = root["storage"];
    config_.storage.basePath     = readRequiredString(storageN, "base_path");
    config_.storage.parquetCompression = readRequiredString(storageN, "parquet_compression");
    config_.storage.rawRetentionDays   = storageN["retention_days"]["raw"].as<int>(30);
    config_.storage.curatedRetentionDays=storageN["retention_days"]["curated"].as<int>(365);

    // ---- etl --------------------------------------------------------------
    const auto& etlN             = root["etl"];
    config_.etl.maxConcurrency   = etlN["max_concurrency"].as<std::size_t>(std::thread::hardware_concurrency());
    config_.etl.batchWindowMinutes = etlN["batch_window_minutes"].as<int>(15);
    config_.etl.validationProfile  = readRequiredString(etlN, "validation_profile");

    // ---- monitoring -------------------------------------------------------
    const auto& monN             = root["monitoring"];
    config_.monitoring.metricsPort = monN["metrics_port"].as<uint16_t>(9090);
    config_.monitoring.enablePprof = monN["enable_pprof"].as<bool>(false);

    // ---- security ---------------------------------------------------------
    const auto& secN             = root["security"];
    config_.security.encryptionKeyPath = readRequiredString(secN, "encryption_key_path");
    config_.security.auditLogPath      = readRequiredString(secN, "audit_log_path");

    validate(config_);
}

// -------- Preprocessing & Helpers ------------------------------------------

YAML::Node ConfigurationLoader::preprocess(const YAML::Node& root)
{
    YAML::Node result = YAML::Clone(root);
    std::regex envPattern(R"(\$\{([^}]+)\})");

    std::function<void(YAML::Node)> recurse = [&](YAML::Node n)
    {
        if (n.IsScalar())
        {
            std::string value = n.as<std::string>();
            n = expandEnv(value);
        }
        else if (n.IsSequence() || n.IsMap())
        {
            for (auto sub : n)
                recurse(sub);
        }
    };
    recurse(result);
    return result;
}

std::string ConfigurationLoader::expandEnv(const std::string& value)
{
    std::regex envPattern(R"(\$\{([^}]+)\})");
    std::smatch match;
    std::string expanded = value;
    while (std::regex_search(expanded, match, envPattern))
    {
        const char* envVal = std::getenv(match[1].str().c_str());
        if (!envVal)
            throw ConfigurationError{"Environment variable '" + match[1].str() + "' is not set"};
        expanded.replace(match.position(), match.length(), envVal);
    }
    return expanded;
}

// -------- Validation -------------------------------------------------------

void ConfigurationLoader::validate(const RootConfig& cfg)
{
    auto isEnum = [](std::string_view v, std::initializer_list<std::string_view> allowed)
    {
        return std::find(allowed.begin(), allowed.end(), v) != allowed.end();
    };

    if (!isEnum(cfg.system.logLevel, {"TRACE","DEBUG","INFO","WARN","ERROR","CRITICAL"}))
        throw ConfigurationError{"Invalid log level: " + cfg.system.logLevel};

    if (!isEnum(cfg.storage.parquetCompression, {"NONE","SNAPPY","GZIP","ZSTD","LZ4","BROTLI"}))
        throw ConfigurationError{"Unsupported Parquet compression: " + cfg.storage.parquetCompression};

    if (!cfg.ingest.hl7Port || cfg.ingest.hl7Port > 65535)
        throw ConfigurationError{"HL7 port out of range: " + std::to_string(cfg.ingest.hl7Port)};

    // Additional domain-specific checks can be placed here…
}

} // namespace ci360::config
```

Usage:

```cpp
#include "ConfigurationLoader.hpp"
#include <iostream>

int main(int argc, char* argv[])
{
    const std::string path = argc > 1 ? argv[1] : "ci360.yaml";
    try
    {
        ci360::config::ConfigurationLoader loader{path};
        const auto& cfg = loader.get();
        std::cout << "Config loaded for node: " << cfg.system.nodeId << '\n';
    }
    catch (const ci360::config::ConfigurationError& ex)
    {
        std::cerr << "Configuration error: " << ex.what() << '\n';
        return EXIT_FAILURE;
    }
}
```

Compile:

```bash
g++ -std=c++17 -I/usr/include/yaml-cpp \
    main.cpp ConfigurationLoader.cpp -lyaml-cpp -o ci360_config_validator
```

---

## 6. Security & Compliance Notes
1. **Encryption keys** must never be committed to source control. Use a secret-manager integration and reference via environment variables or mounted volumes.  
2. **Audit logs** are immutable WORM files; configure `audit_log_path` on a tamper-evident filesystem (e.g., Amazon S3, Ceph with S3-Object-Lock).  
3. Rotate **Kafka credentials** at least every 90 days and automate with your CI pipeline.

---

## 7. Troubleshooting Checklist
| Symptom                            | Possible Cause                          | Resolution                          |
|------------------------------------|-----------------------------------------|-------------------------------------|
| `Configuration error: ...not set`  | Missing env-var                         | Export it or hard-code in YAML      |
| Application exits immediately      | Invalid YAML syntax                     | Validate with `yamllint`            |
| Kafka consumer cannot connect      | Wrong SASL mechanism or credentials     | Verify with `kafkacat -X ...`       |
| Disk keeps filling up              | Retention days too high                 | Lower `retention_days.raw`          |

---

_© 2024 CardioInsight360. All rights reserved._
```