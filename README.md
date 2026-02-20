# Limited Use Spinner (Streamlit)

This app lets you:
- Add options with a usage limit and description
- Spin a visual wheel animation
- Show the selected result
- Auto-send result + description by email

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

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
