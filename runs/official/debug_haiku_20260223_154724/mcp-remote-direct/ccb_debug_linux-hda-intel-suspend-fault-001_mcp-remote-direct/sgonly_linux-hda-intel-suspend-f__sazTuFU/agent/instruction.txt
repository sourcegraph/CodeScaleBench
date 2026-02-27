# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-benchmarks/linux--07c4ee00`
- Use `repo:^github.com/sg-benchmarks/linux--07c4ee00$` filter in keyword_search
- Use `github.com/sg-benchmarks/linux--07c4ee00` as the `repo` parameter for go_to_definition/find_references/read_file


## Required Workflow

1. **Search first** — Use MCP tools to find relevant files and understand existing patterns
2. **Read remotely** — Use `sg_read_file` to read full file contents from Sourcegraph
3. **Edit locally** — Use Edit, Write, and Bash to create or modify files in your working directory
4. **Verify locally** — Run tests with Bash to check your changes

## Tool Selection

| Goal | Tool |
|------|------|
| Exact symbol/string | `sg_keyword_search` |
| Concepts/semantic search | `sg_nls_search` |
| Trace usage/callers | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Read full file | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

**Decision logic:**
1. Know the exact symbol? → `sg_keyword_search`
2. Know the concept, not the name? → `sg_nls_search`
3. Need definition of a symbol? → `sg_go_to_definition`
4. Need all callers/references? → `sg_find_references`
5. Need full file content? → `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search → read → references → definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms
- Read 2-3 related files before synthesising, rather than one at a time
- Don't read 20+ remote files without writing code — once you understand the pattern, start implementing

## If Stuck

If MCP search returns no results:
1. Broaden the search query (synonyms, partial identifiers)
2. Try `sg_nls_search` for semantic matching
3. Use `sg_list_files` to browse the directory structure
4. Use `sg_list_repos` to verify the repository name

---

# Fault Localization: HDA Intel Sound Fails After Suspend to RAM

- **Repository**: github.com/sg-benchmarks/linux--07c4ee00 (mirror of torvalds/linux)
- **Kernel Version**: 3.7.6
- **Difficulty**: expert
- **Category**: fault_localization
- **Subsystem**: Drivers
- **Component**: Sound (HDA Intel)

## Bug Report

**Bug ID**: 53441
**Summary**: hda_intel: sound stops working after suspend to ram
**Regression**: Yes (works on v3.6.11, broken since v3.7.1)

On a fresh boot the sound card works fine. After a few suspends to ram (it doesn't necessarily happen after just one) the sound card stops working well. The sound comes out choppy, as a series of clicks separated by 2 second or so silences.

I see these messages in the kernel log right after resume:
```
hda-intel: azx_get_response timeout, switching to polling mode: last cmd=0x00170503
hda-intel: No response from codec, disabling MSI: last cmd=0x00170503
hda_intel: azx_get_response timeout, switching to single_cmd mode: last cmd=0x00170503
```

The only way to fix the sound seems to be a reboot. I don't have this problem with v3.6.11, it appeared with kernel v3.7.1 (I have not tested v3.7). Right now I'm running 3.7.6 and the problem is still there.

```
$ lspci | grep -i audio
00:1b.0 Audio device: Intel Corporation 5 Series/3400 Series Chipset High Definition Audio (rev 05)
01:00.1 Audio device: NVIDIA Corporation High Definition Audio Controller (rev a1)

$ lsmod | grep snd
snd_hda_codec_hdmi     24993  4
snd_hda_codec_idt      54740  1
snd_hda_intel          24840  6
snd_hda_codec          71155  3 snd_hda_codec_hdmi,snd_hda_codec_idt,snd_hda_intel
snd_pcm                74322  3 snd_hda_codec_hdmi,snd_hda_codec,snd_hda_intel
snd_page_alloc          7333  2 snd_pcm,snd_hda_intel
snd_timer              17563  1 snd_pcm
```

## Task

You are a fault localization agent. Given the bug report above, your task is to identify the **exact source file(s)** and **function(s)/data structure(s)** in the Linux kernel source tree (at `/workspace`) that need to be modified to fix this bug.

You must:
1. Analyze the bug report to understand the symptoms and context
2. Search the kernel source code to identify the relevant subsystem and files
3. Narrow down to the specific file(s) and function(s)/data structure(s) that contain the bug or need modification
4. Write your findings to `/workspace/fault_localization_result.json` in the following format:

```json
{
  "buggy_files": ["path/to/file.c"],
  "buggy_functions": ["function_or_struct_name"],
  "confidence": 0.8,
  "reasoning": "Brief explanation of why these locations are the fault"
}
```

**Important**: Paths should be relative to the kernel source root (e.g., `kernel/sched/core.c`, not `/workspace/kernel/sched/core.c`).

## Success Criteria

- [ ] Correctly identify the buggy file(s)
- [ ] Correctly identify the buggy function(s) or data structure(s)
- [ ] Write results to `/workspace/fault_localization_result.json`
- [ ] Provide reasoning for the localization

## Testing

- **Time limit**: 1800 seconds
- Run `bash /tests/test.sh` to verify your findings
