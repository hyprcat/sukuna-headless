**Midsphere**

Midsphere is an agent platform for developers building AI agent features into their products.

Most platforms in this space ship one piece. Foundation labs ship managed runtimes — bring your own agent, they host it. Frameworks ship libraries — write your own agent loop and integrate everything around it yourself. Observability tools ship dashboards. Sandbox providers ship execution environments. Each solves a slice. The developer building an agent feature ends up integrating six vendors and writing the rest themselves.

Midsphere ships the assembled product.

The agent itself is built. A working multi-agent system handles planning, execution, recovery, multi-step reasoning, mid-run steering, and context management across long-running tasks. The developer doesn't write an agent loop. They configure what the agent should do and it runs.

The infrastructure is built. Sandboxing, durable execution, multi-tenancy, scaling, model routing, retries, artifact handling — all managed. The developer doesn't pick vendors or wire integrations.

The business layer is built. Per-user controls let the developer set credits, rate limits, sandbox time, concurrency caps, model tier access, tool access, and knowledge access for each end user or user tier. Wallets refresh on schedules the developer defines. Scoping and policies enforce what the agent is and isn't allowed to do at the context level. Scheduled execution lets agents run on cron-style schedules without user initiation, enabling weekly digests, monitoring agents, and daily prep workflows. Cost caps prevent runaway spend. Approval flows gate sensitive actions.

The observability is real, not just logs. An analytics agent reads session logs, ratings, costs, and usage patterns and surfaces specific insights the developer would otherwise miss — "47 of your users tried to attach files; you don't expose the capability," "73 of your free-tier users hit their cap without upgrading; your tier is too restrictive," "tasks of type X cost 8x more than average and have 60% lower satisfaction; something is failing silently." A 1-5 rating system the developer exposes to end users captures labeled quality data that flows back into the platform.

The definition surface is editable. Tools and knowledge live in a dashboard accessible to non-engineers — PMs, customer success, founders. They can iterate on agent behavior without going through a code change cycle.

The UI is shipped. A shadcn-style component library (`@midsphere/ui`) installs via CLI. Components copy into the developer's project. Streaming chat with agent steps. Run viewer for past executions. Artifact renderer. Rating widget. Cost meter. Approval prompt. Run status. History sidebar. Built on Tailwind, matches the developer's existing shadcn theme, no runtime lock-in.

The SDKs are first-class in TypeScript and Python. The TypeScript SDK includes streaming support, server action compatibility for Next.js App Router, edge runtime where possible, full type inference on tool definitions, a `useAgent` React hook that mirrors the patterns developers already know from Vercel AI SDK. The Python SDK has parity for backend and AI-stack developers.

The integration model is light. Midsphere accepts a user ID from the developer's existing auth system (Supabase Auth, Clerk, NextAuth, custom) and uses it as the key for per-user state. The developer's auth stays the source of truth. Midsphere doesn't connect to the developer's database — it stores its own state, keyed by IDs the developer chooses.

The pricing is prepaid credits. Free tier with $5–10 in starting credits to evaluate. Prepaid tiers from $20 to $500 with varying concurrency caps during early access. Enterprise plans available. No subscription. Credits don't expire.

The positioning is the same shape as Supabase for databases, Clerk for auth, Vercel for deployment. Each of those products replaced "a stack of libraries plus self-hosted infrastructure" with an opinionated, integrated platform that handles the hard parts so developers can focus on what's specific to their product. Midsphere does that for agents.

The buyer is any developer or team building an agent feature into their product. Solo founders shipping fast. Small teams adding AI features to existing products. Engineering teams at established companies who want to ship in weeks rather than build for months. The product is stack-agnostic — it works with whatever the developer has built — and ships specifically polished integrations for the modern web stack (Next.js, Supabase, shadcn, Vercel deployment).

The underlying technology stack: built on Exo, an open-source three-agent framework (Planner + Executor + Knowledge Manager) with file-based context management and self-spawning multi-agent swarms for handling large contexts. Firecracker microVM sandboxing. Multi-model routing internal to the platform. SOC 2 Type II compliance work in progress. GDPR compliant.

The product replaces what would otherwise be a 6-month engineering investment to build an agent platform, plus six vendor relationships to maintain, plus ongoing custom code to keep it working. The developer ships an agent feature in days instead of months and runs it as a real product with real visibility from day one.

Midsphere is the platform between an agent and its users — the agent itself, the infrastructure to run it, the controls to operate it as a business, the observability to improve it, and the UI to ship it.
