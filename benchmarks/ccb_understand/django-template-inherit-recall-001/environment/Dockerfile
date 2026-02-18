FROM python:3.11-slim

WORKDIR /workspace

RUN apt-get update && apt-get install -y \
    git \
    curl \
    npm \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN git clone --filter=blob:none --no-checkout https://github.com/django/django.git . && \
    git checkout 674eda1c03a3187905f48afee0f15226aa62fdf3 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Inject sparse HISTORY.md to simulate institutional memory loss
RUN cat > HISTORY.md << 'HISTORY'
# Template Engine Changes

## Recent Updates

- 2024-01: Refactored block handling (Alex - no longer with team)
- 2023-11: Fixed minor rendering issue
- 2023-09: Updated template loader
- 2023-06: Various fixes

No detailed documentation available for template internals.
Contact: Template team Slack channel (archived)
HISTORY

RUN git add HISTORY.md && git commit -m "update notes" --quiet
