
## Code to Analyze

```
'ProviGen/ProviGenTests/src/com/tjeannin/provigen/test/multiple/MultipleContractContentTest.java'
:package com.tjeannin.provigen.test.multiple;

import android.test.mock.MockContentResolver;
import com.tjeannin.provigen.test.ExtendedProviderTestCase;
import com.tjeannin.provigen.test.multiple.MultipleContractContentProvider.ContractOne;
import com.tjeannin.provigen.test.multiple.MultipleContractContentProvider.ContractTwo;

public class MultipleContractContentTest extends ExtendedProviderTestCase<MultipleContractContentProvider> {

    private MockContentResolver contentResolver;

    public MultipleContractContentTest() {
        super(MultipleContractContentProvider.class, "com.test.simple");
    }

    @Override
    protected void setUp() throws Exception {
        super.setUp();
        contentResolver = getMockContentResolver();
    }

    public void testMultipleContractInsertDontOverlap() {


        assertEquals(0, getRowCount(ContractOne.CONTENT_URI));
        assertEquals(0, getRowCount(ContractTwo.CONTENT_URI));

        contentResolver.insert(ContractTwo.CONTENT_URI, getContentValues(ContractTwo.class));

        assertEquals(0, getRowCount(ContractOne.CONTENT_URI));
        assertEquals(1, getRowCount(ContractTwo.CONTENT_URI));

        contentResolver.insert(ContractOne.CONTENT_URI, getContentValues(ContractOne.class));

        assertEquals(1, getRowCount(ContractOne.CONTENT_URI));
        assertEquals(1, getRowCount(ContractTwo.CONTENT_URI));
    }

    public void testAddingAnotherContractLater() {

        contentResolver.insert(ContractOne.CONTENT_URI, getContentValues(ContractOne.class));
        assertEquals(1, getRowCount(ContractOne.CONTENT_URI));

        resetContractClasses(new Class[]{ContractTwo.class, ContractOne.class});
        assertEquals(0, getRowCount(ContractTwo.CONTENT_URI));
        assertEquals(1, getRowCount(ContractOne.CONTENT_URI));

        contentResolver.insert(ContractTwo.CONTENT_URI, getContentValues(ContractTwo.class));
        assertEquals(1, getRowCount(ContractTwo.CONTENT_URI));
        assertEquals(1, getRowCount(ContractOne.CONTENT_URI));

        contentResolver.insert(ContractOne.CONTENT_URI, getContentValues(ContractOne.class));
        assertEquals(1, getRowCount(ContractTwo.CONTENT_URI));
        assertEquals(2, getRowCount(ContractOne.CONTENT_URI));
    }
}

```

# Repository Construction Task

## Problem Statement



## Task Description

Your task is to build a call chain graph that represents the function invocation relationships across the repository. Analyze the code to understand how functions call each other and construct a directed graph representation.

## Repository Information

- **Repository**: N/A
- **Language**: java

## Output Format

Write your answer to `/workspace/submission.json` as a JSON object representing the call graph:

```json
{
  "function1": ["function2", "function3"],
  "function2": ["function4"],
  "function3": [],
  "function4": []
}
```

### Structure:

- **Keys**: Function names (callers)
- **Values**: Arrays of function names that are called by the key function (callees)
- **Empty arrays**: Functions that don't call any other functions
- **Isolated nodes**: Include functions that are never called but exist in the repository

### Alternative Format (List of Edges):

You can also use an edge list format:

```json
[
  {"caller": "function1", "callee": "function2"},
  {"caller": "function1", "callee": "function3"},
  {"caller": "function2", "callee": "function4"}
]
```

## Evaluation

Your submission will be evaluated using graph similarity metrics:

- **Node F1**: Precision and recall of identified functions (15% weight)
- **Edge F1**: Precision and recall of call relationships (85% weight)
- **Final Score**: 0.15 × Node_F1 + 0.85 × Edge_F1

The evaluation emphasizes getting the call relationships correct over identifying all functions.

## Tips

- Focus on accurately identifying which functions call which
- Include all functions in the repository, even if they have no outgoing calls
- Pay attention to indirect calls through variables or callbacks
- Consider method calls on objects and class methods
- Cross-file function calls are especially important
