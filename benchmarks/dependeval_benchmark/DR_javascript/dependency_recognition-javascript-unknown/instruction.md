
## Code to Analyze

```
'FitnessApp/src/components/Card.js'
:import React from 'react'
import circlesImg from '../images/circles.png'
import emptyImg from '../images/empty.png'
import './styles/Card.css'

const Card = ({ title, description, img, leftColor, rightColor }) => (
    
    <div className="card mx-auto Fitness-Card"
    style={{
        backgroundImage: `url(${circlesImg}), linear-gradient(to right, ${leftColor || '#56CCF2'}  , ${rightColor|| '#2F80ED'}) `
    }}
    >
        <div className="card-body">
            <div className="row center">
                <div className="col-6">
                    <img src={img || emptyImg} className="float-right" alt="exercise"/>
                </div> 
                <div className="col-6 Fitness-Card-Info">
                    <h1>{title}</h1>
                    <p>{description}</p>
                </div>
            </div>
        </div>
    </div>
)

export default Card
'FitnessApp/src/components/ExerciseList.js'
:import React, { Fragment } from 'react'
import Card from './Card'

const ExerciseList = ({exercises}) => (
    <Fragment>
        { exercises.map((exercise) => (
            <Card 
                key={exercise.id}
                {...exercise}
            />
        ))}
    </Fragment>    
)


export default ExerciseList

```

# Dependency Recognition Task

## Problem Statement



## Task Description

Your task is to identify all dependencies in the given code. Analyze the codebase and determine which external libraries, modules, or packages are being used.

## Repository Information

- **Repository**: FitnessApp
- **Language**: javascript
- **File Path**: N/A

## Output Format

Write your answer to `/workspace/submission.json` as a JSON array of dependency names:

```json
["dependency1", "dependency2", "dependency3"]
```

### Requirements:

1. Include only direct dependencies (not transitive dependencies)
2. Use the exact package/module names as they appear in import statements
3. Order doesn't matter, but avoid duplicates
4. Return an empty array `[]` if there are no dependencies

### Example Output:

```json
["numpy", "pandas", "matplotlib"]
```

## Evaluation

Your submission will be evaluated using exact match. You must identify all dependencies correctly to receive full credit.

**Scoring**: 1.0 if all dependencies match exactly, 0.0 otherwise.

## Tips

- Look for import statements, require statements, or package declarations depending on the language
- Consider both standard library and third-party dependencies
- Pay attention to aliased imports (e.g., `import numpy as np` -> "numpy")
- For Python: check both `import X` and `from X import Y` statements
