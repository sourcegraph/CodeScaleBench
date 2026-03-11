# Reusable Components for Other Teams

| Component | Best Use Stages | Reuse Score Profile | What To Reuse |
|---|---|---|---|
| Skills, QA, Task Factory | Task Design, Quality Gates | Task Design:1.0, Quality Gates:0.9, Execution Harness:0.4, Operations:0.3, Evaluation Analysis:0.2 | Task templates, skill wrappers, task intake flow |
| Dashboard + Audit Ops | Operations | Operations:1.0, Execution Harness:0.6, Quality Gates:0.5, Evaluation Analysis:0.5, Task Design:0.2 | Run state model (READY/BLOCKED/ERROR), promotion checks |
| IR Evaluation Pipeline | Evaluation Analysis, Quality Gates | Evaluation Analysis:1.0, Quality Gates:0.7, Operations:0.4, Task Design:0.3, Execution Harness:0.2 | Retrieval normalization + metric extraction pipeline |
| Curator + ContextBench | Evaluation Analysis, Quality Gates | Evaluation Analysis:0.8, Quality Gates:0.7, Task Design:0.6, Execution Harness:0.4, Operations:0.3 | Curator workflow with timeout/retry and coverage closure |
| LLM Judge + Trace Analysis | Evaluation Analysis, Quality Gates | Evaluation Analysis:1.0, Quality Gates:0.8, Operations:0.5, Task Design:0.2, Execution Harness:0.2 | Judge+trace coupling for root-cause attribution |
| Harness + Infra | Execution Harness, Operations | Execution Harness:1.0, Operations:0.9, Evaluation Analysis:0.4, Quality Gates:0.3, Task Design:0.1 | Harbor/Docker/Daytona routing with shared artifact contract |
