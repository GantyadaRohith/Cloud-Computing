# Limited Use Spinner (Streamlit)

This app lets you:
- Add options with a usage limit and description
- Spin a visual wheel animation
- Show the selected result
- Auto-send result + description by email
- Auto-sync options/results across devices using shared app state

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Multi-device sync

- Options and spin counters are stored in `data/shared_state.json`.
- Any device connected to the same running app instance sees updates automatically.
- The app refreshes every 3 seconds to pull changes from other devices.

Note: if you run separate local app instances on different machines, they will not share data unless they point to the same deployment/storage.

## Cloud sync across separate app instances (Supabase)

To sync data globally across devices and separate deployments, configure Supabase.

1. Create a Supabase project.
2. Run this SQL in the Supabase SQL editor:

```sql
create table if not exists public.spinner_state (
	id text primary key,
	state jsonb not null,
	updated_at timestamptz not null default now()
);
```

3. Add this to `.streamlit/secrets.toml` (or Streamlit Cloud Secrets):

```toml
[sync]
provider = "supabase"
supabase_url = "https://YOUR_PROJECT.supabase.co"
supabase_key = "YOUR_SUPABASE_ANON_OR_SERVICE_KEY"
app_id = "limited-use-spinner"
```

If cloud sync is unavailable, the app automatically falls back to local file sync.

## Deploy to Streamlit Community Cloud

1. Push this project to a GitHub repository.
2. Go to Streamlit Community Cloud and click **Create app**.
3. Select your GitHub repo and branch.
4. Set **Main file path** to `app.py`.
5. Deploy.

### Add SMTP secrets in Streamlit Cloud

In your deployed app dashboard:
- Open **Settings** -> **Secrets**
- Paste this TOML:

```toml
[smtp]
host = "smtp.gmail.com"
port = 587
username = "your_email@gmail.com"
password = "your_gmail_app_password"
from_email = "your_email@gmail.com"
use_tls = true
```

Then save and restart the app.

## Important security note

Do not commit `.streamlit/secrets.toml`.
Use `.streamlit/secrets.toml.example` as template only.

If any real app password was shared/exposed before, rotate it immediately in your email provider.
