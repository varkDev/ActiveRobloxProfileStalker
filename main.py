import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")

import requests
import time
import os
from rich import print
from rich.console import Console
from rich.panel import Panel
from datetime import datetime, timezone

console = Console()

# Fixed webhook identity
WEBHOOK_NAME = "Varkzy's Stalker"
WEBHOOK_AVATAR_URL = "https://i.imgur.com/m1AQm3T.png"

presence_map = {
    0: "Offline",
    1: "Online",
    2: "In-Game",
    3: "In Studio",
    4: "Invisible",
}

def read_webhook_url(filename="webhook.txt"):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            url = f.read().strip()
            if url:
                return url
            else:
                console.print("[yellow]⚠️ webhook.txt is empty; Discord webhook messages will be skipped.[/yellow]")
    except FileNotFoundError:
        console.print(f"[yellow]⚠️ {filename} not found; Discord webhook messages will be skipped.[/yellow]")
    return None

def username_to_userid(username):
    res = requests.post("https://users.roblox.com/v1/usernames/users", json={"usernames": [username]})
    if res.ok:
        data = res.json().get("data", [])
        if data:
            return str(data[0]["id"])
    return None

def get_avatar(userid):
    url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={userid}&size=420x420&format=Png&isCircular=false"
    res = requests.get(url)
    if res.ok and res.json().get("data"):
        return res.json()["data"][0].get("imageUrl", None)
    return None

def get_presence(userid):
    res = requests.post("https://presence.roblox.com/v1/presence/users", json={"userIds": [userid]})
    if res.ok:
        return presence_map.get(res.json()["userPresences"][0].get("userPresenceType", 0), "Unknown")
    return "Unknown"

def get_profile(userid):
    res = requests.get(f"https://users.roblox.com/v1/users/{userid}")
    if res.status_code == 200:
        data = res.json()
        return {
            "id": str(data.get("id")),
            "username": data.get("name", "Unknown"),
            "display_name": data.get("displayName", data.get("name", "Unknown")),
            "description": data.get("description", "No description."),
            "avatar_url": get_avatar(userid),
            "presence": get_presence(userid),
        }
    return None

def fetch_paginated_ids(url_base):
    user_ids = []
    cursor = None
    while True:
        url = f"{url_base}&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        res = requests.get(url)
        if not res.ok:
            break
        data = res.json()
        user_ids.extend([str(user["id"]) for user in data.get("data", [])])
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
    return user_ids

def resolve_user_info(user_ids):
    users = []
    for i in range(0, len(user_ids), 100):
        batch = user_ids[i:i + 100]
        res = requests.post("https://users.roblox.com/v1/users", json={"userIds": batch})
        if res.ok:
            batch_users = res.json()
            if isinstance(batch_users, dict) and "data" in batch_users:
                users.extend(batch_users["data"])
            elif isinstance(batch_users, list):
                users.extend(batch_users)
    return users

def format_user_list(user_list):
    return {str(u["id"]): u["name"] for u in user_list}

def fetch_friends(userid):
    ids = fetch_paginated_ids(f"https://friends.roblox.com/v1/users/{userid}/friends?")
    users = resolve_user_info(ids)
    return format_user_list(users)

def fetch_followers(userid):
    ids = fetch_paginated_ids(f"https://friends.roblox.com/v1/users/{userid}/followers?")
    users = resolve_user_info(ids)
    return format_user_list(users)

def fetch_following(userid):
    ids = fetch_paginated_ids(f"https://friends.roblox.com/v1/users/{userid}/followings?")
    users = resolve_user_info(ids)
    return format_user_list(users)

def profiles_differ(old, new):
    keys = ("display_name", "description", "presence")
    return any(old.get(k) != new.get(k) for k in keys)

def format_profile_changes(old, new):
    changes = []
    for key in ("display_name", "description", "presence"):
        if old.get(key) != new.get(key):
            changes.append(f"**{key.replace('_', ' ').title()}:**\n`{old.get(key)}` → `{new.get(key)}`")
    return "\n".join(changes)

def format_user_changes(old_dict, new_dict, label):
    added = [uid for uid in new_dict if uid not in old_dict]
    removed = [uid for uid in old_dict if uid not in new_dict]
    lines = []
    if added:
        lines.append(f"🟢 **Added {label}:**")
        for uid in added:
            uname = new_dict[uid]
            lines.append(f"`{uname}` — https://roblox.com/users/{uid}")
    if removed:
        lines.append(f"🔴 **Removed {label}:**")
        for uid in removed:
            uname = old_dict[uid]
            lines.append(f"`{uname}` — https://roblox.com/users/{uid}")
    return "\n".join(lines)

def send_to_discord(webhook_url, old_profile, new_profile, old_friends, new_friends, old_followers, new_followers, old_following, new_following, initial=False):
    content_sections = []

    if initial:
        desc = (
            f"**Display Name:** `{new_profile['display_name']}`\n"
            f"**Description:** `{new_profile['description']}`\n"
            f"**Status:** `{new_profile['presence']}`"
        )
        content_sections.append(desc)
    else:
        profile_changes = format_profile_changes(old_profile, new_profile)
        if profile_changes:
            content_sections.append(f"📝 **Profile Updates:**\n{profile_changes}")

        friends_changes = format_user_changes(old_friends, new_friends, "Friends")
        if friends_changes:
            content_sections.append(friends_changes)

        followers_changes = format_user_changes(old_followers, new_followers, "Followers")
        if followers_changes:
            content_sections.append(followers_changes)

        following_changes = format_user_changes(old_following, new_following, "Following")
        if following_changes:
            content_sections.append(following_changes)

        if not content_sections:
            return False

    embed = {
        "title": f"{new_profile['display_name']} (@{new_profile['username']})",
        "url": f"https://roblox.com/users/{new_profile['id']}",
        "color": 0x00aaff,
        "description": "\n\n".join(content_sections),
        "footer": {"text": f"Powered by {WEBHOOK_NAME} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"}, 
    }
    if new_profile["avatar_url"]:
        embed["thumbnail"] = {"url": new_profile["avatar_url"]}

    payload = {
        "username": WEBHOOK_NAME,
        "avatar_url": WEBHOOK_AVATAR_URL,
        "embeds": [embed]
    }

    res = requests.post(webhook_url, json=payload)
    if res.status_code == 204:
        console.print("[green]✅ Sent update to Discord.[/green]")
        return True
    else:
        console.print(f"[red]❌ Discord webhook failed: {res.status_code} - {res.text}[/red]")
        return False

def monitor_user(user_input, webhook_url, interval=10):
    userid = user_input if user_input.isdigit() else username_to_userid(user_input)
    if not userid:
        console.print("[red]❌ Could not resolve username to user ID.[/red]")
        return

    console.print(f"[blue]🔍 Watching Roblox user ID: {userid} every {interval} seconds...[/blue]")

    last_profile = None
    last_friends = {}
    last_followers = {}
    last_following = {}

    while True:
        new_profile = get_profile(userid)
        new_friends = fetch_friends(userid)
        new_followers = fetch_followers(userid)
        new_following = fetch_following(userid)

        if new_profile is None:
            console.print("[red]❌ Failed to fetch profile. Retrying...[/red]")
            time.sleep(interval)
            continue

        if last_profile is None:
            console.print(Panel(f"[bold cyan]Now tracking {new_profile['display_name']} (@{new_profile['username']})[/bold cyan]"))
            send_to_discord(webhook_url, {}, new_profile, {}, {}, {}, {}, {}, {}, initial=True)
        else:
            changed = False
            if profiles_differ(last_profile, new_profile):
                changed = True

            if last_friends != new_friends or last_followers != new_followers or last_following != new_following:
                changed = True

            if changed:
                console.print(f"[yellow]⚠️ Change detected at {datetime.now().strftime('%H:%M:%S')}![/yellow]")
                send_to_discord(webhook_url, last_profile, new_profile, last_friends, new_friends, last_followers, new_followers, last_following, new_following)
            else:
                console.print(f"[dim]{datetime.now().strftime('%H:%M:%S')} — No changes.[/dim]")

        last_profile = new_profile
        last_friends = new_friends
        last_followers = new_followers
        last_following = new_following

        time.sleep(interval)

if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    console.print(Panel(f"[bold cyan]Roblox Profile Watcher[/bold cyan]\nBy {WEBHOOK_NAME}", border_style="blue"))

    print("Updates are ONLY sent whilst the script is running!")
    user_input = input("Enter Roblox username or user ID to monitor: ").strip()
    webhook_url = read_webhook_url()

    if not webhook_url:
        console.print("[yellow]⚠️ No webhook URL provided. The script will run but won't send anything to Discord.[/yellow]")

    monitor_user(user_input, webhook_url, interval=30)
