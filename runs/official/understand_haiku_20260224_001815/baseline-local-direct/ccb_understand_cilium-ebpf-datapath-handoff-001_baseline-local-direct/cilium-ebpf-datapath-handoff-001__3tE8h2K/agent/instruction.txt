# Team Handoff: Cilium eBPF Datapath Subsystem

## Scenario

You are taking over ownership of Cilium's eBPF datapath subsystem from a departing team member. The eBPF datapath is the core of Cilium's networking and security capabilities, responsible for loading eBPF programs into the kernel, enforcing network policies, and implementing service mesh functionality.

Your team member has left limited documentation. Your task is to explore the codebase and produce a comprehensive handoff document that will help you and future team members understand, maintain, and extend the eBPF datapath system.

## Your Task

Explore the cilium/cilium codebase and create a structured handoff document covering the eBPF datapath subsystem. Your document should address the following sections:

### 1. Purpose
- What problem does the eBPF datapath solve in Cilium's architecture?
- Why does Cilium use eBPF instead of traditional iptables or userspace networking?
- What are the key responsibilities of the datapath subsystem?
- How does the datapath integrate with Kubernetes networking?

### 2. Dependencies
- What other Cilium subsystems does the datapath interact with?
- What are the upstream dependencies (what calls into the datapath)?
- What are the downstream dependencies (what does the datapath call)?
- How does the Go code interact with the C eBPF programs?
- What kernel APIs does the datapath rely on?

### 3. Relevant Components
- What are the main source files and directories for the datapath subsystem?
- Where is the eBPF loader implemented?
- Where are the eBPF C programs located?
- Where is the policy enforcement logic implemented?
- Where are the eBPF maps managed?
- What files are critical for understanding how eBPF programs are compiled, loaded, and updated?

### 4. Failure Modes
- What can go wrong with eBPF program loading?
- How does the system handle eBPF verifier failures?
- What happens when eBPF maps are full or can't be updated?
- How are kernel compatibility issues detected and handled?
- What are common configuration errors and how are they detected?
- How does the system recover from eBPF program failures or kernel panics?

### 5. Testing
- How is the eBPF datapath tested?
- What test patterns are used for eBPF programs?
- Where are the datapath tests located?
- How do you test policy enforcement without a full cluster?
- What integration tests exist for the datapath?
- How are eBPF programs validated before loading?

### 6. Debugging
- How do you troubleshoot eBPF program loading failures?
- How do you inspect eBPF maps at runtime?
- What tools are available for debugging eBPF programs (bpftool, cilium monitor, etc.)?
- How do you verify that policies are being enforced correctly?
- What logs or metrics help diagnose datapath issues?
- How do you investigate performance problems in the datapath?

### 7. Adding a New Hook
- If you needed to add a new eBPF hook point (e.g., for a new protocol or policy type), what would be the step-by-step process?
- What eBPF program types can be used?
- What files need to be created or modified (C programs, Go loader code)?
- How do you integrate a new hook with the existing policy engine?
- How is a new hook registered and attached to network interfaces?

## Deliverable

Create your handoff document as a markdown file at `/logs/agent/onboarding.md`.

Deliver a clear, well-structured document that covers all requested sections. Include:
- Specific file paths and directory names
- Key function/type names
- Code flow descriptions
- Concrete examples where helpful
- Architecture diagrams in text/ASCII if helpful

## Evaluation

Your handoff document will be evaluated on:
- **Completeness**: All 7 sections addressed with substantive content
- **Accuracy**: Correct identification of relevant components, interfaces, and architectural patterns
- **Specificity**: Concrete file paths, type names, and code references (not generic descriptions)
- **Understanding**: Demonstrates comprehension of how the eBPF datapath works, including the Go+C boundary
- **Depth**: Goes beyond surface-level file listing to explain how components interact and why design decisions were made

Good luck with your exploration!
