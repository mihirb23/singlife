# SharePoint Setup — What I Need From You

Hey! So we're hooking up our AI assistant to SharePoint so it can automatically grab documents and use them as its knowledge base. I need a few things set up on the Azure/SharePoint side — just follow the steps below and send me back the values at the end.

Shouldn't take more than 10–15 minutes if you've got admin access.

---

## 1. Register an app in Azure

We need this so our backend can talk to SharePoint securely.

1. Head to [portal.azure.com](https://portal.azure.com)
2. Go to **Azure Active Directory** → **App registrations** → **New registration**
3. Set it up like this:
   - **Name**: `Singlife AI Connector` (or whatever you fancy)
   - **Supported account types**: Single tenant (just our org)
   - **Redirect URI**: leave it blank, we don't need it
4. Hit **Register**

Once it's registered, you'll land on the overview page. Grab these three things:

| What | Where |
|------|-------|
| Tenant ID | Overview page → "Directory (tenant) ID" |
| Client ID | Overview page → "Application (client) ID" |
| Client Secret | Go to **Certificates & secrets** → **New client secret** → copy the **Value** straight away (it only shows once!) |

Then we need to sort out permissions:

1. Go to **API permissions** → **Add a permission**
2. Pick **Microsoft Graph** → **Application permissions**
3. Search for and tick these two:
   - `Sites.Read.All`
   - `Files.Read.All`
4. Hit **Grant admin consent** (you'll need admin rights for this — if you haven't got them, ask whoever does)

### Quick checklist for this bit:

- [ ] App registered
- [ ] Got the Tenant ID
- [ ] Got the Client ID
- [ ] Got the Client Secret (the value, not the secret ID — they're different!)
- [ ] Both permissions added
- [ ] Admin consent granted (should show green ticks next to the permissions)

---

## 2. SharePoint details

I need to know which SharePoint site and folder has the documents.

| What I need | Example |
|-------------|---------|
| **SharePoint site URL** | `https://yourcompany.sharepoint.com/sites/Insurance` |
| **Document library name** | Usually just "Documents" or "Shared Documents" |
| **Folder path** (optional) | e.g. `/Policies/2024` — leave blank if you want everything |
| **File types** | Which ones should we pull? PDF, DOCX, TXT, XLSX, etc. |

**Not sure about the library name?** Go into the document library on SharePoint and check the URL — if it says `.../Shared%20Documents/...` then it's "Shared Documents". Most of the time it's just "Documents" though.

---

## 3. Sync preferences

Just let me know:

- **How often** should it sync? (every 30 mins, hourly, daily, etc.)
- **Should it delete** local copies when a file gets removed from SharePoint? Or just keep adding and never remove?

---

## Send me these 7 things

Fill these in and send them over:

```
1. Tenant ID:
2. Client ID:
3. Client Secret:
4. SharePoint site URL:
5. Document library name:
6. File types to sync:
7. Sync interval:
```

**Heads up** — the Client Secret is sensitive so don't just chuck it in a plain email. Use a secure channel or just put it straight into the `.env` file yourself.

---

## Common issues

- **Can't see "Grant admin consent"?** — You need admin rights. Ask your IT admin to do it.
- **Lost the Client Secret?** — It only shows once when you create it. Just delete the old one and make a new one.
- **Not sure which document library?** — Try "Documents" first, that's the default for most SharePoint sites.
