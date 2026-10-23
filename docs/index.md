# GoliathApp

GoliathApp is the general-purpose enterprise platform. Role-based access control and a database workflow engine are the core. User-defined actions implement workflows. A REST gateway enrolls distributed workers and hands them those actions.

Specialized applications extend it with their own actions, profiles, and worker handlers. This repository is the platform those applications build on. It does not depend on them.

## In this site

- [Platform](platform.md) — schemas, processes, and what this tree contains
- [Workflow compiler](workflow-compiler.md) — DomainProgram JSON lowered to a workflow graph
- [Workflow engine](workflow-engine.md) — PostgreSQL and Azure SQL runtime
- [Actions](actions.md) — user-defined actions and data types
- [Workers](workers.md) — enrollment, claim, and fleet control
- [RBAC](rbac.md) — users, roles, scopes, and the portal façade
- [Semantic layer](semantic-layer.md) — portal registry, Exograph façade, and cross-schema reads
- [Pipeline profiles](pipeline-profiles.md) — scope flags for workflow branches
- [Schema apply](schema-apply.md) — ordered, re-runnable `sql_pg` apply
- [Repository layout](workspace-index.md) — directories in this tree

The GitHub README is the short entry point. This site is built with MkDocs Material from `docs/` and published from `main`.
