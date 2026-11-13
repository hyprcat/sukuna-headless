# Developer Experience

## Onboarding
- Sign up at midsphere.com
- Create a workspace
- Free tier with $5-10 starting credits
- Either install SDK into existing app or clone create-midsphere-app starter

## SDK integration
- npm install @midsphere/sdk (or pip install midsphere)
- Initialize with workspace API key
- Three-line agent invocation: agent.run({ userId, prompt, tools, knowledge })
- Streaming response with progress events
- Optional useAgent React hook for Next.js

## Dashboard usage
- Configure agents, tools, knowledge
- Set per-user controls and tiers
- View session logs, run history, costs
- Read analytics agent insights
- Manage billing and credits
- Invite team members

## Component library usage
- npx @midsphere/ui add chat
- Components copy into developer's project
- Built on Tailwind, theme-matched with shadcn
- Imported and used as standard React components

## Auth integration
- Pass user ID from existing auth system on every agent invocation
- Optionally set per-user metadata via API or dashboard
- No database connection needed

## Per-user control management
- Set defaults per tier in dashboard
- Override per user via API or dashboard
- Updates take effect immediately

## Scheduled tasks
- Define schedule in dashboard or via SDK
- Failure handling, output routing configured at the schedule level
- Logs visible alongside on-demand runs

## Billing
- Top up credits via Dodo Payments (Merchant of Record)
- Credits don't expire
- Spend visibility per agent, per user, per day