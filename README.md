# holon-lab-baseline

Realistic WordPress traffic generator for DDoS detection research. Generates legitimate "baseline" traffic patterns that [holon-rs](https://github.com/your-org/holon-rs) learns to distinguish from attack traffic.

## Overview

This project provides:
- **WordPress environment** running on Docker (nginx + PHP-FPM + MariaDB)
- **Multi-IP egress proxy** via Squid + macvlan interfaces (23 unique source IPs)
- **Autonomous traffic generators** using Playwright + LLM-driven behavior:
  - **User agents**: Browse posts, leave comments, navigate naturally
  - **Admin agents**: Create posts with AI-generated content and images, moderate comments

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Host Machine                            │
│  ┌─────────────────┐    ┌─────────────────────────────────────┐ │
│  │  Traffic Gen    │    │  Squid Proxy (ports 40001-40023)    │ │
│  │  (Playwright +  │───▶│  Each port binds to different       │ │
│  │   Ollama LLM)   │    │  macvlan IP for unique source       │ │
│  └─────────────────┘    └──────────────┬──────────────────────┘ │
│                                        │                        │
│  ┌─────────────────────────────────────▼──────────────────────┐ │
│  │                    macvlan interfaces                       │ │
│  │   macv1 (192.168.1.131) ... macv23 (192.168.1.153)         │ │
│  └─────────────────────────────────────┬──────────────────────┘ │
│                                        │                        │
└────────────────────────────────────────┼────────────────────────┘
                                         │ LAN
┌────────────────────────────────────────▼────────────────────────┐
│                    Docker macvlan network                       │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                  │
│  │  nginx   │◀──▶│ wordpress│◀──▶│ mariadb  │                  │
│  │ :443/80  │    │ (PHP-FPM)│    │ :3306    │                  │
│  │ .1.200   │    │          │    │          │                  │
│  └──────────┘    └──────────┘    └──────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Docker + Docker Compose
- Squid proxy (`apt install squid`)
- Python 3.10+ with:
  - `playwright` (+ browsers: `playwright install`)
  - `langchain`, `langchain-ollama`
  - `python-dotenv`, `aiohttp`, `matplotlib`, `pillow`
- Ollama running locally with a model (e.g., `llama3.2`)
- Network interface for macvlan (default: `eno1`)

## Quick Start

### 1. Environment Setup

```bash
cp .env.example .env
# Edit .env with your credentials:
#   WP_ADMIN_USER, WP_ADMIN_PASS, MYSQL_ROOT_PASSWORD, etc.
```

### 2. Create Macvlan Interfaces + Squid Config

```bash
sudo ./setup-squid-macvlans.sh
```

This creates 23 macvlan interfaces (macv1-macv23) with DHCP IPs and configures Squid to bind each port (40001-40023) to a different outgoing IP.

### 3. Start WordPress Stack

```bash
docker-compose up -d
```

WordPress will be available at `https://wp-lab` (or the IP at 192.168.1.200).

### 4. Initialize Content (First Run)

```bash
python create_initial_posts.py
```

Creates seed posts and comments for agents to interact with.

### 5. Run Traffic Generator

```bash
python wordpress_traffic_generator.py
```

Launches multiple browser agents that generate realistic traffic patterns.

## Configuration

### Environment Variables (.env)

| Variable | Description |
|----------|-------------|
| `WP_ADMIN_USER` | WordPress admin username |
| `WP_ADMIN_PASS` | WordPress admin password |
| `WORDPRESS_HOST` | WordPress hostname (default: wp-lab) |
| `MYSQL_ROOT_PASSWORD` | MariaDB root password |
| `OLLAMA_MODEL` | LLM model for content generation |

### Traffic Generator Settings

Edit `wordpress_traffic_generator.py` Config class:
- `num_users`: Number of concurrent user agents (default: 5)
- `num_admins`: Number of admin agents (default: 1)
- `session_duration_minutes`: How long each agent runs

## File Structure

```
holon-lab-baseline/
├── docker-compose.yml          # WordPress + nginx + MariaDB stack
├── nginx.conf                  # nginx configuration
├── nginx-entrypoint.sh         # Container DHCP setup
├── setup-squid-macvlans.sh     # Main setup: macvlans + squid config
├── force-hairpin.sh            # Routing for traffic inspection
├── wordpress_traffic_generator.py  # Main traffic generator
├── create_initial_posts.py     # Seed content creator
├── .env.example                # Environment template
└── README.md
```

## Integration with holon-lab-ddos

This project generates the "good" traffic. To capture it for analysis:

```bash
# In holon-lab-ddos directory, run packet capture:
sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' wordpress-lemp-nginx-1) \
  -n ./target/release/pcap_capture eth1 /tmp/baseline.pcap 1

# Then run traffic generator here
python wordpress_traffic_generator.py
```

The captured pcap contains legitimate traffic patterns for training holon's VSA/HDC embeddings.

## Traffic Patterns Generated

**User Agents:**
- Homepage browsing
- Post reading (random selection)
- Comment submission (LLM-generated)
- Natural delays between actions

**Admin Agents:**
- Post creation with LLM-generated titles and 5-6 paragraph bodies
- Featured image generation (charts, diagrams, headers)
- Comment moderation (approve/reject/reply)
- Balanced activity distribution

## License

MIT
