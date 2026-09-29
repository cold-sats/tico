# Glossary

- **Employee**: a persistent AI role with its own repo, memory, and software. Not a model session.
- **Hub**: this repo. Shared knowledge and the single work queue.
- **Run**: one dispatcher-launched session of an employee against one Issue.
- **Handoff**: delegating work by opening a child Issue and setting the parent to waiting.
- **Session**: the model conversation an employee is currently resuming. Disposable.
- **state.md**: an employee's own note of what it is doing and what to pick up next.
