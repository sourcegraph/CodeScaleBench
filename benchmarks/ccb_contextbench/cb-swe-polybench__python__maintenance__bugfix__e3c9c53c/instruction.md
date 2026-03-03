# Fix: SWE-PolyBench__python__maintenance__bugfix__e3c9c53c

**Repository:** huggingface/transformers
**Language:** python
**Category:** contextbench_cross_validation

## Description

the `tokenize_chinese_chars` argument is not always taken into account with the fast version of the bert tokenizer
## Environment info
<!-- You can run the command `transformers-cli env` and copy-and-paste its output below.
     Don't forget to fill out the missing fields in that output! -->

- `transformers` version: 4.16.0.dev0
- Platform: Linux-5.11.0-46-generic-x86_64-with-glibc2.17
- Python version: 3.8.12
- PyTorch version (GPU?): 1.10.1+cu102 (False)
- Tensorflow version (GPU?): 2.7.0 (False)
- Flax version (CPU?/GPU?/TPU?): 0.3.6 (cpu)
- Jax version: 0.2.26
- JaxLib version: 0.1.75
- Using GPU in script?: no
- Using distributed or parallel set-up in script?: no

### Who can help
<!-- Your issue will be replied to more quickly if you can figure out the right person to tag with @
 If you know how to use git blame, that is the easiest way, otherwise, here is a rough guide of **who to tag**.
 Please tag fewer than 3 people.

Models:

- ALBERT, BERT, XLM, DeBERTa, DeBERTa-v2, ELECTRA, MobileBert, SqueezeBert: @LysandreJik
- T5, BART, Marian, Pegasus, EncoderDecoder: @patrickvonplaten
- Blenderbot, MBART: @patil-suraj
- Longformer, Reformer, TransfoXL, XLNet, FNet, BigBird: @patrickvonplaten
- FSMT: @stas00
- Funnel: @sgugger
- GPT-2, GPT: @patrickvonplaten, @LysandreJik
- RAG, DPR: @patrickvonplaten, @lhoestq
- TensorFlow: @Rocketknight1
- JAX/Flax: @patil-suraj
- TAPAS, LayoutLM, LayoutLMv2, LUKE, ViT, BEiT, DEiT, DETR, CANINE: @NielsRogge
- GPT-Neo, GPT-J, CLIP: @patil-suraj
- Wav2Vec2, HuBERT, SpeechEncoderDecoder, UniSpeech, UniSpeechSAT, SEW, SEW-D, Speech2Text: @patrickvonplaten, @anton-l

If the model isn't in the list, ping @LysandreJik who will redirect you to the correct contributor.

Library:

- Benchmarks: @patrickvonplaten
- Deepspeed: @stas00
- Ray/raytune: @richardliaw, @amogkam
- Text generation: @patrickvonplaten @narsil
- Tokenizers: @SaulLu
- Trainer: @sgugger
- Pipelines: @Narsil
- Speech: @patrickvonplaten, @anton-l
- Vision: @NielsRogge, @sgugger

Documentation: @sgugger

Model hub:

- for issues with a model, report at https://discuss.huggingface.co/ and tag the model's creator.

HF projects:

- datasets: [different repo](https://github.com/huggingface/datasets)
- rust tokenizers: [different repo](https://github.com/huggingface/tokenizers)

Examples:

- maintained examples (not research project or legacy): @sgugger, @patil-suraj

For research projetcs, please ping the contributor directly. For example, on the following projects:

- research_projects/bert-loses-patience: @JetRunner
- research_projects/distillation: @VictorSanh

 -->

## Information

Model I am using (Bert, XLNet ...):

The problem arises when using:
* [x] the official example scripts: (give details below)
* [ ] my own modified scripts: (give details below)

The tasks I am working on is:
* [ ] an official GLUE/SQUaD task: (give the name)
* [ ] my own task or dataset: (give details below)

## To reproduce

Steps to reproduce the behavior:

```python
from transformers import BertTokenizer, BertTokenizerFast

list_of_commun_chinese_char = ["的", "人", "有"]
text = "".join(list_of_commun_chinese_char)
print(text)
# 的人有

model_name = "bert-base-uncased"

tokenizer_slow = BertTokenizer.from_pretrained(model_name, tokenize_chinese_chars=False)
tokenizer_slow.tokenize(text)
# ['的', '##人', '##有']

tokenizer_slow = BertTokenizer.from_pretrained(model_name, tokenize_chinese_chars=True)
tokenizer_slow.tokenize(text)
# ['的', '人', '有']

tokenizer_fast = BertTokenizerFast.from_pretrained(model_name, tokenize_chinese_chars=False)
tokenizer_fast.tokenize(text)
# ['的', '人', '有']


tokenizer_fast = BertTokenizerFast.from_pretrained(model_name, tokenize_chinese_chars=True)
tokenizer_fast.tokenize(text)
# ['的', '人', '有']
```

<!-- If you have code snippets, error messages, stack traces please provide them here as well.
     Important! Use code tags to correctly format your code. See https://help.github.com/en/github/writing-on-github/creating-and-highlighting-code-blocks#syntax-highlighting
     Do not use screenshots, as they are hard to read and (more importantly) don't allow others to copy-and-paste your code.-->

## Expected behavior
If the user indicates `tokenize_chinese_chars=False` when he initializes a fast bert tokenizer, we expect that this characteristic is reflected on the tokenizer. In other words, in the previous example, we expect that:

```python
tokenizer_fast = BertTokenizerFast.from_pretrained(model_name, tokenize_chinese_chars=False)
tokenizer_fast.tokenize(text)
# ['的', '##人', '##有']
```


## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
