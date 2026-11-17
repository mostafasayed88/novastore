# Wiring the WhatsApp channel (Sprint 13 roadmap)

The agent core is channel-agnostic: WhatsApp only needs to (1) receive a
message, (2) call the same `agent.run(...)` the web chat uses, (3) send the
reply back through Meta's Graph API. The backend already exposes the webhook
endpoint - it answers 501 "not configured yet" until you finish the steps
below.

```
WhatsApp user -> Meta Cloud API -> POST /webhook/whatsapp  -> agent.run(...)
                                 GET  /webhook/whatsapp    -> Meta verification
reply path:      Graph API POST /{phone_number_id}/messages <- same AgentReply
```

## 1. Prerequisites

- A Meta developer account: <https://developers.facebook.com/>
- A Meta **Business** account (free tier is fine for testing)
- An app with the **WhatsApp** product added -> note these three values:
  - `WHATSAPP_TOKEN` - permanent (system user) access token
  - `WHATSAPP_PHONE_NUMBER_ID` - the test phone number id
  - `WHATSAPP_VERIFY_TOKEN` - any random string YOU invent; you will paste
    the same string in the Meta dashboard later

Put all three into your `.env`. The `GET` verification handler is already
implemented and compares `hub.verify_token` against `WHATSAPP_VERIFY_TOKEN`.

## 2. Register the webhook

In the Meta App Dashboard -> WhatsApp -> Configuration:

- Callback URL: `https://your-public-domain/webhook/whatsapp`
  (for local testing use a tunnel such as ngrok: `ngrok http 8000`)
- Verify token: the same `WHATSAPP_VERIFY_TOKEN` you set in `.env`
- Subscribe to the **messages** field

Meta calls `GET /webhook/whatsapp?hub.mode=subscribe&...` once - the
existing handler echoes `hub.challenge` when the token matches (HTTP 403
otherwise).

## 3. Implement the inbound parser (the TODO)

`POST /webhook/whatsapp` currently returns 501. Once your credentials work,
parse Meta's envelope and call the agent. The payload shape:

```json
{
  "entry": [{
    "changes": [{
      "value": {
        "messages": [{"from": "2010XXXXXXX", "text": {"body": "Where is order 5482?"}}],
        "metadata": {"phone_number_id": "..."}
      }
    }]
  }]
}
```

Implementation sketch for `src/novastore/api/routes.py`:

```python
@router.post("/webhook/whatsapp")
def whatsapp_inbound(request: Request, payload: dict):
    settings = get_settings_from(request)
    agent = request.app.state.agent
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                text = msg.get("text", {}).get("body", "")
                sender = msg["from"]                     # WhatsApp number
                session_id = f"wa_{sender}"              # one session per number
                customer_id = map_to_customer(sender)    # lookup/create in `customers`
                reply = agent.run(session_id, customer_id, text)
                send_whatsapp_text(sender, reply.reply, settings)
    return {"status": "received"}
```

And the outbound sender (pure HTTP, same style as `GroqClient`):

```python
import httpx

def send_whatsapp_text(to: str, text: str, settings) -> None:
    url = f"https://graph.facebook.com/v21.0/{settings.whatsapp_phone_number_id}/messages"
    httpx.post(
        url,
        headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text[:4096]},
        },
        timeout=30,
    )
```

## 4. Mapping senders to customers

Keep it simple and explicit:

- Maintain a `customers.phone` lookup (the seeded demo customers have
  placeholder phones). On an unknown number, create a retail customer named
  "WhatsApp guest" - or ask the person for their email and match.
- Use `session_id = "wa_" + phone number` so memory and transcripts group
  naturally per contact, and the admin dashboard shows WhatsApp sessions
  next to web ones.

## 5. Production notes

- Reply within 24 hours of the user's last message (Meta rule) - the agent
  is instant, tickets are for humans, so this is easy.
- Meta requires a template message to START a conversation; replies within
  an open session can be free-form text.
- Don't log phone numbers verbatim; mask them in `logs/novastore.log`
  (same discipline as never logging API keys).
- Rate limits: add a small retry with backoff around `send_whatsapp_text`.

## 6. Test checklist

1. `GET /webhook/whatsapp` with the right token returns the challenge.
2. Send "Where is order 5482?" from the test number -> factual status reply.
3. "Cancel order 5391" -> confirmation round-trip works over two WhatsApp
   messages (pending actions are per session, and the session id is stable).
4. "I want to talk to a person" -> ticket appears in the admin dashboard.
