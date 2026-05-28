Minimum to understand:

| Concept | What it means |
|---|---|
| **Agent Card** | JSON document at `/.well-known/agent.json` — describes the agent's name, URL, capabilities, and skills |
| **Well-Known URI** | Standardized discovery path; any A2A client knows to look there first |
| **Task** | Unit of work: `POST /tasks` with a structured message, returns artifacts |
| **Artifact** | Structured output in a task response — contains `parts` with typed content |
| **Skill** | A declared capability of the agent (id, name, input/output modes) |
