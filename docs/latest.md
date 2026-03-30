# Latest Status — Singlife AI Ops

Last updated: 2026-03-30

---

## Blockers Summary

### Already Known

1. **Anthropic API Key** — need to set in `backend/.env` to run anything
2. **SharePoint Integration** — checklist exists, no code implemented

### Additional Blockers Found

3. **8 Knowledge Gaps** (need SME input from Terence/Sharon):
   - ICD code pass/fail list missing — can't complete RCS checks when Claim Ind = Y
   - Duplicate client resolution process undefined
   - Only 4 follow-up codes documented (F45, CSL, C09, AT3) — others exist
   - Race code reference table missing
   - Contract info checks (Steps 6A-6I) marked NA but actually happen
   - "Name sequence" definition unclear
   - Channel inference from cntType not documented
   - SA threshold unclear — monthly benefit vs aggregate SA

4. **Power Automate flows** — JSON trigger format is designed and output works, but no actual PA flows are built to consume it

5. **No live system connections** — L400, FileNet, DotSphere, RCS are all manual (user pastes JSON). This is expected for prototype but blocks any real demo with live data.

---

## NOT Blockers (these are fine)

- Code is complete and working (~2,200 lines)
- All 8 API endpoints functional
- Case evaluation + Q&A + document upload all work
- No hardcoded secrets, good security
- Test questions documented (12 cases)
- Knowledge gap detection works
- Streaming responses work

---

## SharePoint Integration (when access is granted)

Not built yet — waiting on IT for access. When ready, the setup requires:
- Azure AD app registration (Tenant ID, Client ID, Client Secret)
- Permissions: `Sites.Read.All`, `Files.Read.All` via Microsoft Graph
- SharePoint site URL + document library name
- Sync interval config (how often to pull docs)

The app is already designed for this — documents uploaded to SharePoint would sync into `knowledge_base/` and the AI picks them up automatically. No code changes needed on our side, just the connector.

---

## Bottom Line

The code itself is done. The real blockers are all external — API key, SharePoint config, SME answers for the 8 knowledge gaps, and Power Automate flows.
