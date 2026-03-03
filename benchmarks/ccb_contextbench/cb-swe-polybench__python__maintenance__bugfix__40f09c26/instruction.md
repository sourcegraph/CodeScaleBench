# Fix: SWE-PolyBench__python__maintenance__bugfix__40f09c26

**Repository:** huggingface/transformers
**Language:** python
**Category:** contextbench_cross_validation

## Description

Issue with Adding New Tokens to ESM2 Model Tokenizer
Hello

I am encountering an issue while working with the ESM2 models (`facebook/esm2_t6_8M_UR50D`). Specifically, when I try to add new tokens to the tokenizer, they are automatically classified as special tokens, even though I am specifying `special_tokens=False`.

Here is the code snippet I am using:

```python
model_checkpoint = "facebook/esm2_t6_8M_UR50D"
model = AutoModelForMaskedLM.from_pretrained(model_checkpoint)
tokenizer = AutoTokenizer.from_pretrained(model_checkpoint)
num_added_toks = tokenizer.add_tokens(['J'], special_tokens=False)
print("We have added", num_added_toks, "tokens")
model.resize_token_embeddings(len(tokenizer))
```

After executing this code, the new token ('J') is added as a special token, which is not the intended behavior. This behavior is different compared to when I use similar code with BERT models, where new tokens are added as expected without being automatically marked as special.

The vocab output is below:
```python
<bound method EsmTokenizer.get_vocab of EsmTokenizer(name_or_path=‘facebook/esm2_t6_8M_UR50D’, vocab_size=33, model_max_length=1024, is_fast=False, padding_side=‘right’, truncation_side=‘right’, special_tokens={‘eos_token’: ‘’, ‘unk_token’: ‘’, ‘pad_token’: ‘’, ‘cls_token’: ‘’, ‘mask_token’: ‘’, ‘additional_special_tokens’: [‘J’]}, clean_up_tokenization_spaces=True), added_tokens_decoder={
0: AddedToken(“”, rstrip=False, lstrip=False, single_word=False, normalized=False, special=True),
1: AddedToken(“”, rstrip=False, lstrip=False, single_word=False, normalized=False, special=True),
2: AddedToken(“”, rstrip=False, lstrip=False, single_word=False, normalized=False, special=True),
3: AddedToken(“”, rstrip=False, lstrip=False, single_word=False, normalized=False, special=True),
32: AddedToken(“”, rstrip=False, lstrip=False, single_word=False, normalized=False, special=True),
33: AddedToken(“J”, rstrip=False, lstrip=False, single_word=False, normalized=False, special=True),
}>
```
My main problem is that I noticed the **length of the tokenizer** does not change after adding the new token and therefore the above code does not extend the embeddings layer as expected.

I'm seeking guidance or a workaround for this issue. Is this a known issue with the ESM2 tokenizer, or am I missing something in my implementation?

Any help or insight into this matter would be greatly appreciated.

Thank you!



## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
