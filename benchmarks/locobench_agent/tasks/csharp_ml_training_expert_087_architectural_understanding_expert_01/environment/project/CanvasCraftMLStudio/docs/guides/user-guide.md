```markdown
---
title: CanvasCraft ML Studio – User Guide
description: End-to-end walkthrough for composing, training, and deploying models with CanvasCraft ML Studio.
lastUpdated: 2024-06-18
---

# ✨ CanvasCraft ML Studio – User Guide  
> Where Machine Learning meets Digital Artistry  

CanvasCraft ML Studio treats every model as an evolving masterpiece.  
This guide shows you how to install the SDK, create your first experiment,
compose custom preprocessing “brushes,” train and version a model, and finally
curate it inside the interactive Model Gallery.

---

## Table of Contents
1. [Installation](#installation)  
2. [Hello, Canvas! – Your First Experiment](#hello-canvas)  
3. [Experiment Tracking](#experiment-tracking)  
4. [Composing Pipelines (Strategy + Factory)](#composing-pipelines)  
5. [Feature Store Integration](#feature-store)  
6. [Hyper-Parameter “Color Wheels”](#hyperparameter-tuning)  
7. [Model Registry & Gallery Deployment](#model-registry)  
8. [Live Model Monitoring](#model-monitoring)  
9. [Extending CanvasCraft](#extending-canvascraft)  
10. [Troubleshooting & FAQ](#troubleshooting)  

---

<a name="installation"></a>
## 1 – Installation

```bash
# Assuming .NET 7+
dotnet add package CanvasCraft.ML.Studio --prerelease
dotnet add package CanvasCraft.ML.Studio.Plotting
dotnet add package CanvasCraft.ML.Studio.Azure   # optional cloud back-end
```

Add the following **global using** directive to your project so the DSL remains terse:

```csharp
global using CanvasCraft.ML.Studio;
```

---

<a name="hello-canvas"></a>
## 2 – Hello, Canvas! – Your First Experiment

The snippet below trains a simple image-style classifier using the default
settings and logs every creative stroke to the Experiment Tracker.

```csharp
using CanvasCraft.ML.Studio;
using CanvasCraft.ML.Studio.Pipelines;
using CanvasCraft.ML.Studio.Registry;
using CanvasCraft.ML.Studio.Tracking;

var experimentId = Guid.NewGuid().ToString("N");

await using var studio = CanvasStudio
    .Create($"StyleClassifier-{experimentId}")
    .UseLocalWorkspace()        // Files go to ~/.canvascraft by default
    .WithDefaultConfiguration() // Sensible defaults for batch size, caching, etc.
    .BuildAsync();              // async-factory ensures any I/O finishes

// Load training/validation datasets
var dataset = await studio.Data
    .FromFolder("datasets/style_images")
    .AsImageClassification(labelsFromFolderName: true)
    .CacheAsync(); // Caches to Feature Store

// Train model with a single line
var model = await studio.Train
    .WithPreset(ImageClassifier.Presets.ResNet50)
    .On(dataset)
    .RunAsync();

// Evaluate and log metrics
var report = await model.EvaluateAsync(dataset.Validation);
studio.Track.Log(report);

// Save model to registry so other creators can remix it
await model.RegisterAsync("ResNet50-StyleClassifier");
```

**What just happened?**  
1. `CanvasStudio.Create` scaffolds an experiment folder, Git branch, and SQLite
   tracking DB.  
2. `Data.FromFolder` lazily enrolls raw bytes in the Feature Store.  
3. `Train.WithPreset` leverages the Factory Pattern to spit out a ready-made
   pipeline.  
4. All metrics, artifacts, and checkpoints are versioned and queryable through
   the UI or the SDK.

---

<a name="experiment-tracking"></a>
## 3 – Experiment Tracking

CanvasCraft logs everything—including
hyper-parameters, system info, and git commit hash—allowing you to reproduce or
fork any prior run.

```csharp
// Access the fluent query API
var leaderboard = await studio.Track
    .Experiments
    .Where(x => x.Name.StartsWith("StyleClassifier-"))
    .OrderByDescending(x => x.Timestamp)
    .Take(5)
    .ToListAsync();

// Render the leaderboard as a beautiful gallery
await studio.View.Gallery.ShowLeaderboardAsync(leaderboard);
```

You can even time-travel to a specific checkpoint:

```csharp
await studio.Track.RollbackAsync(experimentSha: "8e16f2c");
```

---

<a name="composing-pipelines"></a>
## 4 – Composing Pipelines (Strategy + Factory Patterns)

### 4.1 – Swapping Pre-Processing Brushes

Each `IBrush` encapsulates a pre-processing strategy.

```csharp
public sealed class SepiaToneBrush : IBrush<ImageFrame>
{
    public string Name => "SepiaTone";

    public async Task<ImageFrame> ApplyAsync(ImageFrame input, CancellationToken token = default)
    {
        // Ensure we never block the UI thread
        return await Task.Run(() => ImageFx.ApplySepia(input), token);
    }
}

// Register your brush
studio.Strategy.Brushes.Register(new SepiaToneBrush());
```

### 4.2 – Building a Custom Pipeline

```csharp
var customPipeline = studio.Pipelines
    .Create("Custom-Stylistic-Pipeline")
    .AddBrush<SepiaToneBrush>()       // our custom strategy
    .AddBrush<RandomCropBrush>(o =>   // built-in brush with options
    {
        o.Probability = 0.5;
        o.Size        = 224;
    })
    .AddFeatureEngineering<HistogramOfGradients>()
    .AddModelTrainer<CnnTrainer>(t =>
    {
        t.Epochs          = 25;
        t.InitialLearningRate = 1e-4;
    })
    .Build();

var stylizedModel = await customPipeline.FitAsync(dataset.Training);
await stylizedModel.RegisterAsync("SepiaHOG-CNN-v1");
```

---

<a name="feature-store"></a>
## 5 – Feature Store Integration

Cache expensive feature extractions once, reuse many times.

```csharp
// Ingest raw data once
await studio.FeatureStore
    .IngestAsync(dataset.Training, overwrite: false);

// Retrieve engineered features
var histograms = await studio.FeatureStore
    .Query<HistogramFeature>()
    .Where(f => f.DatasetId == dataset.Id &&
                f.Version    == "v1")
    .ToListAsync();
```

---

<a name="hyperparameter-tuning"></a>
## 6 – Hyper-Parameter “Color Wheels”

Hyper-parameter search is treated as an artistic color wheel—
you spin it, the Studio paints.

```csharp
var searchSpace = new GridSearch
{
    { "learning_rate", new []{ 1e-3, 1e-4, 5e-5 } },
    { "optimizer",     new []{ "Adam", "RMSProp" } },
    { "batch_size",    new []{ 16, 32 } }
};

await studio.Tune
    .With(searchSpace)
    .Using<EarlyStoppingCriterion>(c =>
    {
        c.Patience = 3;
        c.Metric   = MetricType.ValidationLoss;
    })
    .On(dataset)
    .RunAsync(maxTrials: 20);
```

All trials stream to the dashboards in real time:

```csharp
await studio.View.Dashboard.ShowHyperparameterSearchAsync();
```

---

<a name="model-registry"></a>
## 7 – Model Registry & Gallery Deployment

```csharp
// Retrieve best model
var bestModel = await studio.Registry
    .Models
    .Where(m => m.Tags.Contains("ResNet50-StyleClassifier"))
    .OrderByDescending(m => m.Metrics["Accuracy"])
    .FirstAsync();

// Deploy to interactive gallery
await bestModel.DeployAsync(new GalleryDeploymentOptions
{
    EndpointName  = "style-classifier-demo",
    AutoScale     = true,
    MinReplicas   = 1,
    MaxReplicas   = 10
});
```

The gallery endpoint renders as a 3-D carousel where users can drop an image and
see style predictions alongside Class Activation Maps.  
Any user annotation flows back into the Feature Store, ready for the next
retraining session.

---

<a name="model-monitoring"></a>
## 8 – Live Model Monitoring

CanvasCraft ships with reactive, Observer-pattern monitoring:

```csharp
var monitor = studio.Monitor
    .For(bestModel)
    .AddDriftDetector<KLDivergenceDetector>(options =>
    {
        options.WindowSize    = 500;
        options.Threshold     = 0.15;
    })
    .AddPerformanceAlert(metric: MetricType.Top1Accuracy, threshold: 0.90)
    .OnAnomaly(async (sender, evt) =>
    {
        // Notify Slack
        await SlackNotifier.NotifyAsync($"🚨 Model drift detected: {evt.Description}");
        // Optionally trigger auto-retrain
        await studio.Controller.TriggerRetrainAsync(bestModel.Id);
    })
    .Start();

// Dispose monitoring gracefully on shutdown
await monitor.DisposeAsync();
```

---

<a name="extending-canvascraft"></a>
## 9 – Extending CanvasCraft

Because CanvasCraft embraces
SOLID principles, extending the framework is frictionless.

### 9.1 – Writing a Custom Loss Function

```csharp
public sealed class ArtisticContrastiveLoss : ILossFunction
{
    public string Name => "ArtisticContrastiveLoss";

    public float Compute(ReadOnlySpan<float> predictions, ReadOnlySpan<float> labels)
    {
        if (predictions.Length != labels.Length)
            throw new ArgumentException("Dimensionality mismatch.", nameof(predictions));

        var loss = 0f;
        for (int i = 0; i < predictions.Length; i++)
        {
            var diff = predictions[i] - labels[i];
            loss += diff * diff * (1 + MathF.Abs(predictions[i])); // emphasize contrast
        }
        return loss / predictions.Length;
    }
}
```

Register the loss in your pipeline:

```csharp
studio.Factory.LossFunctions.Register(new ArtisticContrastiveLoss());
```

---

<a name="troubleshooting"></a>
## 10 – Troubleshooting & FAQ

| Symptom                                 | Possible Cause                        | Remedy                                       |
| --------------------------------------- | ------------------------------------- | -------------------------------------------- |
| `CanvasStoreIOException` during cache   | Disk quota exceeded                   | Configure `studio.UseCloudWorkspace()`       |
| Training hangs at step 0               | GPU driver mismatch or OOM            | Update CUDA drivers or lower batch size      |
| Drift detector false positives          | Threshold too aggressive              | Increase `options.Threshold` in detector     |
| Not seeing any metrics in dashboard     | WebSocket blocked by firewall         | Allow outbound 443 to `*.canvascraft.ai`     |

---

## Next Steps

– Check out the advanced [Developer Guide](./developer-guide.md)  
– Join the #canvascraft Discord for community showcases  
– File issues or feature requests on GitHub

Happy painting with data! 🎨🖌️
```