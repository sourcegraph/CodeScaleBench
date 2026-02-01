```markdown
# CanvasCraft ML Studio – Setup Guide  
*Version: 1.2 • Last updated: 2024-05-05*

Welcome to **CanvasCraft ML Studio**, a full-stack ML-Ops workbench for creative professionals.  
This guide walks you through installing all required tooling, cloning the repo, seeding the Feature Store, and running your first training pipeline.

---

## 1. Prerequisites

| Tool | Version | Why we need it |
|------|---------|----------------|
| [.NET SDK](https://dotnet.microsoft.com/download) | 8.0 LTS | Backend APIs, MVC UI, model-training pipelines |
| [Node.js](https://nodejs.org) | 20.x | Vue SPA front-end & Live-Reload dev server |
| [Docker Desktop](https://www.docker.com/) | 4.0+ | Local Feature Store (PostgreSQL) & Model Registry |
| Python (optional) | 3.11 | Interop workers & notebook examples |
| Git | latest | Clone, branch, & contribute |

> NOTE  
> CanvasCraft ML Studio is **cross-platform**. All commands shown below work on macOS, Linux, and Windows PowerShell (unless otherwise stated).

---

## 2. Clone & Restore

```bash
git clone https://github.com/CanvasCraft/CanvasCraftMLStudio.git
cd CanvasCraftMLStudio
dotnet restore
npm install --prefix CanvasCraftMLStudio/ClientApp
```

---

## 3. Bootstrap Local Infrastructure

For local development we rely on Docker to spin up:

1. **Feature Store** (PostgreSQL + TimescaleDB)
2. **Model Registry & Experiment Tracking** (MLflow w/ SQLite backend)
3. **Message Bus** (Redis) – drives Observer pattern events.

```bash
docker compose -f ops/docker-compose.local.yml up -d
```

Verify the containers:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

---

## 4. Configure Environment Variables

Create a `.env.development` file at the solution root.

```bash
cp .env.sample .env.development
```

Edit the file – minimal example:

```dotenv
# Database
CCFS__CONNECTION=Host=localhost;Port=5432;Database=canvas_craft_fs;Username=ccraft;Password=ccraft_dev_pwd

# Experiment Tracking
MLFLOW__URL=http://localhost:5000
MLFLOW__ARTIFACTS=s3://localhost:9000/artifacts

# Service Bus
CACHE__REDIS=localhost:6379

# GPU (optional)
CUDA_VISIBLE_DEVICES=0
```

The `appsettings.Development.json` file is already wired to read these keys.

---

## 5. Build & Run the Solution

```bash
dotnet build
dotnet run --project src/CanvasCraftMLStudio.Web
```

The API & MVC UI will start at `https://localhost:5143`.  
Separate hot-reload command (optional):

```bash
dotnet watch --project src/CanvasCraftMLStudio.Web run
```

Open another terminal and run the Vue front-end:

```bash
npm run dev --prefix CanvasCraftMLStudio/ClientApp
```

---

## 6. Seed the Feature Store

A helper CLI ships with the solution.

```bash
dotnet run \
  --project tools/CanvasCraftMLStudio.Tools \
  -- seed \
  --path ./samples/iris.csv \
  --dataset Iris \
  --description "Classic Iris dataset used for smoke tests."
```

Output:

```
[10:03:09 INF] Detected 150 rows, 5 columns.
[10:03:10 INF] Pushed ↑150 features to Feature Store (dataset: Iris, version: 1).
```

---

## 7. First Pipeline Run

The repo includes a **starter pipeline** that demonstrates Strategy + Factory patterns.

### 7.1. Examine the Pipeline Factory

```csharp
// File: src/CanvasCraftMLStudio.Core/Pipelines/PipelineFactory.cs
namespace CanvasCraftMLStudio.Core.Pipelines;

using CanvasCraftMLStudio.Core.Pipelines.Steps;
using CanvasCraftMLStudio.Core.Strategies;
using Microsoft.Extensions.DependencyInjection;

/// <summary>
/// Creates an end-to-end training pipeline using dependency injection.
/// </summary>
public static class PipelineFactory
{
    public static ITrainingPipeline Create(IServiceProvider sp, PipelineOptions options)
    {
        var logger = sp.GetRequiredService<ILoggerFactory>()
                       .CreateLogger("PipelineFactory");

        logger.LogInformation("Creating pipeline {Name}", options.Name);

        return new TrainingPipeline(options.Name)
               .AddStep(new IngestStep(sp, options))
               .AddStep(new FeatureEngineeringStep(sp, options))
               .AddStep(new HyperParameterTuningStep(sp, options))
               .AddStep(new TrainModelStep(sp, options))
               .AddStep(new EvaluateStep(sp, options))
               .AddStep(new RegisterModelStep(sp, options));
    }
}
```

### 7.2. Kick-off Training

```bash
dotnet run --project src/CanvasCraftMLStudio.CLI \
           -- train \
           --dataset Iris \
           --algorithm "FastForest" \
           --metric "MultiClassAccuracy"
```

Logs (abridged):

```
[10:12:43 INF] ☑️  IngestStep completed in 00:00:00.089
[10:12:44 INF] ☑️  FeatureEngineeringStep completed in 00:00:00.624
[10:12:56 INF] 🎨  HyperParameterTuningStep found best palette: N=300, Leaves=20, Depth=10
[10:13:04 INF] ✔️  TrainModelStep saved checkpoint artifacts/iris_ff_20240505_101304.zip
[10:13:05 WRN] Model accuracy drifted by −2.3 pp vs. previous checkpoint.
[10:13:05 INF] 🖼️  RegisterModelStep pushed model v.3 to registry.
```

Open `http://localhost:5000/#/experiments` (MLflow UI) to verify metrics and artifacts.

---

## 8. Automated Retraining (Observer Pattern)

`src/CanvasCraftMLStudio.Workers/ModelMonitorWorker.cs` keeps an eye on production metrics and triggers retraining if drift exceeds a configurable threshold.

Sample configuration:

```jsonc
"ModelMonitoring": {
  "Enabled": true,
  "DriftThreshold": 0.015, // 1.5 percentage points
  "CheckInterval": "00:05:00"
}
```

---

## 9. Troubleshooting

• **Docker port already in use**  
  Stop conflicting service or change ports in `docker-compose.local.yml`.

• **SSL certificate issues on Windows**  
  Run: `dotnet dev-certs https --trust`

• **GPU not detected**  
  Ensure CUDA drivers match your hardware. Set `CUDA_VISIBLE_DEVICES=` to empty string to force CPU.

---

## 10. Next Steps

1. Explore sample notebooks in `/notebooks`.
2. Add new preprocessing “brushes” by implementing `IFeatureBrushStrategy`.
3. Deploy a model to the interactive serving gallery (`src/CanvasCraftMLStudio.Serving`).

Happy crafting! 🖌️🖼️🤖
```