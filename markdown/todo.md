### Todo.

Perfect — you're designing a hybrid ingestion mode that captures real Gmail data once, then reuses it offline for simulation. Here's how to implement it cleanly and modularly:

---

## ✅ Goal

When `--build-simulation-gmail-box` is passed:
- Authenticate and ingest real Gmail messages
- Save the raw Gmail API responses (or parsed metadata) to a local file (e.g., `simulated_gmail.json`)
- Exit after saving — no DB writes yet

Later, during dev:
- Use `--simulate-gmail` to ingest from that local file instead of hitting Gmail

---

## 🧱 Implementation Plan

### 1. **Extend CLI Flags in `main.py`**
```python
parser.add_argument("--build-simulation-gmail-box", action="store_true", help="Fetch real Gmail messages and save to local file")
parser.add_argument("--simulate-gmail", action="store_true", help="Ingest from local Gmail simulation file instead of live Gmail")
```

---

### 2. **Simulation File Location**
Define a constant:
```python
SIM_FILE = "simulated_gmail.json"
```

---

### 3. **If `--build-simulation-gmail-box` is set**
Replace the full sync logic with:

```python
if args.build_simulation_gmail_box:
    print("📥 Fetching real Gmail messages for simulation...")
    query = build_query()
    messages = fetch_all_messages(service, query)

    # Fetch full message payloads
    full_messages = []
    for idx, msg in enumerate(messages, start=1):
        msg_id = msg["id"]
        try:
            full = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            full_messages.append(full)
            print(f"[{idx}/{len(messages)}] ✅ Saved {msg_id}")
        except Exception as e:
            print(f"[{idx}/{len(messages)}] ❌ Failed to fetch {msg_id}: {e}")

    # Save to file
    import json
    with open(SIM_FILE, "w", encoding="utf-8") as f:
        json.dump(full_messages, f, indent=2)

    print(f"✅ Saved {len(full_messages)} messages to {SIM_FILE}")
    sys.exit(0)
```

---

### 4. **If `--simulate-gmail` is set**
Bypass Gmail auth and load from file:

```python
if args.simulate_gmail:
    print("🧪 Simulation mode: loading Gmail messages from local file")
    import json
    with open(SIM_FILE, "r", encoding="utf-8") as f:
        simulated_messages = json.load(f)

    print(f"📄 Loaded {len(simulated_messages)} simulated messages")

    for idx, msg in enumerate(simulated_messages, start=1):
        msg_id = msg["id"]
        try:
            result = ingest_message(None, msg_id, raw_message=msg)
            print(f"[{idx}/{len(simulated_messages)}] ✅ {result} {msg_id}")
        except Exception as e:
            print(f"[{idx}/{len(simulated_messages)}] ❌ Failed to ingest {msg_id}: {e}")
    sys.exit(0)
```

You’ll need to modify `ingest_message()` to accept a `raw_message` override and skip the Gmail API call if it’s provided.

---

### 5. **Patch `ingest_message()` in `parser.py`**
```python
def ingest_message(service, msg_id, raw_message=None):
    if raw_message:
        message = raw_message
    else:
        message = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    ...
```

---

## 🧪 Final CLI Usage

- To build the simulation file:
  ```bash
  python main.py --build-simulation-gmail-box
  ```

- To ingest from it offline:
  ```bash
  python main.py --simulate-gmail
  ```

---

Let me know if you want to version the simulation file, anonymize sensitive fields, or scaffold a `simulate_gmail.py` module. This hybrid mode is a brilliant move — it gives you reproducible, real-world test data without hammering the Gmail API.
