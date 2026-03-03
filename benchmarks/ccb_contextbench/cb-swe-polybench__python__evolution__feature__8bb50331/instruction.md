# Fix: SWE-PolyBench__python__evolution__feature__8bb50331

**Repository:** huggingface/transformers
**Language:** python
**Category:** contextbench_cross_validation

## Description

The new impl for CONFIG_MAPPING prevents users from adding any custom models
## Environment info
<!-- You can run the command `transformers-cli env` and copy-and-paste its output below.
     Don't forget to fill out the missing fields in that output! -->

- `transformers` version: 4.10+
- Platform: Ubuntu 18.04
- Python version: 3.7.11
- PyTorch version (GPU?): N/A
- Tensorflow version (GPU?): N/A
- Using GPU in script?: N/A
- Using distributed or parallel set-up in script?: No.

### Who can help
<!-- Your issue will be replied to more quickly if you can figure out the right person to tag with @
 If you know how to use git blame, that is the easiest way, otherwise, here is a rough guide of **who to tag**.
 Please tag fewer than 3 people.
 -->


## Information

Model I am using (Bert, XLNet ...): _Custom_ model

The problem arises when using:
* [ ] the official example scripts: (give details below)
* [x] my own modified scripts: (give details below)

The tasks I am working on is:
* [x] an official GLUE/SQUaD task: (give the name)
* [ ] my own task or dataset: (give details below)

## To reproduce

See: https://github.com/huggingface/transformers/blob/010965dcde8ce9526f6a7e6e2c3f36276c153708/src/transformers/models/auto/configuration_auto.py#L297

This was changed from the design in version `4.9` which used an `OrderedDict` instead of the new `_LazyConfigMapping`. The current design makes it so users cannot add their own custom models by assigning names and classes to the following registries (example: classification tasks):

- `CONFIG_MAPPING` in `transformers.models.auto.configuration_auto`, and
- `MODEL_FOR_SEQUENCE_CLASSIFICATION_MAPPING` in `transformers.models.auto.modeling_auto`.

<!-- If you have code snippets, error messages, stack traces please provide them here as well.
     Important! Use code tags to correctly format your code. See https://help.github.com/en/github/writing-on-github/creating-and-highlighting-code-blocks#syntax-highlighting
     Do not use screenshots, as they are hard to read and (more importantly) don't allow others to copy-and-paste your code.-->

## Expected behavior

Either a mechanism to add custom `Config`s (and the corresponding models) with documentation for it, or documentation for whatever other recommended method. Possibly that already exists, but I haven't found it yet.

<!-- A clear and concise description of what you would expect to happen. -->

@sgugger 


## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
