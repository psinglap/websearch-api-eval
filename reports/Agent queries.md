# Agent queries — FINAL set (v2, 2026-10-08)

Each test is what a developer's agent sends to a search API. **Upstream task** = the human or system trigger. **Search call** = the exact query string the agent (LLM or code) sends, keyword-dense, with time and domain handled by parameters, one fact per call.
Pilot set (v1) archived in eval/out/pilot/. 17 search calls were rewritten from chat-style or feed-monitoring phrasing to agent-style calls; every use case keeps at least 4 real-time queries.

## GTM agent — Reo.dev-style signal agent working for LaserData (Apache Iggy / streaming infra)

| QID | Upstream task | Search call the agent sends | Params | What the agent needs back | Freshness |
|---|---|---|---|---|---|
| G1 | Find developers hitting Kafka latency problems right now | `kafka consumer lag high latency issue` | window last ~6 h (tightest available), domains: github.com | Issue URLs opened in the last 6 hours, repo/org, time, the error described | real-time |
| G2 | Account signal: anything new at Confluent today? | `Confluent news` | window 24h | Headline, date, link - or "none" in the last 24h | real-time |
| G3 | Any new mentions of Apache Iggy in the last day? | `"Apache Iggy"` | window 24h | Every mention (repo, blog, forum) in 24h, date - or "none" | real-time |
| G4 | Draft a note on Apache Iggy's latest release for a prospect | `Apache Iggy release notes` | window 7 days, domains: github.com, iggy.apache.org | Latest release version, date, key changes, link | week |
| G5 | Coding agent fixing a consumer-lag bug needs the official tuning guidance | `kafka consumer lag max.poll.records fetch.min.bytes` | window 1 year, domains: kafka.apache.org, docs.confluent.io | Official doc URL, what each setting does, recommended direction | year |
| G6 | Competitive brief: what's the latest NATS server release? | `NATS server release` | window 7 days, domains: github.com | Version, release date, link | week |
| G7 | Is Confluent Cloud having an incident right now? (outage = switching trigger) | `Confluent Cloud incident` | window 24h, domains: status.confluent.cloud | Active incident yes/no, component, start time - or "none" | real-time |
| G8 | Which AI-agent / data-infra startups just raised money? | `AI agent infrastructure startup funding round` | window 48h | Company, amount, lead investor, date, link | 48h |
| G9 | Find this week's content about memory/event logs for AI agents | `durable event log memory for AI agents` | window 7 days | Article URLs, author/org, date | week |
| G10 | Competitive brief: published Redpanda vs Kafka latency benchmarks | `Redpanda vs Kafka p99 latency benchmark` | window 1 year | Benchmark source, date, p99 numbers, who ran it | year |

## Insurance agent — Liberate-style voice + claims agent for P&C insurers

| QID | Upstream task | Search call the agent sends | Params | What the agent needs back | Freshness |
|---|---|---|---|---|---|
| I1 | Caller wants a new Florida homeowners policy | `Citizens Property Insurance binding suspension Florida` | window 24h, domains: citizensfla.com | Suspended yes/no, scope, effective date/time | real-time |
| I2 | Caller in Pensacola asks if the storm is coming | `Hurricane Isaias latest advisory NHC` | window 24h | Advisory #, time, location, max winds, landfall forecast | real-time |
| I3 | Agent must check warnings for the policy's county before binding | `hurricane warning Escambia County Florida active` | window 24h | Active warning types, issued time | real-time |
| I4 | Claims agent validating a wind-damage report in progress | `Pensacola weather wind speed` | window 24h | Current wind speed/gusts, observation time | real-time |
| I5 | Policyholder asks if they must evacuate | `Baldwin County Alabama evacuation order Isaias` | window 24h | Order in effect yes/no, zones, time | real-time |
| I6 | Claims ops checks whether federal aid applies | `FEMA disaster declaration Hurricane Isaias 2026` | window 48h | Declaration number + date - or "none yet" (beware older "Isaias") | 48h |
| I7 | Compliance agent checks for new regulator orders | `Florida OIR OR Alabama DOI emergency order Isaias insurance` | window 48h | Order/bulletin, issuer, date - or "none" | 48h |
| I8 | Underwriting checks which states declared emergencies | `governor state of emergency Hurricane Isaias` | window 7 days | States, date of each declaration | week |
| I9 | Claims agent validating a Texas hail claim | `Texas hail storm reports` | window 24h, domains: spc.noaa.gov | Locations, dates, hail size - or "none" | 24h |
| I10 | Caller asks whether their 2024 Toyota RAV4 has an open recall | `NHTSA recall 2024 Toyota RAV4` | window 1 year, domains: nhtsa.gov | Recall campaign number(s), component, date | year |

## Finance agent — Rogo-style analyst agent for banks / PE

| QID | Upstream task | Search call the agent sends | Params | What the agent needs back | Freshness |
|---|---|---|---|---|---|
| F1 | Where is NVIDIA trading? | `NVDA stock price` | window 24h | Price, % change, timestamp | real-time |
| F2 | Where's the 10-year? | `US 10-year Treasury yield` | window 24h | Yield %, timestamp | real-time |
| F3 | Bitcoin price? | `BTC USD price` | window 24h | Price, timestamp | real-time |
| F4 | How's oil moving today? | `WTI crude oil price` | window 24h | Price, change, timestamp | real-time |
| F5 | What did jobless claims print? | `initial jobless claims weekly report` | window 24h, domains: dol.gov | Number, week ending, release time | real-time |
| F6 | Summarize the latest Fed minutes | `FOMC minutes` | window 7 days, domains: federalreserve.gov | Release date, 3 key points, federalreserve.gov link | week |
| F7 | List $1B+ M&A deals announced in the last two days | `definitive agreement to acquire billion` | window 48h | Acquirer, target, value, date, source | 48h |
| F8 | Monitoring account Stryker: what did its latest 8-K report? | `Stryker 8-K item 5.02` | window 7 days, domains: sec.gov | Filing date, items, what changed (officer/director), EDGAR link | week |
| F9 | Analyst asks about the Chilwa Minerals listing | `Chilwa Minerals IPO price per share` | window 7 days | IPO price, ticker, exchange, pricing date | week |
| F10 | When does JPMorgan report Q3? | `JPMorgan third quarter 2026 earnings release date` | window 7 days | Date, time of release and call | week (upcoming) |
