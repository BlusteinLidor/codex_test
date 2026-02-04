# RSVP WhatsApp Bot

This app provides a lightweight RSVP workflow:

- Users sign up, log in, pay, and submit event details with invitees.
- Admins review pending events and approve or reject them.
- Approved events trigger simulated WhatsApp invites with approve/reject/maybe responses.
- All data is stored in SQLite.

## Quick start (Python)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open the following pages:

- User signup: `http://localhost:3000/user-signup.html`
- User login: `http://localhost:3000/user-login.html`
- Admin login: `http://localhost:3000/admin-login.html`
- Invite response: `http://localhost:3000/invitee-response.html?id=1`

### Default admin credentials

- Email: `admin@example.com`
- Password: `admin123`

## API overview

- `POST /api/signup`
- `POST /api/login`
- `POST /api/events` (user)
- `GET /api/events/mine` (user)
- `POST /api/events/:id/pay` (user)
- `GET /api/admin/events` (admin)
- `POST /api/admin/events/:id/decision` (admin)
- `GET /api/admin/events/:id/invites` (admin)
- `GET /api/invites/:id`
- `POST /api/invites/:id/respond`
