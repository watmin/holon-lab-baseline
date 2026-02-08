#!/usr/bin/env python3
"""
Create initial WordPress posts via REST API
Requires: requests, python-dotenv (pip install requests python-dotenv)
"""

import requests
import json
import os
from datetime import datetime, timedelta
import random
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# WordPress Configuration (from environment - required)
WP_URL = os.environ["WORDPRESS_URL"]  # e.g., https://wp-lab
WP_USER = os.getenv("WP_ADMIN_USER", "admin")
WP_PASSWORD = os.environ["WP_APP_PASSWORD"]  # Application password for REST API

# Disable SSL warnings for self-signed cert
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Blog posts data
POSTS = [
    {
        "title": "Getting Started with Home Automation in 2026",
        "content": """<p>Smart home technology has come a long way in the past few years. What once seemed like science fiction is now accessible and affordable for most homeowners.</p>

<p>In this guide, I'll walk you through the basics of setting up your first smart home devices and creating automation routines that actually make your life easier.</p>

<h2>Start Small</h2>
<p>Don't try to automate everything at once. Start with one room or one use case. Smart lighting is usually the easiest entry point - you can pick up smart bulbs for under $15 each, and they don't require any rewiring.</p>

<h2>Choose Your Ecosystem</h2>
<p>The three major platforms are:</p>
<ul>
<li>Google Home - Great if you're already in the Google ecosystem</li>
<li>Amazon Alexa - Widest device compatibility</li>
<li>Apple HomeKit - Most privacy-focused, but more expensive</li>
</ul>

<p>You can mix and match, but life is easier if you pick one primary platform.</p>

<h2>Practical Automations</h2>
<p>Here are some automations I use daily:</p>
<ul>
<li>Lights turn on at sunset automatically</li>
<li>Coffee maker starts 10 minutes before my alarm</li>
<li>Thermostat adjusts when I leave for work</li>
<li>Garage door closes automatically if left open for 10 minutes</li>
</ul>

<p>What home automation projects are you working on? Drop a comment below!</p>""",
        "status": "publish",
        "categories": [1]  # Uncategorized
    },
    {
        "title": "My Experience Switching to Linux After 15 Years on Windows",
        "content": """<p>After using Windows since the XP days, I finally made the switch to Linux last month. Here's what I learned.</p>

<h2>Why I Switched</h2>
<p>Honestly, it started with frustration. Windows 11 kept pushing updates at the worst times, and I was tired of the bloat and telemetry. I'd been hearing about how far Linux had come, especially for gaming, so I decided to give it a shot.</p>

<h2>Choosing a Distribution</h2>
<p>I went with Ubuntu 24.04 LTS. I know some Linux veterans roll their eyes at Ubuntu, but for a first-timer, it was perfect. Everything just worked out of the box - WiFi, Bluetooth, even my printer.</p>

<h2>The Good</h2>
<ul>
<li><strong>Speed</strong> - My 5-year-old laptop feels brand new</li>
<li><strong>Control</strong> - I decide when updates happen</li>
<li><strong>Privacy</strong> - No telemetry, no forced Microsoft account</li>
<li><strong>Package management</strong> - Installing software is actually easier than Windows</li>
</ul>

<h2>The Challenges</h2>
<p>Not everything was smooth sailing:</p>
<ul>
<li>Adobe Creative Suite doesn't run natively (I use Affinity Photo now)</li>
<li>Some corporate VPN clients are Windows-only</li>
<li>Gaming works great on Steam, but some anti-cheat games are still problematic</li>
</ul>

<h2>Would I Recommend It?</h2>
<p>Absolutely, with caveats. If you're technical and willing to troubleshoot occasionally, Linux is fantastic. If you rely heavily on specific Windows-only software, maybe dual-boot first.</p>

<p>Anyone else make the switch recently? What distro did you choose?</p>""",
        "status": "publish",
        "categories": [1]
    },
    {
        "title": "The Best Coffee Shops in Seattle for Remote Work",
        "content": """<p>As someone who's been working remotely for three years, I've tried every coffee shop in Seattle that has WiFi and outlets. Here are my top picks.</p>

<h2>1. Analog Coffee - Capitol Hill</h2>
<p>Great atmosphere, solid WiFi, and they don't rush you. The cold brew is excellent. Can get crowded after 10am on weekdays. Best time to go: 7-9am or after 3pm.</p>

<p><strong>Pros:</strong> Large communal tables, plenty of outlets<br>
<strong>Cons:</strong> Music can be loud, limited food options</p>

<h2>2. Victrola Coffee Roasters - Multiple Locations</h2>
<p>The 15th Ave location is my go-to. Spacious, consistent WiFi, and the baristas are cool with people camping out. They roast their own beans, and you can taste the difference.</p>

<p><strong>Pros:</strong> Reliable internet, good seating variety<br>
<strong>Cons:</strong> Parking can be tricky</p>

<h2>3. Slate Coffee - University District</h2>
<p>Modern, minimalist vibe. Perfect if you need to take video calls - they have a quieter back room. The latte art here is Instagram-worthy.</p>

<p><strong>Pros:</strong> Quieter than most, great for calls<br>
<strong>Cons:</strong> Smaller space, can fill up quickly</p>

<h2>Remote Work Etiquette</h2>
<p>A few tips I've learned:</p>
<ul>
<li>Buy something every 2-3 hours</li>
<li>Use headphones, even if you're not listening to anything</li>
<li>Don't take calls during rush hours</li>
<li>Clean up your space when you leave</li>
</ul>

<p>What are your favorite work-from-cafe spots? I'm always looking to expand my rotation!</p>""",
        "status": "publish",
        "categories": [1]
    },
    {
        "title": "Why I'm Building a Homelab in 2026",
        "content": """<p>Cloud services are convenient, but I'm increasingly uncomfortable with how much of my data lives on someone else's computer. Here's why I'm building a homelab and what I'm learning.</p>

<h2>The Privacy Wake-Up Call</h2>
<p>After the recent data breaches and changes to cloud storage policies, I started thinking: why am I paying $15/month for cloud storage when I could own my data?</p>

<h2>My Hardware Setup</h2>
<p>I didn't go crazy expensive:</p>
<ul>
<li>Dell OptiPlex 7050 (used, $200 on eBay)</li>
<li>32GB RAM upgrade ($80)</li>
<li>2x 4TB WD Red drives in RAID 1 ($200)</li>
<li>UPS for power protection ($100)</li>
</ul>

<p>Total cost: ~$600. That's less than 4 years of cloud storage subscriptions.</p>

<h2>Services I'm Running</h2>
<p>All using Docker for easy management:</p>
<ul>
<li><strong>Nextcloud</strong> - Personal cloud storage (goodbye Google Drive)</li>
<li><strong>Jellyfin</strong> - Media server for my movie collection</li>
<li><strong>Bitwarden</strong> - Self-hosted password manager</li>
<li><strong>Pi-hole</strong> - Network-wide ad blocking</li>
<li><strong>Home Assistant</strong> - Smart home automation hub</li>
</ul>

<h2>What I've Learned</h2>
<p>Running your own infrastructure teaches you a lot:</p>
<ul>
<li>Networking fundamentals you never learned in school</li>
<li>Why backups matter (learned this the hard way)</li>
<li>Docker and containerization</li>
<li>Linux system administration</li>
</ul>

<h2>The Downsides</h2>
<p>It's not all sunshine and self-hosting:</p>
<ul>
<li>You're responsible for security and updates</li>
<li>No customer support when things break</li>
<li>Power and internet outages mean downtime</li>
<li>Initial time investment is significant</li>
</ul>

<h2>Is It Worth It?</h2>
<p>For me, absolutely. I love the control and the learning experience. Plus, there's something satisfying about knowing exactly where your data lives.</p>

<p>Anyone else running a homelab? What services are you hosting?</p>""",
        "status": "publish",
        "categories": [1]
    },
    {
        "title": "Lessons from One Year of Daily Meditation",
        "content": """<p>A year ago, I committed to meditating every single day. No exceptions. Here's what changed.</p>

<h2>Starting Out</h2>
<p>I'd tried meditation before - downloaded Headspace, did it for a week, got bored, quit. This time I made a deal with myself: 10 minutes every morning, no matter what. Even if I was traveling, sick, or hungover.</p>

<h2>The First Month Was Hard</h2>
<p>My brain wouldn't shut up. Every session felt like 10 minutes of me thinking about my grocery list while occasionally remembering I was supposed to be meditating. I almost quit multiple times.</p>

<h2>What Changed After 3 Months</h2>
<p>Something clicked. I stopped fighting my thoughts and just watched them. That sounds like hippie nonsense, but it actually works. My mind still wanders, but I'm way faster at noticing and returning to my breath.</p>

<h2>Unexpected Benefits</h2>
<p>Things I didn't expect:</p>
<ul>
<li><strong>Better sleep</strong> - I fall asleep faster and wake up less groggy</li>
<li><strong>Less reactive</strong> - That instant anger when someone cuts me off in traffic? Gone.</li>
<li><strong>Focus</strong> - I can work for longer stretches without checking my phone</li>
<li><strong>Physical tension</strong> - I didn't realize how much tension I carried in my shoulders</li>
</ul>

<h2>What Didn't Change</h2>
<p>I'm not enlightened. I still get stressed, anxious, and frustrated. But there's more space between the stimulus and my reaction. That space is everything.</p>

<h2>My Current Practice</h2>
<p>Still doing 10 minutes most days, sometimes 20 if I have time. I use Insight Timer (free, no subscription required). Simple breath awareness - nothing fancy.</p>

<h2>Advice for Beginners</h2>
<ul>
<li>Start with 5 minutes, not 30</li>
<li>Same time every day (morning works best for me)</li>
<li>You don't need a special cushion or app</li>
<li>Missing a day isn't failure - just start again tomorrow</li>
<li>Your mind will wander. That's normal. That's literally the practice.</li>
</ul>

<p>Anyone else have a meditation practice? What works for you?</p>""",
        "status": "publish",
        "categories": [1]
    }
]

def create_post(post_data):
    """Create a single WordPress post via REST API"""

    auth = (WP_USER, WP_PASSWORD)
    headers = {'Content-Type': 'application/json'}

    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"

    try:
        response = requests.post(
            endpoint,
            auth=auth,
            headers=headers,
            json=post_data,
            verify=False  # Skip SSL verification for self-signed cert
        )

        if response.status_code == 201:
            post = response.json()
            print(f"✓ Created: {post['title']['rendered']} (ID: {post['id']})")
            return True
        else:
            print(f"✗ Failed to create post: {response.status_code}")
            print(f"  Response: {response.text}")
            return False

    except Exception as e:
        print(f"✗ Error creating post: {str(e)}")
        return False

def main():
    print(f"Creating {len(POSTS)} WordPress posts...\n")

    if not WP_PASSWORD:
        print("ERROR: Please update WP_PASSWORD in the script!")
        return

    success_count = 0

    for i, post in enumerate(POSTS, 1):
        print(f"[{i}/{len(POSTS)}] ", end="")
        if create_post(post):
            success_count += 1

    print(f"\n{'='*50}")
    print(f"Created {success_count}/{len(POSTS)} posts successfully!")
    print(f"\nView your posts at: {WP_URL}/wp-admin/edit.php")

if __name__ == "__main__":
    main()
