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

create or replace function public.spin_once(p_id text)
returns jsonb
language plpgsql
as $$
declare
	v_state jsonb;
	v_options jsonb;
	v_pool int[];
	v_pool_len int;
	v_pick_idx int;
	v_winner_idx int;
	v_winner jsonb;
	v_spin_id int;
	v_labels text[];
begin
	insert into public.spinner_state (id, state)
	values (p_id, jsonb_build_object('options', '[]'::jsonb, 'spin_id', 0, 'updated_at', extract(epoch from now())))
	on conflict (id) do nothing;

	select state into v_state
	from public.spinner_state
	where id = p_id
	for update;

	v_options := coalesce(v_state->'options', '[]'::jsonb);

	select array_agg((elem.ordinality - 1)::int)
	into v_pool
	from jsonb_array_elements(v_options) with ordinality as elem(value, ordinality)
	where coalesce((elem.value->>'remaining')::int, 0) > 0;

	v_pool_len := coalesce(array_length(v_pool, 1), 0);
	if v_pool_len = 0 then
		return jsonb_build_object(
			'winner_name', null,
			'winner_description', null,
			'labels_for_spin', '[]'::jsonb,
			'spin_id', coalesce((v_state->>'spin_id')::int, 0)
		);
	end if;

	v_pick_idx := floor(random() * v_pool_len + 1)::int;
	v_winner_idx := v_pool[v_pick_idx];
	v_winner := v_options -> v_winner_idx;

	v_options := jsonb_set(
		v_options,
		array[v_winner_idx::text, 'remaining'],
		to_jsonb(greatest(coalesce((v_winner->>'remaining')::int, 0) - 1, 0)),
		false
	);

	v_spin_id := coalesce((v_state->>'spin_id')::int, 0) + 1;

	update public.spinner_state
	set state = jsonb_build_object(
		'options', v_options,
		'spin_id', v_spin_id,
		'updated_at', extract(epoch from now())
	),
	updated_at = now()
	where id = p_id;

	select array_agg(elem.value->>'name')
	into v_labels
	from jsonb_array_elements(v_options) as elem(value)
	where coalesce((elem.value->>'remaining')::int, 0) > 0;

	return jsonb_build_object(
		'winner_name', v_winner->>'name',
		'winner_description', coalesce(v_winner->>'description', ''),
		'labels_for_spin', to_jsonb(coalesce(v_labels, array[]::text[])),
		'spin_id', v_spin_id
	);
end;
$$;
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
