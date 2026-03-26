# PropAI Prompt Library

Standalone system prompts for real estate AI agents. Drop any of these into Claude, ChatGPT, or your own tool.

Each prompt is designed for a specific role in the investment workflow. They are opinionated, specific, and built around how real investors actually work — not generic "real estate assistant" prompts.

## Available Prompts

| File | Agent Role | Best For |
|---|---|---|
| `acquisition_analyst.md` | Acquisition Analyst | Deal screening, quick underwriting, go/no-go decisions |
| `underwriting_analyst.md` | Underwriting Analyst | Deep financial modeling, DCF, sensitivity analysis |
| `due_diligence_analyst.md` | Due Diligence Analyst | T-12 review, rent roll analysis, red flag detection |
| `capital_stack_advisor.md` | Capital Stack Advisor | Debt structuring, mezz/pref equity, agency vs. bridge, 1031s |
| `asset_manager.md` | Asset Manager | Monthly reporting, NOI tracking, capex planning |
| `disposition_analyst.md` | Disposition Analyst | Exit strategy, timing, broker selection, net proceeds |
| `lp_relations.md` | LP Relations | Investor updates, distribution notices, capital calls |
| `development_analyst.md` | Development Analyst | Ground-up pro formas, construction draws, lease-up modeling |
| `market_analyst.md` | Market Analyst | Market research, comp analysis, rent trend analysis |

## The Full Investment Lifecycle

The prompts map to every stage of a deal:

```
SOURCE → SCREEN → UNDERWRITE → FINANCE → DUE DILIGENCE → CLOSE
                                                              ↓
                                                         ASSET MANAGE
                                                              ↓
                                                         DISPOSE → LP REPORT
```

| Stage | Prompt |
|---|---|
| Screen deals | `acquisition_analyst.md` |
| Model returns | `underwriting_analyst.md` |
| Research the market | `market_analyst.md` |
| Structure the capital stack | `capital_stack_advisor.md` |
| Catch seller manipulation | `due_diligence_analyst.md` |
| Manage the asset post-close | `asset_manager.md` |
| Plan and execute the exit | `disposition_analyst.md` |
| Communicate with investors | `lp_relations.md` |
| Evaluate ground-up projects | `development_analyst.md` |

## How to Use

1. Copy the contents of the prompt file
2. Paste as the **System Prompt** in Claude, ChatGPT, or your API call
3. Start your conversation — the agent will stay in character

## Tips

- These prompts work best when you provide real numbers. Don't ask the agent to guess.
- For deal analysis, paste the actual OM text or T-12 rather than summarizing it.
- The agents are calibrated to be direct and flag concerns — they won't just tell you what you want to hear.
- Combine prompts for complex tasks (e.g., use `due_diligence_analyst.md` + `underwriting_analyst.md` for a full underwrite with DD overlay).

## Contributing

Have a prompt that's working well in your workflow? Open a PR — see [CONTRIBUTING.md](../CONTRIBUTING.md).
