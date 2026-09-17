# ADR-003: Provider-Neutral Model Interface and Router

## Status
Accepted

## Context
Agent frameworks frequently hard-code dependencies on a specific vendor's SDK (such as OpenAI, Anthropic, or Google GenAI) directly into prompt generation, chain execution, or tool calling loops. This creates vendor lock-in, complicates offline testing, and prevents dynamic model switching based on latency, cost, task complexity, or privacy preferences.

## Decision
We establish a strict, provider-neutral model layer in `app.models`:
1. **Domain DTOs:**
   - `ModelRequest`: Contains normalized messages, temperature, max_tokens, and tool schemas.
   - `ModelResponse`: Contains normalized content, structured `tool_calls`, usage statistics, and finish reason.
   - `ToolCallRequest`: Represents a normalized tool invocation request (`id`, `name`, `arguments`).
2. **Abstract Interface:**
   - `ModelProvider`: Defines `async def generate(request: ModelRequest) -> ModelResponse`.
3. **Concrete Adapters:**
   - `MockModelProvider`: Deterministic, programmable provider for fast, reliable unit and integration tests without network I/O or token spend.
   - `OpenAICompatibleProvider`: Standard HTTP client adapter supporting OpenAI, Azure OpenAI, Ollama, vLLM, and LMStudio endpoints.
   - Future adapters (e.g., `GeminiProvider`, `AnthropicProvider`) will implement `ModelProvider` without touching orchestrator code.
4. **ModelRouter:**
   - The Orchestrator interacts exclusively with `ModelRouter`.
   - The router selects the appropriate provider based on model configuration, task requirements, or environment settings.

## Consequences
### Positive
- Zero provider-specific APIs leaked into orchestrator or agent logic.
- 100% deterministic, offline automated testing using `MockModelProvider`.
- Ability to switch from cloud models to private local LLMs (via Ollama/vLLM) via environment variables alone.

### Negative / Trade-offs
- Requires maintaining an adapter layer that maps provider-specific JSON formats into AURA's normalized schemas.
